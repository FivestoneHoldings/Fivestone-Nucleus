"""Customer SMS notifications via Twilio (raw REST — no SDK dependency).
Graceful degradation: unconfigured or bad phone → recorded as skipped, never crashes
the order flow. Configure with Railway vars: TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM.
"""
import os
import re

import httpx
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import Notification

BASE_URL = os.environ.get("BASE_URL", "https://fivestone-nucleus-production.up.railway.app")


def _cfg():
    return (os.environ.get("TWILIO_SID", ""), os.environ.get("TWILIO_TOKEN", ""),
            os.environ.get("TWILIO_FROM", ""))


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    if raw.startswith("+") and len(digits) >= 10:
        return "+" + digits
    return ""


async def _twilio_post(sid: str, token: str, from_: str, to: str, body: str) -> tuple[bool, str]:
    async with httpx.AsyncClient(timeout=12) as c:
        r = await c.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            auth=(sid, token),
            data={"From": from_, "To": to, "Body": body})
        if r.status_code in (200, 201):
            return True, r.json().get("sid", "")
        return False, f"HTTP {r.status_code}: {r.text[:200]}"


def _record(order_id: str, to: str, body: str, status: str, detail: str = ""):
    db: Session = SessionLocal()
    try:
        db.add(Notification(order_id=order_id, to_phone=to, body=body,
                            status=status, detail=detail[:300]))
        db.commit()
    finally:
        db.close()


async def send_sms(order_id: str, raw_phone: str, body: str) -> str:
    """Send one SMS; always leaves a Notification row. Returns the outcome status."""
    to = normalize_phone(raw_phone)
    if not to:
        _record(order_id, raw_phone or "?", body, "skipped_no_phone")
        return "skipped_no_phone"
    sid, token, from_ = _cfg()
    if not (sid and token and from_):
        _record(order_id, to, body, "skipped_unconfigured",
                "Set TWILIO_SID / TWILIO_TOKEN / TWILIO_FROM in Railway Variables")
        return "skipped_unconfigured"
    try:
        ok, detail = await _twilio_post(sid, token, from_, to, body)
    except Exception as e:  # network etc — never break the order flow
        ok, detail = False, str(e)[:200]
    _record(order_id, to, body, "sent" if ok else "failed", detail)
    return "sent" if ok else "failed"


def msg_received(order_id: str) -> str:
    return (f"GateWay Delivery: we got your order {order_id}. "
            f"Track it live: {BASE_URL}/track/{order_id}")


def msg_on_the_way(order_id: str) -> str:
    return (f"GateWay Delivery: your order {order_id} is on the way! "
            f"Follow along: {BASE_URL}/track/{order_id}")


def msg_delivered(order_id: str) -> str:
    return (f"GateWay Delivery: order {order_id} delivered. "
            f"Thank you for choosing GateWay!")
