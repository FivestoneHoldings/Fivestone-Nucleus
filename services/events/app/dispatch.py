"""GateWay Dispatch v0 — driver + board surfaces (GWD-004).
Laws honored: three driver buttons; <=3-tap assignment; every action events.
Temporarily hosted inside the events service per ADR-008 (split at M3).
"""
import json
import os
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy.orm import Session

from . import airtable_client as at
from . import notify
from .bizday import business_day, business_day_of
from .db import SessionLocal
from .models import Event, Proof, DriverLocation

router = APIRouter()

# Legal transitions: {target_action: (allowed_from, idempotent_when)}
TRANSITIONS = {
    "confirm":   ({"received"}, {"confirmed"}),
    "assign":    ({"received", "confirmed"}, set()),
    "picked_up": ({"assigned"}, {"in_transit"}),
    "delivered": ({"in_transit"}, {"delivered", "closed"}),
    "failed":    ({"assigned", "in_transit"}, {"failed"}),
    "close":     ({"delivered"}, {"closed"}),
    "cancel":    ({"received", "confirmed", "assigned", "in_transit", "failed"}, {"cancelled"}),
    "requeue":   ({"failed"}, {"confirmed"}),
}


def _guard(action: str, current: str):
    """Returns 'proceed' | 'idempotent' or raises 409 with a human message."""
    allowed, idem = TRANSITIONS[action]
    if current in allowed:
        return "proceed"
    if current in idem:
        return "idempotent"
    raise HTTPException(409, f"Can't {action.replace('_', ' ')} an order that is "
                             f"'{current.replace('_', ' ')}' — refresh and try again.")


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
    cached = _cget(f"drv:{day_token}")
    if cached is not None:
        return cached
    drivers = await at.list_records(
        at.DRIVERS, formula=f"{{day_token}}='{_fq(day_token)}'", max_records=1)
    if not drivers:
        raise HTTPException(404, "Unknown day token")
    _cput(f"drv:{day_token}", drivers[0], 30)
    return drivers[0]


import re as _re


def _fq(v: str) -> str:
    """Formula-quote sanitizer: strips anything that could escape an Airtable
    filterByFormula single-quoted string. IDs/tokens/codes only ever contain these."""
    return _re.sub(r"[^A-Za-z0-9 _.@+\-]", "", str(v or ""))[:120]


# ---------- DATA RETENTION ----------
_LAST_SWEEP = {"t": 0.0}


def retention_sweep(force: bool = False):
    """Age out operational exhaust: driver locations >24h, proof photos >60d.
    Cheap, opportunistic (at most hourly), never blocks a request path."""
    import time as _t
    if not force and _t.time() - _LAST_SWEEP["t"] < 3600:
        return {"swept": False}
    _LAST_SWEEP["t"] = _t.time()
    from datetime import timedelta
    from .models import Proof
    db: Session = SessionLocal()
    try:
        cut_loc = datetime.now(timezone.utc) - timedelta(hours=24)
        cut_proof = datetime.now(timezone.utc) - timedelta(days=60)
        n_loc = (db.query(DriverLocation)
                 .filter(DriverLocation.updated_at < cut_loc.replace(tzinfo=None))
                 .delete(synchronize_session=False))
        n_proof = (db.query(Proof)
                   .filter(Proof.created_at < cut_proof.replace(tzinfo=None))
                   .delete(synchronize_session=False))
        db.commit()
    finally:
        db.close()
    return {"swept": True, "locations_purged": n_loc, "proofs_purged": n_proof}


# ---------- TTL CACHE (slow-changing lookups only; mutations bust it) ----------
import time as _time

_TTL_CACHE: dict = {}


def _cget(key: str):
    hit = _TTL_CACHE.get(key)
    if hit and _time.time() < hit[1]:
        return hit[0]
    return None


def _cput(key: str, value, ttl: float):
    _TTL_CACHE[key] = (value, _time.time() + ttl)


def _cbust():
    _TTL_CACHE.clear()


# ---------- DIAGNOSTICS (no secrets returned; booleans only) ----------

@router.get("/api/diag")
async def diag():
    return {
        "airtable_pat_set": at.configured(),
        "stripe_configured": __import__("app.payments", fromlist=["configured"]).configured(),
        "admin_key_set": bool(os.environ.get("ADMIN_KEY")),
        "service": "nucleus-dispatch",
        "note": "If either is false, the Railway Variable did not save or the service has not redeployed since it was added.",
    }


# ---------- DRIVER API ----------

@router.get("/api/driver/{day_token}/orders")
async def driver_orders(day_token: str):
    if not at.configured():
        raise HTTPException(503, "AIRTABLE_PAT not configured")
    drv = await _driver_by_token(day_token)
    pay_by_order: dict = {}
    today = business_day()
    # Split queries: active (assigned/in_transit) and delivered-today run
    # separately AND concurrently. The old combined query capped at 100 records
    # total — on a busy day, delivered rows could crowd active assignments out
    # of the window and a driver's live order would silently vanish from their
    # hub. Now active orders have their own full window and can never be
    # truncated out by history.
    import asyncio as _aio
    records, done_today = await _aio.gather(
        at.list_records(
            at.ORDERS,
            formula="OR({status}='assigned',{status}='in_transit')",
            max_records=100),
        at.list_records(
            at.ORDERS,
            formula=(f"AND(OR({{status}}='delivered',{{status}}='closed'),"
                     f"DATETIME_FORMAT(SET_TIMEZONE({{delivered_at}},'America/New_York'),'YYYY-MM-DD')='{today}')"),
            max_records=100),
    )
    combined = list(records) + list(done_today)
    mine = [r for r in records if drv["id"] in (r["fields"].get("driver") or [])]
    mine.sort(key=lambda r: (r["fields"].get("requested_for")
                             or r["fields"].get("received_at") or "9999"))
    mine_ids = [r["fields"].get("order_id", "") for r in mine]
    ready_ids: set = set()
    if mine_ids:
        _dbr: Session = SessionLocal()
        try:
            _rows = (_dbr.query(Event)
                     .filter(Event.event_type == "order.kitchen_ready",
                             Event.entity_ref.in_(mine_ids)).all())
            ready_ids = {e.entity_ref for e in _rows}
            import json as _pj
            for e in (_dbr.query(Event)
                      .filter(Event.event_type == "order.payment_method",
                              Event.entity_ref.in_(mine_ids)).all()):
                try:
                    pay_by_order[e.entity_ref] = _pj.loads(e.payload).get("method", "cod")
                except Exception:
                    pay_by_order[e.entity_ref] = "cod"
        finally:
            _dbr.close()
    done_recs = [r for r in combined
                 if r["fields"].get("status") in ("delivered", "closed")]
    my_done = [r for r in done_recs if drv["id"] in (r["fields"].get("driver") or [])]
    my_done.sort(key=lambda r: r["fields"].get("delivered_at") or "", reverse=True)
    done_today = len(my_done)
    tips_today = sum(int(r["fields"].get("tip_cents") or 0) for r in my_done)
    return {
        "driver": drv["fields"].get("display_name", "Driver"),
        "shift": drv["fields"].get("status", "") == "on_shift",
        "done_today": done_today,
        "tips_today_cents": tips_today,
        # v1.9: the hub's My-day history — each completed run, newest first,
        # so a driver can review their day instead of staring at a bare count.
        "done_list": [{
            "order_id": r["fields"].get("order_id", ""),
            "dropoff": r["fields"].get("dropoff_address", ""),
            "delivered_at": r["fields"].get("delivered_at", ""),
            "tip_cents": int(r["fields"].get("tip_cents") or 0),
            "total_cents": int(r["fields"].get("total_cents") or 0),
        } for r in my_done[:30]],
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
            "requested_for": r["fields"].get("requested_for", ""),
            "kitchen_ready": r["fields"].get("order_id", "") in ready_ids,
            "collect_cash_cents": _cash_due(r["fields"], pay_by_order),
            "total_cents": int(r["fields"].get("total_cents") or 0),
        } for r in mine],
    }


# ---------- DRIVER NOTES ----------

