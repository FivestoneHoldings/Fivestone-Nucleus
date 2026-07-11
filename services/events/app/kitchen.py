"""Kitchen Screen — the merchant-tablet equivalent. Token-gated per partner.
Shows today's active orders, beeps on new ones, one button: READY FOR PICKUP.
"""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
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
                    .filter(Event.event_type == "order.kitchen_ready",
                            Event.entity_ref.in_(order_ids)).all())
            ready = {e.entity_ref for e in rows}
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
        already = (db.query(Event)
                   .filter(Event.event_type == "order.kitchen_ready",
                           Event.entity_ref == order_id).count() > 0)
        if already:
            return {"ok": True, "idempotent": True, "order_id": order_id}
        db.add(Event(event_type="order.kitchen_ready", entity_ref=order_id,
                     tenant="gateway", actor=f"kitchen:{p.code}", payload=json.dumps({})))
        db.commit()
    finally:
        db.close()
    return {"ok": True, "order_id": order_id}


@router.post("/api/kitchen/{token}/accepting")
async def kitchen_accepting(token: str, request: Request):
    """Kitchen self-serve pause/resume — merchants control their own gate."""
    p = _partner_by_token(token)
    body = await request.json()
    on = bool(body.get("on", True))
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
    return {"ok": True, "accepting": on}
