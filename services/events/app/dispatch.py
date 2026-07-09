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
from .db import SessionLocal
from .models import Event, Proof, DriverLocation

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


# ---------- DIAGNOSTICS (no secrets returned; booleans only) ----------

@router.get("/api/diag")
async def diag():
    return {
        "airtable_pat_set": at.configured(),
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
    records = await at.list_records(
        at.ORDERS,
        formula="OR({status}='assigned',{status}='in_transit')",
        max_records=100,
    )
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
        finally:
            _dbr.close()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    done_recs = await at.list_records(
        at.ORDERS,
        formula=f"AND(OR({{status}}='delivered',{{status}}='closed'),"
                f"DATETIME_FORMAT({{delivered_at}},'YYYY-MM-DD')='{today}')",
        max_records=100)
    done_today = sum(1 for r in done_recs if drv["id"] in (r["fields"].get("driver") or []))
    return {
        "driver": drv["fields"].get("display_name", "Driver"),
        "shift": drv["fields"].get("status", "") == "on_shift",
        "done_today": done_today,
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
    recs = await at.list_records(at.ORDERS, formula=f"RECORD_ID()='{record_id}'", max_records=1)
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
    return {"ok": True, "shift": on}


# ---------- PROOF OF DELIVERY ----------

@router.post("/api/driver/{day_token}/orders/{record_id}/proof")
async def upload_proof(day_token: str, record_id: str, request: Request):
    drv = await _driver_by_token(day_token)
    body = await request.json()
    img = body.get("image_b64", "")
    if not img or len(img) > 6_000_000:
        raise HTTPException(400, "image_b64 required (max ~4MB)")
    order_id = body.get("order_id", record_id)
    db: Session = SessionLocal()
    try:
        db.add(Proof(order_id=order_id, content_b64=img,
                     content_type=body.get("content_type", "image/jpeg"),
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



@router.post("/api/driver/{day_token}/orders/{record_id}/{action}")
async def driver_action(day_token: str, record_id: str, action: str, request: Request,
                        background_tasks: BackgroundTasks):
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


# ---------- BOARD: LIFECYCLE COMPLETION ----------

@router.post("/api/board/{key}/orders/{record_id}/close")
async def close_order(key: str, record_id: str):
    _check_key(key)
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
    return {"drivers": [{
        "id": d["id"],
        "driver_id": d["fields"].get("driver_id", ""),
        "name": d["fields"].get("display_name", ""),
        "status": d["fields"].get("status", ""),
        "day_token": d["fields"].get("day_token", ""),
    } for d in drivers]}


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
    return {"ok": True, "id": created["id"], "day_token": token}


@router.post("/api/board/{key}/drivers/{record_id}/rotate")
async def rotate_driver_token(key: str, record_id: str):
    _check_key(key)
    token = _new_token()
    updated = await at.patch_record(at.DRIVERS, record_id, {"day_token": token})
    _log_event("driver.token_rotated",
               updated.get("fields", {}).get("driver_id", record_id), "founder", {})
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
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    records = await at.list_records(
        at.ORDERS, formula=f"DATETIME_FORMAT({{received_at}},'YYYY-MM-DD')='{today}'",
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
    recs = await at.list_records(at.ORDERS, formula=f"{{order_id}}='{oid}'", max_records=1)
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
            "customer_name_raw", "customer_phone_raw",
            "subtotal_cents", "fee_cents", "total_cents"]
    return {
        "record_id": recs[0]["id"],
        "fields": {k: f.get(k, "") for k in keep if f.get(k)},
        "has_proof": has_proof,
        "events": [{"event_type": e.event_type, "actor": e.actor,
                    "occurred_at": e.occurred_at.isoformat(), "payload": e.payload}
                   for e in evs],
    }


@router.post("/api/board/{key}/orders/{record_id}/requeue")
async def requeue_order(key: str, record_id: str):
    """Recover a failed delivery: return it to 'confirmed' so it can be reassigned."""
    _check_key(key)
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
    recs = await at.list_records(at.ORDERS, formula=f"RECORD_ID()='{record_id}'", max_records=1)
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
    recs = await at.list_records(at.ORDERS, formula=f"{{order_id}}='{oid}'", max_records=1)
    if not recs:
        return {"live": False}
    f = recs[0]["fields"]
    if f.get("status") != "in_transit":
        return {"live": False}
    driver_refs = f.get("driver") or []
    # resolve driver record -> driver_id
    ref = None
    if driver_refs:
        drecs = await at.list_records(at.DRIVERS, formula=f"RECORD_ID()='{driver_refs[0]}'", max_records=1)
        if drecs:
            ref = drecs[0]["fields"].get("driver_id", drecs[0]["id"])
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
    day = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    formula = f"DATETIME_FORMAT({{received_at}},'YYYY-MM-DD')='{day}'"
    if partner:
        formula = f"AND({formula},{{partner_code}}='{partner}')"
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


@router.get("/api/board/{key}/export.csv")
async def export_day_csv(key: str, date: str = ""):
    _check_key(key)
    import csv
    import io
    day = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    records = await at.list_records(
        at.ORDERS,
        formula=f"DATETIME_FORMAT({{received_at}},'YYYY-MM-DD')='{day}'",
        max_records=100)
    cols = ["order_id", "status", "partner_code", "customer_name_raw",
            "pickup_address", "dropoff_address", "items_description",
            "subtotal_cents", "fee_cents", "tip_cents", "total_cents",
            "received_at", "delivered_at", "cancel_reason"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in records:
        f = r["fields"]
        w.writerow([f.get(c, "") for c in cols])
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition":
                             f'attachment; filename="gateway-{day}.csv"'})


@router.get("/api/board/{key}/digest")
async def weekly_digest(key: str, partner: str = "", days: int = 7):
    _check_key(key)
    from datetime import timedelta
    days = max(1, min(days, 31))
    start = (datetime.now(timezone.utc) - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    formula = f"DATETIME_FORMAT({{received_at}},'YYYY-MM-DD')>='{start}'"
    if partner:
        formula = f"AND({formula},{{partner_code}}='{partner}')"
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
    before = await at.list_records(at.ORDERS, formula=f"RECORD_ID()='{record_id}'", max_records=1)
    old = {k: before[0]["fields"].get(k, "") for k in changes} if before else {}
    updated = await at.patch_record(at.ORDERS, record_id, changes)
    order_id = updated.get("fields", {}).get("order_id", record_id)
    _log_event("order.edited", order_id, "founder",
               {"changed": {k: {"from": old.get(k, ""), "to": v} for k, v in changes.items()}})
    return {"ok": True, "order_id": order_id}