@router.post("/api/driver/{day_token}/orders/{record_id}/note")
async def driver_note(day_token: str, record_id: str, request: Request):
    drv = await _driver_by_token(day_token)
    body = await request.json()
    text = str(body.get("text", "")).strip()[:400]
    if not text:
        raise HTTPException(400, "text required")
    recs = await at.list_records(at.ORDERS, formula=f"RECORD_ID()='{_fq(record_id)}'", max_records=1)
    order_id = recs[0]["fields"].get("order_id", record_id) if recs else record_id
    actor = f"driver:{drv['fields'].get('display_name','?')}"
    _log_event("order.driver_note", order_id, actor, {"note": text})
    await _mirror_event_airtable("order.driver_note", order_id, actor, text)
    return {"ok": True}


# ---------- SHIFT TOGGLE ----------

@router.post("/api/driver/{day_token}/shift")
async def toggle_shift(day_token: str, request: Request):
    drv = await _driver_by_token(day_token)
    body = await request.json()
    on = bool(body.get("on", True))
    new_status = "on_shift" if on else "active"
    await at.patch_record(at.DRIVERS, drv["id"], {"status": new_status})
    actor = f"driver:{drv['fields'].get('display_name','?')}"
    _log_event("driver.shift_started" if on else "driver.shift_ended",
               drv["fields"].get("driver_id", drv["id"]), actor, {})
    _cbust()
    return {"ok": True, "shift": on}


# ---------- PROOF OF DELIVERY ----------

@router.get("/api/driver/{day_token}/hq")
async def driver_hq_contact(day_token: str):
    """How this driver reaches a human right now.

    The phone number is configured per-deployment rather than hardcoded, and if
    it isn't set we return an empty string so the UI hides the call/text buttons
    instead of showing a dead link — a driver tapping 'Call dispatch' and
    reaching nothing is worse than not offering it at all."""
    await _driver_by_token(day_token)   # authenticates the driver
    import os as _os
    return {"phone": _os.environ.get("GATEWAY_HQ_PHONE", "").strip(),
            "hours": _os.environ.get("GATEWAY_HQ_HOURS", "").strip()}


# What a driver can flag, worst first. Severity decides how loudly the board
# shouts, so a safety emergency never queues behind a missing-drink question.
DRIVER_ISSUES = {
    "safety":    ("🚨 Safety emergency", "critical"),
    "accident":  ("🚗 Accident or vehicle trouble", "critical"),
    "address":   ("📍 Can't find / unsafe address", "urgent"),
    "customer":  ("🙍 Problem with the customer", "urgent"),
    "kitchen":   ("🍳 Problem at the kitchen", "urgent"),
    "order":     ("🧾 Order is wrong or incomplete", "normal"),
    "app":       ("📱 Something in the app is broken", "normal"),
    "other":     ("💬 Something else", "normal"),
}


@router.post("/api/driver/{day_token}/help")
async def driver_help(day_token: str, request: Request):
    """A driver raising their hand. Lands as a support ticket AND a permanent
    event, so it can never be lost because a UI happened to be closed."""
    from .models import SupportTicket
    drv = await _driver_by_token(day_token)
    body = await request.json()
    kind = str(body.get("kind", "other"))[:20]
    if kind not in DRIVER_ISSUES:
        kind = "other"
    label, severity = DRIVER_ISSUES[kind]
    note = str(body.get("message", "")).strip()[:900]
    order_id = str(body.get("order_id", "")).strip()[:40]
    name = drv["fields"].get("display_name", "Driver")
    phone = drv["fields"].get("phone", "")
    message = f"[DRIVER · {severity.upper()}] {label}"
    if order_id:
        message += f" · order {order_id}"
    if note:
        message += f"\n{note}"
    db: Session = SessionLocal()
    try:
        db.add(SupportTicket(name=f"{name} (driver)", phone=phone,
                             order_id=order_id, message=message))
        db.add(Event(event_type="driver.help_requested",
                     entity_ref=order_id or drv["id"], tenant="gateway",
                     actor=f"driver:{name}",
                     payload=json.dumps({"kind": kind, "severity": severity,
                                         "note": note, "order_id": order_id})))
        db.commit()
    finally:
        db.close()
    return {"ok": True, "severity": severity, "label": label}


@router.post("/api/driver/{day_token}/orders/{record_id}/proof")
async def upload_proof(day_token: str, record_id: str, request: Request):
    drv = await _driver_by_token(day_token)
    owned = await at.list_records(at.ORDERS, formula=f"RECORD_ID()='{_fq(record_id)}'",
                                  max_records=1)
    if owned and drv["id"] not in (owned[0]["fields"].get("driver") or []):
        raise HTTPException(403, "This order is not on your sheet")
    body = await request.json()
    img = body.get("image_b64", "")
    if not img or len(img) > 6_000_000:
        raise HTTPException(400, "image_b64 required (max ~4MB)")
    import base64 as _b64
    try:
        _b64.b64decode(img, validate=True)
    except Exception:
        raise HTTPException(400, "image_b64 is not valid base64")
    ctype = str(body.get("content_type", "image/jpeg")).lower()
    if ctype not in ("image/jpeg", "image/png", "image/webp"):
        ctype = "image/jpeg"
    order_id = body.get("order_id", record_id)
    db: Session = SessionLocal()
    try:
        db.add(Proof(order_id=order_id, content_b64=img,
                     content_type=ctype,
                     lat=str(body.get("lat", ""))[:30], lng=str(body.get("lng", ""))[:30]))
        db.commit()
    finally:
        db.close()
    actor = f"driver:{drv['fields'].get('display_name','?')}"
    _log_event("order.proof_captured", order_id, actor,
               {"lat": str(body.get("lat", "")), "lng": str(body.get("lng", ""))})
    return {"ok": True, "order_id": order_id, "proof_url": f"/proof/{order_id}"}


@router.get("/proof/{order_id}")
def get_proof(order_id: str):
    import base64
    db: Session = SessionLocal()
    try:
        p = (db.query(Proof).filter(Proof.order_id == order_id)
             .order_by(Proof.created_at.desc()).first())
    finally:
        db.close()
    if not p:
        raise HTTPException(404, "No proof on file for this order")
    return Response(content=base64.b64decode(p.content_b64), media_type=p.content_type)



@router.post("/api/driver/{day_token}/orders/{record_id}/heads-up")
async def driver_heads_up(day_token: str, record_id: str, request: Request):
    """Driver's one-tap personal note to the customer (e.g. 'Running 5 late, sorry!').
    Recorded in the owned log; surfaced on the customer's tracking page while in transit."""
    drv = await _driver_by_token(day_token)
    owned = await at.list_records(at.ORDERS, formula=f"RECORD_ID()='{_fq(record_id)}'",
                                  max_records=1)
    if not owned:
        raise HTTPException(404, "No such order")
    if drv["id"] not in (owned[0]["fields"].get("driver") or []):
        raise HTTPException(403, "This order is not on your sheet")
    body = await request.json()
    note = str(body.get("note", "")).strip()[:160]
    order_id = owned[0]["fields"].get("order_id", record_id)
    _log_event("order.heads_up", order_id, f"driver:{drv['id']}", {"note": note})
    return {"ok": True}


