"""Kitchen Screen — the merchant-tablet equivalent. Token-gated per partner.
Shows today's active orders, beeps on new ones, one button: READY FOR PICKUP.
"""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse
from pathlib import Path
from sqlalchemy.orm import Session

from . import airtable_client as at
from .db import SessionLocal
from .models import Event, Partner

router = APIRouter()
_UI = Path(__file__).parent / "ui"


def _partner_by_token(token: str) -> Partner:
    db: Session = SessionLocal()
    try:
        p = db.query(Partner).filter(Partner.portal_token == token).first()
    finally:
        db.close()
    if not p or not token:
        raise HTTPException(404, "Unknown kitchen link")
    return p


@router.get("/kitchen/{token}", response_class=HTMLResponse)
def kitchen_page(token: str):
    return (_UI / "kitchen.html").read_text()


@router.get("/api/kitchen/{token}/orders")
async def kitchen_orders(token: str):
    p = _partner_by_token(token)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # scheduled-order fix: an order placed Wednesday FOR Friday must appear Friday —
    # match on received today OR requested_for today.
    records = await at.list_records(
        at.ORDERS,
        formula=(f"AND({{partner_code}}='{p.code}',"
                 f"OR(DATETIME_FORMAT({{received_at}},'YYYY-MM-DD')='{today}',"
                 f"DATETIME_FORMAT({{requested_for}},'YYYY-MM-DD')='{today}'),"
                 f"NOT(OR({{status}}='closed',{{status}}='cancelled')))"),
        max_records=100)
    # the kitchen's active rail: tickets still in the kitchen's hands.
    # picked-up and delivered tickets leave the rail (counted instead).
    ACTIVE = ("received", "confirmed", "assigned")
    # pride stats — the kitchen's whole day, computed before we filter to the active rail
    day_all = records
    picked_up_today = sum(1 for r in day_all
                          if r["fields"].get("status") in ("in_transit", "delivered"))
    delivered_today = sum(1 for r in day_all
                          if r["fields"].get("status") in ("delivered", "closed"))
    revenue_today = sum(int(r["fields"].get("subtotal_cents") or 0) for r in day_all
                        if r["fields"].get("status") in ("in_transit", "delivered", "closed"))
    # busiest hour (by received_at) — a little insight the big dashboards bury
    from collections import Counter
    hours = Counter((r["fields"].get("received_at") or "")[11:13]
                    for r in day_all if r["fields"].get("received_at"))
    peak_hour = hours.most_common(1)[0][0] if hours else ""
    records = [r for r in records if r["fields"].get("status") in ACTIVE]
    records.sort(key=lambda r: (r["fields"].get("requested_for")
                                or r["fields"].get("received_at") or "9999"))
    order_ids = [r["fields"].get("order_id", "") for r in records]
    ready: set = set()
    if order_ids:
        db: Session = SessionLocal()
        try:
            rows = (db.query(Event)
                    .filter(Event.event_type.in_(["order.kitchen_ready",
                                                  "order.kitchen_ready_undone"]),
                            Event.entity_ref.in_(order_ids))
                    .order_by(Event.recorded_at).all())
            # An UNDO is a later event, not a deletion — the log stays append-only.
            # The ticket is ready iff its most recent ready/undo event is a READY.
            latest: dict = {}
            for e in rows:
                latest[e.entity_ref] = e.event_type
            ready = {ref for ref, ev in latest.items() if ev == "order.kitchen_ready"}
        finally:
            db.close()
    return {
        "kitchen": p.display_name,
        "accepting": p.accepting_orders,
        "picked_up_today": picked_up_today,
        "delivered_today": delivered_today,
        "revenue_today_cents": revenue_today,
        "peak_hour": peak_hour,
        "in_kitchen_now": len(records),
        "special": (p.special_text if p.special_date == today else ""),
        "load": ("slammed" if len(records) >= 8 else
                 "busy" if len(records) >= 4 else "steady"),
        "orders": [{
            "id": r["id"],
            "order_id": r["fields"].get("order_id", ""),
            "status": r["fields"].get("status", ""),
            "items": r["fields"].get("items_description", ""),
            "notes": r["fields"].get("special_instructions", ""),
            "requested_for": r["fields"].get("requested_for", ""),
            "received_at": r["fields"].get("received_at", ""),
            "ready": r["fields"].get("order_id", "") in ready,
        } for r in records],
    }


