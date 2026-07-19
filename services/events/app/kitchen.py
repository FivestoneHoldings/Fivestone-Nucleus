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
from .bizday import business_day, business_day_of
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
    today = business_day()
    # CRITICAL: a ticket the kitchen still has to work must NEVER disappear
    # because of a date-format edge case. The active rail is queried by STATUS
    # ONLY — no date filter at all — so a scheduled order, a UTC-midnight
    # boundary, or an Airtable field-type quirk on received_at can never make an
    # open ticket vanish. (Root-caused a real 'orders not popping up' report:
    # the old single query required received_at OR requested_for to
    # DATETIME_FORMAT-match today, which is fragile if that field isn't a true
    # Airtable date type or the record sits right at a day boundary.)
    ACTIVE = ("received", "confirmed", "assigned")
    import asyncio as _aio
    active_records, day_all = await _aio.gather(
        at.list_records(
            at.ORDERS,
            formula=(f"AND({{partner_code}}='{p.code}',"
                     f"OR({{status}}='received',{{status}}='confirmed',{{status}}='assigned'))"),
            max_records=100),
        at.list_records(
            at.ORDERS,
            formula=(f"AND({{partner_code}}='{p.code}',"
                     f"OR(DATETIME_FORMAT(SET_TIMEZONE({{received_at}},'America/New_York'),'YYYY-MM-DD')='{today}',"
                     f"DATETIME_FORMAT({{requested_for}},'YYYY-MM-DD')='{today}'))"),
            max_records=100),
    )
    # the kitchen's active rail: tickets still in the kitchen's hands.
    # picked-up and delivered tickets leave the rail (counted instead).
    # pride stats — the kitchen's whole day (today's records only; cosmetic, not
    # load-bearing for whether a ticket is visible)
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
    records = [r for r in active_records if r["fields"].get("status") in ACTIVE]
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
        "logo_url": p.logo_url,
        "brand_color": p.brand_color,
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


@router.get("/api/kitchen/{token}/history")
async def kitchen_history(token: str):
    """The kitchen's day in review: every ticket that's left the building today
    (out for delivery / delivered), newest first, plus today's top sellers
    parsed from real tickets — the depth a serious operation reviews at close."""
    p = _partner_by_token(token)
    today = business_day()
    records = await at.list_records(
        at.ORDERS,
        formula=(f"AND({{partner_code}}='{p.code}',"
                 f"OR(DATETIME_FORMAT(SET_TIMEZONE({{received_at}},'America/New_York'),'YYYY-MM-DD')='{today}',"
                 f"DATETIME_FORMAT(SET_TIMEZONE({{delivered_at}},'America/New_York'),'YYYY-MM-DD')='{today}'),"
                 f"OR({{status}}='in_transit',{{status}}='delivered',{{status}}='closed'))"),
        max_records=100)
    records.sort(key=lambda r: (r["fields"].get("delivered_at")
                                or r["fields"].get("in_transit_at") or ""), reverse=True)
    # top sellers: parse "2× Pad Thai ($9.00), 1× Rolls (...)" quantity lines
    import re as _re
    counts: dict = {}
    for r in records:
        raw = (r["fields"].get("items_description") or "").split(" — subtotal")[0]
        for part in _re.split(r",\s*(?=\d+\s*[×xX])", raw):
            m = _re.match(r"^\s*(\d+)\s*[×xX]\s*(.+?)(?:\s*\(\$[\d.]+\))?\s*$", part)
            if m:
                name = m.group(2).strip()[:60]
                counts[name] = counts.get(name, 0) + int(m.group(1))
    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
    return {
        "tickets": [{
            "order_id": r["fields"].get("order_id", ""),
            "status": r["fields"].get("status", ""),
            "items": r["fields"].get("items_description", ""),
            "subtotal_cents": int(r["fields"].get("subtotal_cents") or 0),
            "delivered_at": r["fields"].get("delivered_at", ""),
        } for r in records[:40]],
        "top_sellers": [{"name": n, "qty": q} for n, q in top],
    }