@router.post("/api/driver/{day_token}/orders/{record_id}/{action}")
async def driver_action(day_token: str, record_id: str, action: str, request: Request,
                        background_tasks: BackgroundTasks):
    if action not in ACTION_MAP:
        raise HTTPException(400, "Action must be picked_up, delivered, or failed")
    drv = await _driver_by_token(day_token)
    owned = await at.list_records(at.ORDERS, formula=f"RECORD_ID()='{_fq(record_id)}'",
                                  max_records=1)
    if not owned:
        raise HTTPException(404, "No such order")
    if drv["id"] not in (owned[0]["fields"].get("driver") or []):
        raise HTTPException(403, "This order is not on your sheet")
    current = owned[0]["fields"].get("status", "")
    if _guard(action, current) == "idempotent":
        return {"ok": True, "idempotent": True,
                "order_id": owned[0]["fields"].get("order_id", record_id),
                "new_status": current}
    spec = ACTION_MAP[action]
    fields = {"status": spec["status"], spec["stamp"]: _now()}
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    if action == "failed" and body.get("reason"):
        fields["fail_reason"] = str(body["reason"])[:200]
    gps = {}
    if body.get("lat") and body.get("lng"):
        gps = {"lat": str(body["lat"])[:30], "lng": str(body["lng"])[:30]}
        ref = drv["fields"].get("driver_id", drv["id"])
        _dbl: Session = SessionLocal()
        try:
            _loc = _dbl.get(DriverLocation, ref)
            if _loc is None:
                _dbl.add(DriverLocation(driver_ref=ref, lat=gps["lat"], lng=gps["lng"]))
            else:
                _loc.lat, _loc.lng = gps["lat"], gps["lng"]
                _loc.updated_at = datetime.now(timezone.utc)
            _dbl.commit()
        finally:
            _dbl.close()
    updated = await at.patch_record(at.ORDERS, record_id, fields)
    order_id = updated.get("fields", {}).get("order_id", record_id)
    actor = f"driver:{drv['fields'].get('display_name','?')}"
    _log_event(spec["event"], order_id, actor, {"action": action, **fields, **gps})
    await _mirror_event_airtable(spec["event"], order_id, actor, json.dumps(fields))
    phone = updated.get("fields", {}).get("customer_phone_raw", "")
    if phone:
        if action == "picked_up":
            background_tasks.add_task(notify.send_sms, order_id, phone,
                                      notify.msg_on_the_way(order_id))
        elif action == "delivered":
            background_tasks.add_task(notify.send_sms, order_id, phone,
                                      notify.msg_delivered(order_id))
    return {"ok": True, "order_id": order_id, "new_status": spec["status"]}


# ---------- BOARD API (founder) ----------

def _check_key(key: str):
    admin = os.environ.get("ADMIN_KEY", "")
    if not admin or not secrets.compare_digest(str(key), admin):
        raise HTTPException(403, "Bad board key")


@router.get("/api/board/{key}/orders")
async def board_orders(key: str):
    _check_key(key)
    # These two Airtable reads are independent — firing them sequentially made
    # the board's poll wait one round-trip, then another (this is the
    # system.slow_request the founder saw on the log). Run them concurrently.
    import asyncio
    _drivers_cached = _cget("drivers:active")
    if _drivers_cached is not None:
        records = await at.list_records(
            at.ORDERS,
            formula="NOT(OR({status}='closed',{status}='cancelled'))",
            max_records=100,
        )
        drivers = _drivers_cached
    else:
        records, drivers = await asyncio.gather(
            at.list_records(
                at.ORDERS,
                formula="NOT(OR({status}='closed',{status}='cancelled'))",
                max_records=100,
            ),
            at.list_records(at.DRIVERS, formula="{status}!='inactive'"),
        )
        _cput("drivers:active", drivers, 45)
    # failed orders surface for recovery (reassign/cancel)
    all_ids = [r["fields"].get("order_id", "") for r in records]
    ready_ids: set = set()
    if all_ids:
        _dbb: Session = SessionLocal()
        try:
            _rws = (_dbb.query(Event)
                    .filter(Event.event_type == "order.kitchen_ready",
                            Event.entity_ref.in_(all_ids)).all())
            ready_ids = {e.entity_ref for e in _rws}
        finally:
            _dbb.close()
    return {
        "orders": [{
            "id": r["id"],
            "order_id": r["fields"].get("order_id", ""),
            "status": r["fields"].get("status", ""),
            "customer": r["fields"].get("customer_name_raw", ""),
            "pickup": r["fields"].get("pickup_address", ""),
            "dropoff": r["fields"].get("dropoff_address", ""),
            "items": r["fields"].get("items_description", ""),
            "requested_for": r["fields"].get("requested_for", ""),
            "kitchen_ready": r["fields"].get("order_id", "") in ready_ids,
            "driver": (r["fields"].get("driver") or [None])[0],
        } for r in records],
        "drivers": [{
            "id": d["id"],
            "name": d["fields"].get("display_name", ""),
            "active": sum(1 for r in records
                          if d["id"] in (r["fields"].get("driver") or [])
                          and r["fields"].get("status") in ("assigned", "in_transit")),
        } for d in drivers],
    }


@router.post("/api/board/{key}/orders/{record_id}/assign")
async def assign_order(key: str, record_id: str, request: Request):
    _check_key(key)
    body = await request.json()
    driver_rec = body.get("driver_id")
    if not driver_rec:
        raise HTTPException(400, "driver_id required")
    cur = await _order_state(record_id)
    _guard("assign", cur)
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
    cur = await _order_state(record_id)
    if _guard("confirm", cur) == "idempotent":
        return {"ok": True, "idempotent": True}
    updated = await at.patch_record(at.ORDERS, record_id, {
        "status": "confirmed", "confirmed_at": _now(),
    })
    order_id = updated.get("fields", {}).get("order_id", record_id)
    _log_event("order.confirmed", order_id, "founder", {})
    await _mirror_event_airtable("order.confirmed", order_id, "founder", "")
    return {"ok": True, "order_id": order_id}


def _cash_due(fields: dict, pay_by_order: dict) -> int:
    """Cash-on-delivery amount the driver collects at the door (0 if prepaid)."""
    if pay_by_order.get(fields.get("order_id", "")) == "card":
        return 0
    return int(fields.get("total_cents") or 0)


async def _order_state(record_id: str) -> str:
    recs = await at.list_records(at.ORDERS, formula=f"RECORD_ID()='{_fq(record_id)}'",
                                 max_records=1)
    if not recs:
        raise HTTPException(404, "No such order")
    return recs[0]["fields"].get("status", "")


# ---------- BOARD: LIFECYCLE COMPLETION ----------

@router.post("/api/board/{key}/orders/{record_id}/close")
async def close_order(key: str, record_id: str):
    _check_key(key)
    cur = await _order_state(record_id)
    if _guard("close", cur) == "idempotent":
        return {"ok": True, "idempotent": True}
    updated = await at.patch_record(at.ORDERS, record_id,
                                    {"status": "closed", "closed_at": _now()})
    order_id = updated.get("fields", {}).get("order_id", record_id)
    _log_event("order.closed", order_id, "founder", {})
    await _mirror_event_airtable("order.closed", order_id, "founder", "")
    return {"ok": True, "order_id": order_id}


@router.post("/api/board/{key}/orders/{record_id}/cancel")
async def cancel_order(key: str, record_id: str, request: Request):
    _check_key(key)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    reason = str(body.get("reason", ""))[:200]
    cur = await _order_state(record_id)
    if _guard("cancel", cur) == "idempotent":
        return {"ok": True, "idempotent": True}
    fields = {"status": "cancelled", "cancelled_at": _now()}
    if reason:
        fields["cancel_reason"] = reason
    updated = await at.patch_record(at.ORDERS, record_id, fields)
    order_id = updated.get("fields", {}).get("order_id", record_id)
    _log_event("order.cancelled", order_id, "founder", {"reason": reason})
    await _mirror_event_airtable("order.cancelled", order_id, "founder", reason)
    return {"ok": True, "order_id": order_id}


# ---------- BOARD: DRIVER MANAGEMENT (Access service owns this at M3) ----------

def _new_token() -> str:
    return "gw-" + secrets.token_hex(4)


@router.get("/api/board/{key}/drivers")
async def board_drivers(key: str):
    _check_key(key)
    drivers = await at.list_records(at.DRIVERS)
    # join the local profile (avatar/vehicle/bio) so the board shows the roster
    # as people, and flags who still needs to set their card up.
    from .models import DriverProfile
    profs: dict = {}
    _db: Session = SessionLocal()
    try:
        for p in _db.query(DriverProfile).all():
            profs[p.driver_id] = p
    finally:
        _db.close()
    out = []
    for d in drivers:
        did = d["fields"].get("driver_id", "")
        p = profs.get(did)
        card = {
            "id": d["id"],
            "driver_id": did,
            "name": d["fields"].get("display_name", ""),
            "status": d["fields"].get("status", ""),
            "day_token": d["fields"].get("day_token", ""),
            "avatar": p.avatar if p else "",
            "vehicle": " ".join(x for x in [(p.vehicle_color if p else ""),
                                            (p.vehicle if p else "")] if x),
            "bio": p.bio if p else "",
            "photo_url": p.photo_url if p else "",
            # a driver is "set up" once they've added a face and a car
            "profile_complete": bool(p and (p.avatar or p.photo_url) and p.vehicle),
        }
        out.append(card)
    return {"drivers": out}


