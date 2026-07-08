"""GateWay Dispatch v0 — driver + board surfaces (GWD-004).
Laws honored: three driver buttons; <=3-tap assignment; every action events.
Temporarily hosted inside the events service per ADR-008 (split at M3).
"""
import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from . import airtable_client as at
from .db import SessionLocal
from .models import Event

router = APIRouter()

ACTION_MAP = {
    "picked_up": {"status": "in_transit", "stamp": "in_transit_at", "event": "order.picked_up"},
    "delivered": {"status": "delivered", "stamp": "delivered_at", "event": "order.delivered"},
    "failed": {"status": "failed", "stamp": "failed_at", "event": "order.failed"},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_event(event_type: str, entity_ref: str, actor: str, payload: dict) -> None:
    """Append to the OWNED event log (Postgres). The truth lives here."""
    db: Session = SessionLocal()
    try:
        db.add(Event(event_type=event_type, entity_ref=entity_ref,
                     tenant="gateway", actor=actor, payload=json.dumps(payload)))
        db.commit()
    finally:
        db.close()


async def _mirror_event_airtable(event_type: str, entity_ref: str, actor: str, payload: str):
    """Mirror to Airtable events table so the founder sees it on his phone."""
    try:
        await at.create_record(at.EVENTS, {
            "event_id": "EVT-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")[:-3],
            "event_type": event_type, "entity_ref": entity_ref,
            "occurred_at": _now(), "actor": actor, "payload": payload,
        })
    except Exception:
        pass  # mirror is best-effort; the owned log is authoritative


async def _driver_by_token(day_token: str) -> dict:
    drivers = await at.list_records(
        at.DRIVERS, formula=f"{{day_token}}='{day_token}'", max_records=1)
    if not drivers:
        raise HTTPException(404, "Unknown day token")
    return drivers[0]


# ---------- DRIVER API ----------

@router.get("/api/driver/{day_token}/orders")
async def driver_orders(day_token: str):
    if not at.configured():
        raise HTTPException(503, "AIRTABLE_PAT not configured")
    drv = await _driver_by_token(day_token)
    records = await at.list_records(
        at.ORDERS,
        formula="OR({status}='assigned',{status}='in_transit')",
        max_records=100,
    )
    mine = [r for r in records if drv["id"] in (r["fields"].get("driver") or [])]
    return {
        "driver": drv["fields"].get("display_name", "Driver"),
        "orders": [{
            "id": r["id"],
            "order_id": r["fields"].get("order_id", ""),
            "status": r["fields"].get("status", ""),
            "pickup": r["fields"].get("pickup_address", ""),
            "dropoff": r["fields"].get("dropoff_address", ""),
            "contact": r["fields"].get("dropoff_contact_name", ""),
            "phone": r["fields"].get("dropoff_contact_phone", ""),
            "items": r["fields"].get("items_description", ""),
            "notes": r["fields"].get("special_instructions", ""),
        } for r in mine],
    }


@router.post("/api/driver/{day_token}/orders/{record_id}/{action}")
async def driver_action(day_token: str, record_id: str, action: str, request: Request):
    if action not in ACTION_MAP:
        raise HTTPException(400, "Action must be picked_up, delivered, or failed")
    drv = await _driver_by_token(day_token)
    spec = ACTION_MAP[action]
    fields = {"status": spec["status"], spec["stamp"]: _now()}
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    if action == "failed" and body.get("reason"):
        fields["fail_reason"] = str(body["reason"])[:200]
    updated = await at.patch_record(at.ORDERS, record_id, fields)
    order_id = updated.get("fields", {}).get("order_id", record_id)
    actor = f"driver:{drv['fields'].get('display_name','?')}"
    _log_event(spec["event"], order_id, actor, {"action": action, **fields})
    await _mirror_event_airtable(spec["event"], order_id, actor, json.dumps(fields))
    return {"ok": True, "order_id": order_id, "new_status": spec["status"]}


# ---------- BOARD API (founder) ----------

def _check_key(key: str):
    admin = os.environ.get("ADMIN_KEY", "")
    if not admin or key != admin:
        raise HTTPException(403, "Bad board key")


@router.get("/api/board/{key}/orders")
async def board_orders(key: str):
    _check_key(key)
    records = await at.list_records(
        at.ORDERS,
        formula="NOT(OR({status}='closed',{status}='cancelled'))",
        max_records=100,
    )
    drivers = await at.list_records(at.DRIVERS, formula="{status}!='inactive'")
    return {
        "orders": [{
            "id": r["id"],
            "order_id": r["fields"].get("order_id", ""),
            "status": r["fields"].get("status", ""),
            "customer": r["fields"].get("customer_name_raw", ""),
            "pickup": r["fields"].get("pickup_address", ""),
            "dropoff": r["fields"].get("dropoff_address", ""),
            "items": r["fields"].get("items_description", ""),
            "driver": (r["fields"].get("driver") or [None])[0],
        } for r in records],
        "drivers": [{"id": d["id"], "name": d["fields"].get("display_name", "")}
                    for d in drivers],
    }


@router.post("/api/board/{key}/orders/{record_id}/assign")
async def assign_order(key: str, record_id: str, request: Request):
    _check_key(key)
    body = await request.json()
    driver_rec = body.get("driver_id")
    if not driver_rec:
        raise HTTPException(400, "driver_id required")
    updated = await at.patch_record(at.ORDERS, record_id, {
        "driver": [driver_rec], "status": "assigned", "assigned_at": _now(),
    })
    order_id = updated.get("fields", {}).get("order_id", record_id)
    _log_event("order.assigned", order_id, "founder", {"driver": driver_rec})
    await _mirror_event_airtable("order.assigned", order_id, "founder", driver_rec)
    return {"ok": True, "order_id": order_id}


@router.post("/api/board/{key}/orders/{record_id}/confirm")
async def confirm_order(key: str, record_id: str):
    _check_key(key)
    updated = await at.patch_record(at.ORDERS, record_id, {
        "status": "confirmed", "confirmed_at": _now(),
    })
    order_id = updated.get("fields", {}).get("order_id", record_id)
    _log_event("order.confirmed", order_id, "founder", {})
    await _mirror_event_airtable("order.confirmed", order_id, "founder", "")
    return {"ok": True, "order_id": order_id}
