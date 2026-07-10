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
    records = await at.list_records(
        at.ORDERS,
        formula=(f"AND({{partner_code}}='{p.code}',"
                 f"DATETIME_FORMAT({{received_at}},'YYYY-MM-DD')='{today}',"
                 f"NOT(OR({{status}}='closed',{{status}}='cancelled')))"),
        max_records=100)
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