@router.post("/api/board/{key}/drivers")
async def create_driver(key: str, request: Request):
    _check_key(key)
    body = await request.json()
    name = str(body.get("name", "")).strip()
    if not name:
        raise HTTPException(400, "name required")
    token = _new_token()
    created = await at.create_record(at.DRIVERS, {
        "driver_id": "DRV-" + secrets.token_hex(3).upper(),
        "display_name": name, "status": "active", "day_token": token,
    })
    _log_event("driver.created", created["fields"].get("driver_id", ""), "founder", {"name": name})
    _cbust()
    return {"ok": True, "id": created["id"], "day_token": token}


@router.post("/api/board/{key}/drivers/{record_id}/rotate")
async def rotate_driver_token(key: str, record_id: str):
    _check_key(key)
    token = _new_token()
    updated = await at.patch_record(at.DRIVERS, record_id, {"day_token": token})
    _log_event("driver.token_rotated",
               updated.get("fields", {}).get("driver_id", record_id), "founder", {})
    _cbust()
    return {"ok": True, "day_token": token}


# ---------- BOARD: STATS ----------

def _minutes_between(a: str, b: str):
    try:
        t1 = datetime.fromisoformat(a.replace("Z", "+00:00"))
        t2 = datetime.fromisoformat(b.replace("Z", "+00:00"))
        return max(0.0, (t2 - t1).total_seconds() / 60.0)
    except Exception:
        return None


@router.get("/api/board/{key}/stats")
async def board_stats(key: str):
    _check_key(key)
    today = business_day()
    records = await at.list_records(
        at.ORDERS, formula=f"DATETIME_FORMAT(SET_TIMEZONE({{received_at}},'America/New_York'),'YYYY-MM-DD')='{today}'",
        max_records=100)
    by_status: dict = {}
    partners: dict = {}
    times = []
    for r in records:
        f = r["fields"]
        st = f.get("status", "?")
        by_status[st] = by_status.get(st, 0) + 1
        p = f.get("partner_code", "")
        if p:
            partners[p] = partners.get(p, 0) + 1
        if f.get("received_at") and f.get("delivered_at"):
            m = _minutes_between(f["received_at"], f["delivered_at"])
            if m is not None:
                times.append(m)
    return {
        "date": today,
        "orders_today": len(records),
        "by_status": by_status,
        "by_partner": partners,
        "delivered_today": by_status.get("delivered", 0) + by_status.get("closed", 0),
        "avg_received_to_delivered_min": round(sum(times) / len(times), 1) if times else None,
    }


# ---------- BOARD: OWNED TRUTH LOG ----------

@router.get("/api/board/{key}/events")
def board_events(key: str, limit: int = 50):
    _check_key(key)
    db: Session = SessionLocal()
    try:
        rows = (db.query(Event).order_by(Event.occurred_at.desc())
                .limit(min(limit, 200)).all())
    finally:
        db.close()
    return {"events": [{
        "event_type": e.event_type, "entity_ref": e.entity_ref,
        "actor": e.actor, "occurred_at": e.occurred_at.isoformat(),
        "payload": e.payload,
    } for e in rows]}


@router.get("/api/board/{key}/notifications")
def board_notifications(key: str, limit: int = 50):
    _check_key(key)
    from .models import Notification
    db: Session = SessionLocal()
    try:
        rows = (db.query(Notification).order_by(Notification.created_at.desc())
                .limit(min(limit, 200)).all())
    finally:
        db.close()
    return {"notifications": [{
        "order_id": n.order_id, "to": n.to_phone, "status": n.status,
        "body": n.body, "detail": n.detail, "at": n.created_at.isoformat(),
    } for n in rows]}


@router.get("/api/board/{key}/order-detail/{order_id}")
async def order_detail(key: str, order_id: str):
    _check_key(key)
    oid = order_id.upper().strip()
    recs = await at.list_records(at.ORDERS, formula=f"{{order_id}}='{_fq(oid)}'", max_records=1)
    if not recs:
        raise HTTPException(404, "No order with that ID")
    f = recs[0]["fields"]
    db: Session = SessionLocal()
    try:
        evs = (db.query(Event).filter(Event.entity_ref == oid)
               .order_by(Event.occurred_at.asc()).all())
        from .models import Proof
        has_proof = db.query(Proof).filter(Proof.order_id == oid).count() > 0
    finally:
        db.close()
    keep = ["order_id", "status", "partner_code", "source_channel",
            "pickup_address", "dropoff_address", "dropoff_contact_name",
            "dropoff_contact_phone", "items_description", "special_instructions",
            "cancel_reason", "received_at", "confirmed_at", "assigned_at",
            "in_transit_at", "delivered_at", "closed_at", "cancelled_at", "failed_at",
            "customer_name_raw", "customer_phone_raw", "requested_for",
            "subtotal_cents", "fee_cents", "total_cents", "tip_cents",
            "discount_cents", "promo_code", "payment_method", "collect_cash_cents",
            "prep_estimate_minutes"]
    driver_name = ""
    driver_ids = f.get("driver") or []
    if driver_ids:
        drivers = _cget("drivers:list")
        if drivers is None:
            drivers = await at.list_records(at.DRIVERS)
            _cput("drivers:list", drivers, 45)
        match = next((d for d in drivers if d["id"] == driver_ids[0]), None)
        if match:
            driver_name = match["fields"].get("display_name", "")
    return {
        "record_id": recs[0]["id"],
        "fields": {k: f.get(k, "") for k in keep if f.get(k)},
        "driver_name": driver_name,
        "has_proof": has_proof,
        "events": [{"event_type": e.event_type, "actor": e.actor,
                    "occurred_at": e.occurred_at.isoformat(), "payload": e.payload}
                   for e in evs],
    }


@router.post("/api/board/{key}/orders/{record_id}/requeue")
async def requeue_order(key: str, record_id: str):
    """Recover a failed delivery: return it to 'confirmed' so it can be reassigned."""
    _check_key(key)
    cur = await _order_state(record_id)
    if _guard("requeue", cur) == "idempotent":
        return {"ok": True, "idempotent": True}
    updated = await at.patch_record(at.ORDERS, record_id,
                                    {"status": "confirmed", "failed_at": ""})
    order_id = updated.get("fields", {}).get("order_id", record_id)
    _log_event("order.requeued", order_id, "founder", {})
    await _mirror_event_airtable("order.requeued", order_id, "founder", "")
    return {"ok": True, "order_id": order_id}


@router.post("/api/board/{key}/orders/{record_id}/notify")
async def manual_notify(key: str, record_id: str, request: Request):
    """Founder-triggered SMS to the customer (e.g. a delay note)."""
    _check_key(key)
    body = await request.json()
    text = str(body.get("message", "")).strip()[:320]
    if not text:
        raise HTTPException(400, "message required")
    recs = await at.list_records(at.ORDERS, formula=f"RECORD_ID()='{_fq(record_id)}'", max_records=1)
    phone = ""
    order_id = record_id
    if recs:
        phone = recs[0]["fields"].get("customer_phone_raw", "")
        order_id = recs[0]["fields"].get("order_id", record_id)
    status = await notify.send_sms(order_id, phone, text)
    return {"ok": True, "sms_status": status}


@router.post("/api/driver/{day_token}/ping")
async def driver_ping(day_token: str, request: Request):
    """Continuous location ping while a driver is running deliveries. Upsert."""
    drv = await _driver_by_token(day_token)
    body = await request.json()
    lat, lng = str(body.get("lat", ""))[:30], str(body.get("lng", ""))[:30]
    if not lat or not lng:
        return {"ok": False, "reason": "no coords"}
    retention_sweep()
    ref = drv["fields"].get("driver_id", drv["id"])
    db: Session = SessionLocal()
    try:
        loc = db.get(DriverLocation, ref)
        if loc is None:
            db.add(DriverLocation(driver_ref=ref, lat=lat, lng=lng))
        else:
            loc.lat, loc.lng = lat, lng
            loc.updated_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()
    return {"ok": True}