@router.post("/api/kitchen/{token}/orders/{record_id}/ready")
async def kitchen_ready(token: str, record_id: str, request: Request):
    import re as _re
    p = _partner_by_token(token)
    safe_rec = _re.sub(r"[^A-Za-z0-9]", "", record_id)[:40]
    recs = await at.list_records(at.ORDERS, formula=f"RECORD_ID()='{safe_rec}'", max_records=1)
    if not recs:
        raise HTTPException(404, "No such order")
    if recs[0]["fields"].get("partner_code", "") != p.code:
        raise HTTPException(403, "That order belongs to a different kitchen")
    order_id = recs[0]["fields"].get("order_id", record_id)
    db: Session = SessionLocal()
    try:
        last = (db.query(Event)
                .filter(Event.event_type.in_(["order.kitchen_ready",
                                              "order.kitchen_ready_undone"]),
                        Event.entity_ref == order_id)
                .order_by(Event.recorded_at.desc()).first())
        if last is not None and last.event_type == "order.kitchen_ready":
            return {"ok": True, "idempotent": True, "order_id": order_id}
        db.add(Event(event_type="order.kitchen_ready", entity_ref=order_id,
                     tenant="gateway", actor=f"kitchen:{p.code}", payload=json.dumps({})))
        db.commit()
    finally:
        db.close()
    return {"ok": True, "order_id": order_id}


@router.post("/api/kitchen/{token}/accepting")
async def kitchen_accepting(token: str, request: Request,
                            background_tasks: BackgroundTasks):
    """Kitchen self-serve pause/resume — merchants control their own gate."""
    p = _partner_by_token(token)
    body = await request.json()
    on = bool(body.get("on", True))
    was = p.accepting_orders
    db: Session = SessionLocal()
    try:
        row = db.get(Partner, p.code)
        row.accepting_orders = on
        db.add(Event(event_type="partner.resumed" if on else "partner.paused",
                     entity_ref=p.code, tenant="gateway",
                     actor=f"kitchen:{p.code}", payload=json.dumps({})))
        db.commit()
    finally:
        db.close()
    if on and not was:
        from .identity import _flush_reopen_alerts
        background_tasks.add_task(_flush_reopen_alerts, p.code, p.display_name)
    return {"ok": True, "accepting": on}


@router.post("/api/kitchen/{token}/special")
async def set_special(token: str, request: Request):
    """The cook posts today's special — no corporate approval, no ad buy."""
    p = _partner_by_token(token)
    body = await request.json()
    text = str(body.get("text", "")).strip()[:200]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    db: Session = SessionLocal()
    try:
        row = db.get(Partner, p.code)
        row.special_text = text
        row.special_date = today if text else ""
        db.add(Event(event_type="partner.special_posted", entity_ref=p.code,
                     tenant="gateway", actor=f"kitchen:{p.code}",
                     payload=json.dumps({"text": text})))
        db.commit()
    finally:
        db.close()
    return {"ok": True, "special": text}


# ---------- UNDO (v1.1) ----------
# A cook's thumb slips. Before GateWay, that meant a phone call. Now it means a
# button — for a short window, and ONLY while the ticket is still in the kitchen.
# Once a driver has the food in their hands, the kitchen cannot rewrite history:
# the truth of where that food is belongs to the person holding it.
UNDO_WINDOW_SECONDS = 120


@router.post("/api/kitchen/{token}/orders/{record_id}/unready")
async def kitchen_unready(token: str, record_id: str, request: Request):
    import re as _re
    from datetime import datetime, timedelta, timezone as _tz
    p = _partner_by_token(token)
    safe_rec = _re.sub(r"[^A-Za-z0-9]", "", record_id)[:40]
    recs = await at.list_records(at.ORDERS, formula=f"RECORD_ID()='{safe_rec}'", max_records=1)
    if not recs:
        raise HTTPException(404, "No such order")
    if recs[0]["fields"].get("partner_code", "") != p.code:
        raise HTTPException(403, "That order belongs to a different kitchen")
    status = recs[0]["fields"].get("status", "")
    order_id = recs[0]["fields"].get("order_id", record_id)

    # The driver already has it. Undo would be a lie.
    if status in ("in_transit", "delivered", "closed"):
        raise HTTPException(409, "The driver already has this order — call dispatch "
                                 "and we'll sort it out together.")

    db: Session = SessionLocal()
    try:
        last = (db.query(Event)
                .filter(Event.event_type.in_(["order.kitchen_ready",
                                              "order.kitchen_ready_undone"]),
                        Event.entity_ref == order_id)
                .order_by(Event.recorded_at.desc()).first())
        if last is None or last.event_type != "order.kitchen_ready":
            raise HTTPException(409, "That ticket isn't marked ready.")

        stamped = last.recorded_at
        if stamped.tzinfo is None:
            stamped = stamped.replace(tzinfo=_tz.utc)
        age = datetime.now(_tz.utc) - stamped
        if age > timedelta(seconds=UNDO_WINDOW_SECONDS):
            raise HTTPException(409, "Too late to undo — a driver may already be on "
                                     "the way. Call dispatch.")

        db.add(Event(event_type="order.kitchen_ready_undone", entity_ref=order_id,
                     tenant="gateway", actor=f"kitchen:{p.code}",
                     payload=json.dumps({"seconds_after_ready": int(age.total_seconds())})))
        db.commit()
    finally:
        db.close()
    return {"ok": True, "order_id": order_id, "undone": True}