@router.post("/api/kitchen/{token}/orders/{record_id}/accept")
async def kitchen_accept(token: str, record_id: str, request: Request):
    """A real kitchen ACCEPTS an incoming ticket before working it — optionally
    with a prep-time estimate ('this'll take 25 min') that flows straight to the
    customer's ETA. Moves received -> confirmed."""
    import re as _re
    p = _partner_by_token(token)
    safe_rec = _re.sub(r"[^A-Za-z0-9]", "", record_id)[:40]
    recs = await at.list_records(at.ORDERS, formula=f"RECORD_ID()='{safe_rec}'", max_records=1)
    if not recs:
        raise HTTPException(404, "No such order")
    if recs[0]["fields"].get("partner_code", "") != p.code:
        raise HTTPException(403, "That order belongs to a different kitchen")
    order_id = recs[0]["fields"].get("order_id", record_id)
    status = recs[0]["fields"].get("status", "")
    body = await request.json()
    try:
        est = int(body.get("prep_estimate_minutes") or 0)
    except (TypeError, ValueError):
        est = 0
    est = max(0, min(120, est))  # sane bound
    # only advance from 'received' — never walk a driver-assigned order backwards
    if status == "received":
        from datetime import datetime, timezone
        fields = {"status": "confirmed", "confirmed_at": datetime.now(timezone.utc).isoformat()}
        if est:
            fields["prep_estimate_minutes"] = est
        try:
            await at.patch_record(at.ORDERS, recs[0]["id"], fields)
        except Exception:
            # if the prep_estimate column doesn't exist yet, still confirm
            try:
                await at.patch_record(at.ORDERS, recs[0]["id"],
                                      {"status": "confirmed",
                                       "confirmed_at": datetime.now(timezone.utc).isoformat()})
            except Exception:
                raise HTTPException(502, "Could not update the order")
    db: Session = SessionLocal()
    try:
        db.add(Event(event_type="order.kitchen_accepted", entity_ref=order_id,
                     tenant="gateway", actor=f"kitchen:{p.code}",
                     payload=json.dumps({"partner": p.code, "prep_estimate_minutes": est})))
        db.commit()
    finally:
        db.close()
    return {"ok": True, "order_id": order_id, "prep_estimate_minutes": est}


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
    received_at = recs[0]["fields"].get("received_at", "")
    # honest prep-time telemetry: how many minutes from order-received to
    # kitchen-ready, captured at the moment it happens. This is what powers the
    # 'usually ready in ~X min' badge on the storefront — never a guess.
    prep_minutes = None
    if received_at:
        try:
            from datetime import datetime, timezone
            rt = datetime.fromisoformat(received_at.replace("Z", "+00:00"))
            if rt.tzinfo is None:
                rt = rt.replace(tzinfo=timezone.utc)
            delta = (datetime.now(timezone.utc) - rt).total_seconds() / 60
            if 0 < delta < 180:  # sanity bound — ignore stale/bad data
                prep_minutes = round(delta)
        except Exception:
            prep_minutes = None
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
                     tenant="gateway", actor=f"kitchen:{p.code}",
                     payload=json.dumps({"partner": p.code, "prep_minutes": prep_minutes})))
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


@router.get("/api/kitchen/{token}/verify")
async def verify_kitchen_token(token: str):
    """Confirm a kitchen access code is real — local database only.

    Sign-in must NOT depend on Airtable being reachable. Verifying against the
    live orders endpoint meant any Airtable hiccup locked every merchant out of
    their own screen mid-service. The partner record is the source of truth for
    'is this a valid code', and it lives in our own database."""
    p = _partner_by_token(token)
    return {"ok": True, "code": p.code, "display_name": p.display_name}


@router.post("/api/kitchen/{token}/posts")
async def create_post(token: str, request: Request):
    """The kitchen's own news feed — 'Back from vacation!', 'New menu is in!'.
    Real, dated, kitchen-authored, capped at the last 20 so it never turns into
    an unmoderated wall."""
    from .models import PartnerPost
    p = _partner_by_token(token)
    body = await request.json()
    text = str(body.get("text", "")).strip()[:280]
    if not text:
        raise HTTPException(400, "Post can't be empty")
    db: Session = SessionLocal()
    try:
        db.add(PartnerPost(partner_code=p.code, text=text))
        # trim to the most recent 20 for this partner — a feed, not an archive
        old = (db.query(PartnerPost).filter(PartnerPost.partner_code == p.code)
               .order_by(PartnerPost.created_at.desc()).offset(20).all())
        for row in old:
            db.delete(row)
        db.commit()
    finally:
        db.close()
    return {"ok": True}


@router.get("/api/kitchen/{token}/posts")
async def list_own_posts(token: str):
    from .models import PartnerPost
    p = _partner_by_token(token)
    db: Session = SessionLocal()
    try:
        rows = (db.query(PartnerPost).filter(PartnerPost.partner_code == p.code)
               .order_by(PartnerPost.created_at.desc()).limit(20).all())
        return {"posts": [{"id": r.id, "text": r.text,
                           "created_at": r.created_at.isoformat()} for r in rows]}
    finally:
        db.close()


@router.delete("/api/kitchen/{token}/posts/{post_id}")
async def delete_post(token: str, post_id: str):
    from .models import PartnerPost
    p = _partner_by_token(token)
    db: Session = SessionLocal()
    try:
        row = db.get(PartnerPost, post_id)
        if row and row.partner_code == p.code:
            db.delete(row)
            db.commit()
    finally:
        db.close()
    return {"ok": True}


@router.post("/api/kitchen/{token}/special")
async def set_special(token: str, request: Request):
    """The cook posts today's special — no corporate approval, no ad buy."""
    p = _partner_by_token(token)
    body = await request.json()
    text = str(body.get("text", "")).strip()[:200]
    today = business_day()
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