@router.get("/v0/track/{order_id}/location")
async def track_location(order_id: str):
    """Public: last-known driver location for an in-transit order. Coarse, time-boxed.
    Returns nothing unless the order is actively in transit (privacy)."""
    oid = order_id.upper().strip()
    recs = await at.list_records(at.ORDERS, formula=f"{{order_id}}='{_fq(oid)}'", max_records=1)
    if not recs:
        return {"live": False}
    f = recs[0]["fields"]
    if f.get("status") != "in_transit":
        return {"live": False}
    driver_refs = f.get("driver") or []
    # resolve driver record -> driver_id
    ref = None
    if driver_refs:
        ref = _cget(f"dref:{driver_refs[0]}")
        if ref is None:
            drecs = await at.list_records(at.DRIVERS,
                                          formula=f"RECORD_ID()='{_fq(driver_refs[0])}'", max_records=1)
            if drecs:
                ref = drecs[0]["fields"].get("driver_id", drecs[0]["id"])
                _cput(f"dref:{driver_refs[0]}", ref, 600)
    if not ref:
        return {"live": False}
    db: Session = SessionLocal()
    try:
        loc = db.get(DriverLocation, ref)
    finally:
        db.close()
    if not loc or not loc.lat:
        return {"live": False}
    # staleness guard: only surface pings from the last 10 minutes.
    # SQLite returns naive datetimes; normalize to UTC-aware before diffing.
    updated = loc.updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - updated).total_seconds()
    if age > 600:
        return {"live": False}
    return {"live": True, "lat": loc.lat, "lng": loc.lng,
            "dropoff": f.get("dropoff_address", "")}


@router.get("/api/board/{key}/summary")
async def day_summary(key: str, date: str = "", partner: str = ""):
    _check_key(key)
    day = date or business_day()
    formula = f"DATETIME_FORMAT(SET_TIMEZONE({{received_at}},'America/New_York'),'YYYY-MM-DD')='{day}'"
    if partner:
        formula = f"AND({formula},{{partner_code}}='{_fq(partner)}')"
    records = await at.list_records(at.ORDERS, formula=formula, max_records=100)
    delivered = [r for r in records if r["fields"].get("status") in ("delivered", "closed")]
    revenue = sum(int(r["fields"].get("total_cents") or 0) for r in delivered)
    times = []
    for r in delivered:
        f = r["fields"]
        m = _minutes_between(f.get("received_at", ""), f.get("delivered_at", ""))
        if m is not None:
            times.append(m)
    return {"date": day, "partner": partner or "all",
            "orders": len(records), "delivered": len(delivered),
            "cancelled": sum(1 for r in records if r["fields"].get("status") == "cancelled"),
            "failed_open": sum(1 for r in records if r["fields"].get("status") == "failed"),
            "revenue_cents": revenue,
            "avg_minutes": round(sum(times) / len(times), 1) if times else None}


def _dollars(cents) -> str:
    try:
        return f"{int(cents) / 100:.2f}"
    except (TypeError, ValueError):
        return ""


@router.get("/api/board/{key}/export.csv")
async def export_day_csv(key: str, date: str = "", partner: str = "", days: int = 1):
    """Ledger export. ?date= single day (default today), ?days=N back from date,
    ?partner= isolates one restaurant (never hand one partner another's ledger)."""
    _check_key(key)
    import csv
    import io
    from datetime import timedelta
    day = date or business_day()
    days = max(1, min(days, 31))
    start = (datetime.fromisoformat(day) - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    formula = (f"AND(DATETIME_FORMAT(SET_TIMEZONE({{received_at}},'America/New_York'),'YYYY-MM-DD')>='{start}',"
               f"DATETIME_FORMAT(SET_TIMEZONE({{received_at}},'America/New_York'),'YYYY-MM-DD')<='{day}')")
    if partner:
        formula = f"AND({formula},{{partner_code}}='{_fq(partner)}')"
    records = await at.list_records(at.ORDERS, formula=formula, max_records=100)
    records.sort(key=lambda r: r["fields"].get("received_at", ""))
    cols = ["order_id", "status", "partner_code", "customer_name_raw",
            "pickup_address", "dropoff_address", "items_description",
            "received_at", "delivered_at", "cancel_reason"]
    money = ["subtotal_cents", "fee_cents", "tip_cents", "total_cents"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols + ["subtotal_usd", "delivery_fee_usd", "tip_usd", "total_usd"])
    for r in records:
        f = r["fields"]
        w.writerow([f.get(c, "") for c in cols] + [_dollars(f.get(m)) for m in money])
    tag = f"-{partner}" if partner else ""
    name = f"gateway{tag}-{start}_to_{day}.csv" if days > 1 else f"gateway{tag}-{day}.csv"
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/api/board/{key}/digest")
async def weekly_digest(key: str, partner: str = "", days: int = 7):
    _check_key(key)
    from datetime import timedelta
    days = max(1, min(days, 31))
    start = (datetime.now(timezone.utc) - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    formula = f"DATETIME_FORMAT(SET_TIMEZONE({{received_at}},'America/New_York'),'YYYY-MM-DD')>='{start}'"
    if partner:
        formula = f"AND({formula},{{partner_code}}='{_fq(partner)}')"
    records = await at.list_records(at.ORDERS, formula=formula, max_records=100)
    by_day: dict = {}
    for r in records:
        f = r["fields"]
        day = (f.get("received_at") or "")[:10]
        d = by_day.setdefault(day, {"date": day, "orders": 0, "delivered": 0, "revenue_cents": 0})
        d["orders"] += 1
        if f.get("status") in ("delivered", "closed"):
            d["delivered"] += 1
            d["revenue_cents"] += int(f.get("total_cents") or 0)
    days_list = sorted(by_day.values(), key=lambda x: x["date"])
    return {"partner": partner or "all", "since": start, "days": days_list,
            "totals": {"orders": sum(d["orders"] for d in days_list),
                       "delivered": sum(d["delivered"] for d in days_list),
                       "revenue_cents": sum(d["revenue_cents"] for d in days_list)}}


EDITABLE_FIELDS = {"pickup_address", "dropoff_address", "dropoff_contact_name",
                   "dropoff_contact_phone", "items_description",
                   "special_instructions", "requested_for", "customer_phone_raw"}


@router.post("/api/board/{key}/orders/{record_id}/edit")
async def edit_order(key: str, record_id: str, request: Request):
    _check_key(key)
    body = await request.json()
    changes = {k: str(v)[:600] for k, v in body.items() if k in EDITABLE_FIELDS}
    if not changes:
        raise HTTPException(400, "No editable fields provided")
    before = await at.list_records(at.ORDERS, formula=f"RECORD_ID()='{_fq(record_id)}'", max_records=1)
    old = {k: before[0]["fields"].get(k, "") for k in changes} if before else {}
    updated = await at.patch_record(at.ORDERS, record_id, changes)
    order_id = updated.get("fields", {}).get("order_id", record_id)
    _log_event("order.edited", order_id, "founder",
               {"changed": {k: {"from": old.get(k, ""), "to": v} for k, v in changes.items()}})
    return {"ok": True, "order_id": order_id}


def _stats_from(records: list) -> dict:
    by_status: dict = {}
    partners: dict = {}
    times = []
    for r in records:
        f = r["fields"]
        st = f.get("status", "?")
        by_status[st] = by_status.get(st, 0) + 1
        p = f.get("partner_code", "")
        if p:
            partners[p] = partners.get(p, 0) + 1
        if f.get("received_at") and f.get("delivered_at"):
            m = _minutes_between(f["received_at"], f["delivered_at"])
            if m is not None:
                times.append(m)
    return {
        "orders_today": len(records),
        "by_status": by_status,
        "by_partner": partners,
        "delivered_today": by_status.get("delivered", 0) + by_status.get("closed", 0),
        "avg_received_to_delivered_min": round(sum(times) / len(times), 1) if times else None,
    }


STATUS_PRIORITY = {"failed": 0, "received": 1, "confirmed": 2,
                   "assigned": 3, "in_transit": 4, "delivered": 5}


@router.get("/api/board/{key}/snapshot")
async def board_snapshot(key: str):
    """One round-trip board load: open orders + drivers + today's stats.
    Orders arrive urgency-sorted: needs-attention first, oldest first within a group."""
    _check_key(key)
    import asyncio
    today = business_day()
    # open orders and today's orders are two independent reads — fetch together.
    records, today_records = await asyncio.gather(
        at.list_records(
            at.ORDERS, formula="NOT(OR({status}='closed',{status}='cancelled'))",
            max_records=100),
        at.list_records(
            at.ORDERS,
            formula=f"DATETIME_FORMAT(SET_TIMEZONE({{received_at}},'America/New_York'),'YYYY-MM-DD')='{today}'",
            max_records=100),
    )
    drivers = _cget("drivers:list")
    if drivers is None:
        drivers = await at.list_records(at.DRIVERS)
        _cput("drivers:list", drivers, 45)
    records.sort(key=lambda r: (STATUS_PRIORITY.get(r["fields"].get("status", ""), 9),
                                r["fields"].get("received_at", "9999")))
    all_ids = [r["fields"].get("order_id", "") for r in records]
    ready_ids: set = set()
    if all_ids:
        db: Session = SessionLocal()
        try:
            rows = (db.query(Event)
                    .filter(Event.event_type == "order.kitchen_ready",
                            Event.entity_ref.in_(all_ids)).all())
            ready_ids = {e.entity_ref for e in rows}
        finally:
            db.close()
    return {
        "orders": [{
            "id": r["id"],
            "order_id": r["fields"].get("order_id", ""),
            "status": r["fields"].get("status", ""),
            "customer": r["fields"].get("customer_name_raw", ""),
            "pickup": r["fields"].get("pickup_address", ""),
            "dropoff": r["fields"].get("dropoff_address", ""),
            "items": r["fields"].get("items_description", ""),
            "requested_for": r["fields"].get("requested_for", ""),
            "partner": r["fields"].get("partner_code", ""),
            "received_at": r["fields"].get("received_at", ""),
            "kitchen_ready": r["fields"].get("order_id", "") in ready_ids,
            "driver": (r["fields"].get("driver") or [None])[0],
        } for r in records],
        "drivers": [{
            "id": d["id"],
            "name": d["fields"].get("display_name", ""),
            "active": sum(1 for r in records
                          if d["id"] in (r["fields"].get("driver") or [])
                          and r["fields"].get("status") in ("assigned", "in_transit")),
        } for d in drivers],
        "stats": _stats_from(today_records),
    }


@router.get("/v0/track/{order_id}/status")
async def track_status(order_id: str):
    """Public, minimal: current status string only. Powers live page updates."""
    oid = _fq(order_id.upper().strip())
    recs = await at.list_records(at.ORDERS, formula=f"{{order_id}}='{oid}'", max_records=1)
    return {"status": recs[0]["fields"].get("status", "unknown") if recs else "unknown"}


@router.get("/api/board/{key}/statement/{partner}")
async def partner_statement(key: str, partner: str, days: int = 7):
    """The settle-up artifact: branded printable statement for one partner.
    Factual money columns only — settlement terms are the founder's domain."""
    _check_key(key)
    from datetime import timedelta
    from fastapi.responses import HTMLResponse
    days = max(1, min(days, 31))
    end = datetime.now(timezone.utc)
    start = (end - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    end_s = end.strftime("%Y-%m-%d")
    p = _fq(partner.lower())
    formula = (f"AND(DATETIME_FORMAT(SET_TIMEZONE({{received_at}},'America/New_York'),'YYYY-MM-DD')>='{start}',"
               f"{{partner_code}}='{p}')")
    records = await at.list_records(at.ORDERS, formula=formula, max_records=100)
    records.sort(key=lambda r: r["fields"].get("received_at", ""))
    def esc(x):
        return (str(x or "").replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))
    rows = ""
    tot = {"sub": 0, "fee": 0, "tip": 0, "all": 0, "n": 0, "delivered": 0}
    for r in records:
        f = r["fields"]
        st = f.get("status", "")
        counted = st in ("delivered", "closed")
        tot["n"] += 1
        if counted:
            tot["delivered"] += 1
            for k, fld in (("sub", "subtotal_cents"), ("fee", "fee_cents"),
                           ("tip", "tip_cents"), ("all", "total_cents")):
                tot[k] += int(f.get(fld) or 0)
        mark = "" if counted else ' class="void"'
        rows += (f"<tr{mark}><td>{esc(f.get('received_at',''))[:10]}</td>"
                 f"<td class=mono>{esc(f.get('order_id',''))}</td>"
                 f"<td>{esc(f.get('items_description',''))[:80]}</td>"
                 f"<td>{esc(st)}</td>"
                 f"<td class=r>{_dollars(f.get('subtotal_cents'))}</td>"
                 f"<td class=r>{_dollars(f.get('fee_cents'))}</td>"
                 f"<td class=r>{_dollars(f.get('tip_cents'))}</td>"
                 f"<td class=r><b>{_dollars(f.get('total_cents'))}</b></td></tr>")
    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Statement — {esc(p)} — GateWay</title>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;700;900&family=IBM+Plex+Mono&display=swap" rel="stylesheet">
<style>body{{font-family:'Archivo',sans-serif;color:#14181f;max-width:760px;margin:0 auto;padding:26px 20px 60px;background:#fff}}
.head{{background:#0e1526;margin:-26px -20px 24px;padding:22px 24px;display:flex;align-items:center;justify-content:space-between}}
.head img{{height:44px}}
.head .t{{color:#e8eaf0;text-align:right}}.head .t b{{font-size:1.05rem}}
.head .t div{{font-family:'IBM Plex Mono',monospace;font-size:.66rem;color:#8b93a7;letter-spacing:.1em;text-transform:uppercase}}
h1{{font-size:1.2rem;margin:0 0 2px}}.per{{font-family:'IBM Plex Mono',monospace;font-size:.72rem;color:#5a5e64;margin-bottom:20px}}
table{{width:100%;border-collapse:collapse;font-size:.78rem}}
th{{font-family:'IBM Plex Mono',monospace;font-size:.6rem;text-transform:uppercase;letter-spacing:.08em;color:#5a5e64;text-align:left;border-bottom:2px solid #16337a;padding:7px 6px}}
td{{padding:8px 6px;border-bottom:1px solid #e8ecf4;vertical-align:top}}
.mono{{font-family:'IBM Plex Mono',monospace;font-size:.68rem}}.r{{text-align:right}}
th.r{{text-align:right}}
tr.void td{{color:#b6bac2;text-decoration:line-through}}
.tots{{margin-top:18px;border-top:3px solid #0e1526;padding-top:12px;display:flex;gap:26px;flex-wrap:wrap}}
.tots div b{{display:block;font-size:1.15rem}}
.tots div span{{font-family:'IBM Plex Mono',monospace;font-size:.6rem;color:#5a5e64;text-transform:uppercase;letter-spacing:.08em}}
.note{{margin-top:20px;font-size:.74rem;color:#5a5e64;line-height:1.6}}
.foot{{margin-top:28px;font-family:'IBM Plex Mono',monospace;font-size:.6rem;color:#9a9ea5;text-transform:uppercase;letter-spacing:.1em;text-align:center}}
.printbtn{{position:fixed;bottom:20px;right:20px;background:#16337a;color:#fff;border:none;border-radius:12px;padding:14px 22px;font-weight:800;font-family:'Archivo';box-shadow:0 8px 22px rgba(22,51,122,.35)}}
@media print{{.printbtn{{display:none}}body{{padding:0}}}}
</style></head><body>
<div class="head"><img src="/static/logo-bar.png" alt="GateWay Dispatch">
<div class="t"><b>PARTNER STATEMENT</b><div>GateWay Delivery · Fivestone Holdings</div></div></div>
<h1>{esc(p)}</h1>
<div class="per">PERIOD {start} — {end_s} · GENERATED {end.strftime('%Y-%m-%d %H:%M')} UTC</div>
<table><tr><th>Date</th><th>Order</th><th>Items</th><th>Status</th>
<th class=r>Subtotal $</th><th class=r>Fee $</th><th class=r>Tip $</th><th class=r>Total $</th></tr>
{rows if rows else '<tr><td colspan=8 style="text-align:center;color:#9a9ea5;padding:24px">No orders in this period.</td></tr>'}</table>
<div class="tots">
<div><b>{tot['delivered']}</b><span>Delivered</span></div>
<div><b>${tot['sub']/100:.2f}</b><span>Food subtotal</span></div>
<div><b>${tot['fee']/100:.2f}</b><span>Delivery fees</span></div>
<div><b>${tot['tip']/100:.2f}</b><span>Tips (to drivers)</span></div>
<div><b>${tot['all']/100:.2f}</b><span>Total collected</span></div>
</div>
<div class="note">Struck-through rows were cancelled or failed and are excluded from totals.
Tips pass through 100% to drivers. Settlement of food subtotal and delivery fees per your GateWay partner agreement.</div>
<div class="foot">GateWay Dispatch · The record never pretends</div>
<button class="printbtn" onclick="window.print()">Print / Save PDF</button>
</body></html>"""
    return HTMLResponse(html)


@router.post("/api/board/{key}/partners/{code}/demo-order")
async def create_demo_order(key: str, code: str):
    """Founder demo tool: seeds one realistic order for this kitchen, priced from
    its live menu, flowing the normal record path. Marked as demo in the owned log."""
    _check_key(key)
    import hashlib
    from .models import MenuItem, Partner as P
    db: Session = SessionLocal()
    try:
        p = db.get(P, _fq(code.lower()))
        items = (db.query(MenuItem).filter(MenuItem.partner_code == p.code,
                                           MenuItem.available == True)  # noqa: E712
                 .limit(2).all()) if p else []
    finally:
        db.close()
    if not p:
        raise HTTPException(404, "Unknown partner")
    if items:
        lines = ", ".join(f"1× {i.name} (${i.price_cents/100:.2f})" for i in items)
        subtotal = sum(i.price_cents for i in items)
    else:
        lines, subtotal = "1× Demo plate ($12.00)", 1200
    fee = p.delivery_fee_cents or 599
    tip = 300
    total = subtotal + fee + tip
    now = _now()
    oid = "ORD-" + hashlib.md5(f"demo{p.code}{now}".encode()).hexdigest()[:8].upper()
    fields = {
        "order_id": oid, "status": "received", "source_channel": "demo",
        "partner_code": p.code, "pickup_address": p.address or "",
        "dropoff_address": "123 Demo Lane, Knoxville TN",
        "items_description": f"{lines} — subtotal ${subtotal/100:.2f}",
        "customer_name_raw": "Demo Customer", "customer_phone_raw": "",
        "fingerprint": hashlib.md5(f"demo{now}".encode()).hexdigest(),
        "received_at": now, "subtotal_cents": subtotal, "fee_cents": fee,
        "tip_cents": tip, "total_cents": total,
    }
    created = await at.create_record(at.ORDERS, fields)
    _log_event("order.received", oid, "founder:demo", {"demo": True, "partner": p.code})
    return {"ok": True, "order_id": oid, "record_id": created["id"],
            "total_cents": total, "partner": p.code}


@router.get("/v0/local-impact")
async def local_impact():
    """Public, no-PII community stat: this week's delivered orders + food dollars
    kept in local kitchens. Cached 10 min — it powers a home-screen banner."""
    cached = _cget("local_impact")
    if cached is not None:
        return cached
    from datetime import timedelta
    start = (datetime.now(timezone.utc) - timedelta(days=6)).strftime("%Y-%m-%d")
    try:
        records = await at.list_records(
            at.ORDERS,
            formula=(f"AND(DATETIME_FORMAT(SET_TIMEZONE({{received_at}},'America/New_York'),'YYYY-MM-DD')>='{start}',"
                     f"OR({{status}}='delivered',{{status}}='closed'))"),
            max_records=100)
    except Exception:
        records = []
    delivered = len(records)
    food_cents = sum(int(r["fields"].get("subtotal_cents") or 0) for r in records)
    kitchens = len({r["fields"].get("partner_code", "") for r in records
                    if r["fields"].get("partner_code")})
    out = {"days": 7, "delivered": delivered, "food_cents": food_cents,
           "kitchens": kitchens}
    _cput("local_impact", out, 600)
    return out


@router.get("/v0/track/{order_id}/heads-up")
async def track_heads_up(order_id: str):
    """Public: the latest driver heads-up note for an order that is still in transit."""
    oid = _fq(order_id.upper().strip())
    recs = await at.list_records(at.ORDERS, formula=f"{{order_id}}='{oid}'", max_records=1)
    if not recs or recs[0]["fields"].get("status") != "in_transit":
        return {"note": ""}
    db: Session = SessionLocal()
    try:
        row = (db.query(Event)
               .filter(Event.event_type == "order.heads_up", Event.entity_ref == oid)
               .order_by(Event.occurred_at.desc()).first())
        note = ""
        if row:
            import json as _j
            try:
                note = _j.loads(row.payload).get("note", "")
            except Exception:
                note = ""
    finally:
        db.close()
    return {"note": note[:160]}


@router.post("/v0/track/{order_id}/tip")
async def add_tip(order_id: str, request: Request):
    """Public: add (or increase) a tip after delivery. 100% to the driver.
    The big apps hide this behind an account; a neighbor should just be able to say thanks."""
    oid = _fq(order_id.upper().strip())
    body = await request.json()
    try:
        add_cents = int(body.get("cents", 0))
    except (TypeError, ValueError):
        raise HTTPException(400, "cents must be a number")
    if add_cents <= 0 or add_cents > 20000:
        raise HTTPException(400, "Tip must be between $0.01 and $200")
    recs = await at.list_records(at.ORDERS, formula=f"{{order_id}}='{oid}'", max_records=1)
    if not recs:
        raise HTTPException(404, "No such order")
    f = recs[0]["fields"]
    if f.get("status") not in ("delivered", "closed"):
        raise HTTPException(409, "You can add a tip once your order is delivered.")
    old_tip = int(f.get("tip_cents") or 0)
    new_tip = old_tip + add_cents
    new_total = int(f.get("total_cents") or 0) + add_cents
    await at.patch_record(at.ORDERS, recs[0]["id"],
                          {"tip_cents": new_tip, "total_cents": new_total})
    _log_event("order.tip_added", oid, "customer",
               {"added_cents": add_cents, "tip_cents": new_tip})
    return {"ok": True, "tip_cents": new_tip}


@router.post("/api/board/{key}/phone-order")
async def phone_order(key: str, request: Request):
    """The chains have no phone number. GateWay does: a neighbor calls, dispatch types it in.
    Same record path, same tracking, same texts — just entered by a human who answered."""
    _check_key(key)
    import hashlib
    from .models import Partner as P
    body = await request.json()
    code = _fq(str(body.get("partner", "")).lower())
    items = str(body.get("items", "")).strip()[:600]
    addr = str(body.get("address", "")).strip()[:300]
    name = str(body.get("name", "")).strip()[:120]
    phone = str(body.get("phone", "")).strip()[:40]
    notes = str(body.get("notes", "")).strip()[:300]
    try:
        subtotal = int(body.get("subtotal_cents") or 0)
        tip = int(body.get("tip_cents") or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "Amounts must be numbers")
    if not items or not addr:
        raise HTTPException(400, "Items and address are required")
    pay = str(body.get("payment_method", "cod")).lower()
    pay = pay if pay in ("cod", "card") else "cod"

    db: Session = SessionLocal()
    try:
        p = db.get(P, code) if code else None
        pickup = p.address if p else ""
        fee = p.delivery_fee_cents if p else 599
    finally:
        db.close()
    total = subtotal + fee + tip
    now = _now()
    oid = "ORD-" + hashlib.md5(f"phone{addr}{items}{now}".encode()).hexdigest()[:8].upper()
    fields = {
        "order_id": oid, "status": "received", "source_channel": "phone",
        "partner_code": code, "pickup_address": pickup, "dropoff_address": addr,
        "items_description": items, "special_instructions": notes,
        "customer_name_raw": name, "customer_phone_raw": phone,
        "fingerprint": hashlib.md5(f"phone{now}{addr}".encode()).hexdigest(),
        "received_at": now, "subtotal_cents": subtotal, "fee_cents": fee,
        "tip_cents": tip, "total_cents": total,
    }
    created = await at.create_record(at.ORDERS, fields)
    _log_event("order.received", oid, "founder:phone",
               {"channel": "phone", "partner": code, "payment_method": pay})
    _log_event("order.payment_method", oid, "founder:phone", {"method": pay})
    return {"ok": True, "order_id": oid, "record_id": created["id"],
            "total_cents": total, "fee_cents": fee}


@router.get("/v0/community-fund")
async def community_fund():
    """The Neighbor Fund: neighbors round up a little so someone who's having a
    hard week still gets a hot meal brought to their door. No account, no fee,
    no cut — a platform built on extraction would never ship this.

    'Deliveries covered' is measured against the real $5.99 network delivery
    fee, so the number means exactly what it says."""
    from .models import Partner as _P
    FEE = 599  # one covered delivery = one standard delivery fee
    db: Session = SessionLocal()
    try:
        rows = (db.query(Event)
                .filter(Event.event_type == "order.rounded_up")
                .order_by(Event.occurred_at.desc()).all())
        import json as _j
        total = 0
        recent = []
        for e in rows:
            try:
                c = int(_j.loads(e.payload).get("cents", 0))
            except Exception:
                c = 0
            total += c
            if c > 0 and len(recent) < 8:
                recent.append({"cents": c, "at": e.occurred_at.isoformat()
                               if e.occurred_at else None})
        covered = total // FEE
        # how much more is needed to cover the next full delivery
        toward_next = total % FEE
        return {"cents": total, "gifts": len([r for r in rows]),
                "deliveries_covered": covered,
                "meals_covered": covered,  # back-compat for existing home widget
                "fee_cents": FEE,
                "toward_next_cents": toward_next,
                "recent": recent}
    finally:
        db.close()


@router.post("/v0/track/{order_id}/round-up")
async def round_up(order_id: str, request: Request):
    """Add a round-up gift to the community fund. No account, no fee, no cut."""
    oid = _fq(order_id.upper().strip())
    body = await request.json()
    try:
        cents = int(body.get("cents", 0))
    except (TypeError, ValueError):
        raise HTTPException(400, "cents must be a number")
    if cents <= 0 or cents > 10000:
        raise HTTPException(400, "Round-up must be between $0.01 and $100")
    recs = await at.list_records(at.ORDERS, formula=f"{{order_id}}='{oid}'", max_records=1)
    if not recs:
        raise HTTPException(404, "No such order")
    _log_event("order.rounded_up", oid, "customer", {"cents": cents})
    return {"ok": True, "cents": cents}


@router.post("/v0/track/{order_id}/feedback")
async def order_feedback(order_id: str, request: Request):
    """Private feedback, straight to the people who made and carried the food.
    NO public star rating: a single bad night shouldn't be able to sink a family kitchen
    the way a public 1-star average does on the big platforms."""
    oid = _fq(order_id.upper().strip())
    body = await request.json()
    good = bool(body.get("good", True))
    note = str(body.get("note", "")).strip()[:400]
    recs = await at.list_records(at.ORDERS, formula=f"{{order_id}}='{oid}'", max_records=1)
    if not recs:
        raise HTTPException(404, "No such order")
    if recs[0]["fields"].get("status") not in ("delivered", "closed"):
        raise HTTPException(409, "Feedback opens once your order is delivered.")
    partner = recs[0]["fields"].get("partner_code", "")
    _log_event("order.feedback", oid, "customer",
               {"good": good, "note": note, "partner": partner})
    return {"ok": True}


@router.get("/api/kitchen-feedback/{token}")
async def kitchen_feedback(token: str):
    """The kitchen reads what neighbors actually said — praise and problems both,
    unfiltered, private, and theirs. Not a public score they can never repair."""
    from .kitchen import _partner_by_token
    p = _partner_by_token(token)
    import json as _j
    db: Session = SessionLocal()
    try:
        rows = (db.query(Event).filter(Event.event_type == "order.feedback")
                .order_by(Event.occurred_at.desc()).limit(200).all())
        out, good, bad = [], 0, 0
        for e in rows:
            try:
                d = _j.loads(e.payload)
            except Exception:
                continue
            if d.get("partner") != p.code:
                continue
            if d.get("good"):
                good += 1
            else:
                bad += 1
            if d.get("note"):
                out.append({"good": bool(d.get("good")), "note": d["note"][:400],
                            "order_id": e.entity_ref,
                            "at": e.occurred_at.isoformat()})
        return {"kitchen": p.display_name, "loved": good, "issues": bad,
                "notes": out[:30]}
    finally:
        db.close()


@router.get("/api/driver/{day_token}/earnings")
async def driver_earnings(day_token: str, days: int = 7):
    """The driver's own ledger: deliveries and tips, day by day. Their work, their numbers,
    visible without asking anyone."""
    drv = await _driver_by_token(day_token)
    from datetime import timedelta
    days = max(1, min(days, 31))
    start = (datetime.now(timezone.utc) - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    records = await at.list_records(
        at.ORDERS,
        formula=(f"AND(OR({{status}}='delivered',{{status}}='closed'),"
                 f"DATETIME_FORMAT(SET_TIMEZONE({{delivered_at}},'America/New_York'),'YYYY-MM-DD')>='{start}')"),
        max_records=100)
    mine = [r for r in records if drv["id"] in (r["fields"].get("driver") or [])]
    by_day: dict = {}
    for r in mine:
        d = (r["fields"].get("delivered_at") or "")[:10]
        row = by_day.setdefault(d, {"date": d, "deliveries": 0, "tips_cents": 0})
        row["deliveries"] += 1
        row["tips_cents"] += int(r["fields"].get("tip_cents") or 0)
    days_list = sorted(by_day.values(), key=lambda x: x["date"], reverse=True)
    return {
        "driver": drv["fields"].get("display_name", ""),
        "since": start,
        "days": days_list,
        "totals": {"deliveries": sum(d["deliveries"] for d in days_list),
                   "tips_cents": sum(d["tips_cents"] for d in days_list)},
    }


@router.get("/api/board/{key}/readiness")
async def launch_readiness(key: str):
    """Everything standing between here and taking real money, in one honest list."""
    _check_key(key)
    from .models import MenuItem, Partner as P
    from . import payments
    checks = []
    db: Session = SessionLocal()
    try:
        partners = db.query(P).all()
        drivers_ok = True
        for p in partners:
            items = db.query(MenuItem).filter(MenuItem.partner_code == p.code).count()
            photos = db.query(MenuItem).filter(MenuItem.partner_code == p.code,
                                               MenuItem.image_url != "").count()
            checks.append({
                "area": f"{p.display_name}",
                "ok": bool(items and p.address and p.about_blurb),
                "detail": (f"{items} menu items · "
                           f"{photos} with photos · "
                           f"{'hero ✓' if p.hero_url else 'no hero photo'} · "
                           f"{'address ✓' if p.address else 'NO ADDRESS'}"),
            })
    finally:
        db.close()
    try:
        drivers = await at.list_records(at.DRIVERS)
    except Exception:
        drivers = []
    checks.append({"area": "Drivers", "ok": len(drivers) > 0,
                   "detail": f"{len(drivers)} driver(s) with day links"})
    checks.append({"area": "SMS (Twilio)", "ok": bool(os.environ.get("TWILIO_SID")),
                   "detail": "Live texts to customers" if os.environ.get("TWILIO_SID")
                             else "NOT SET — texts queue but never send. Add TWILIO_SID/TOKEN/FROM in Railway."})
    checks.append({"area": "Card payments (Stripe)", "ok": payments.configured(),
                   "detail": "Online payment live" if payments.configured()
                             else "Not set — orders default to CASH at the door (works today)."})
    checks.append({"area": "Database", "ok": True, "detail": "PostgreSQL on Railway · owned event log"})
    ready = all(c["ok"] for c in checks if c["area"] != "Card payments (Stripe)")
    blocking = [c["area"] for c in checks if not c["ok"]]
    return {"ready_to_take_orders": ready, "checks": checks, "blocking": blocking}
