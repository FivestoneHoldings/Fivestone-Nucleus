"""OWNED intake — GateWay Dispatch orders enter through Fivestone infrastructure.
Same dedup contract as the Make v0.2 pipeline (fingerprint-compatible), so both
paths coexist. This is the canonical path from v0.4 forward.
"""
import hashlib
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from . import airtable_client as at
from . import notify
from .db import SessionLocal
from .models import Event, Partner

router = APIRouter()

FIELDS = ["customer_name", "customer_phone", "pickup_address", "dropoff_address",
          "dropoff_contact_name", "dropoff_contact_phone", "items_description",
          "special_instructions", "requested_for", "partner",
          "subtotal_cents", "fee_cents", "total_cents", "tip_cents"]

CAPS = {"items_description": 1000, "special_instructions": 600,
        "pickup_address": 300, "dropoff_address": 300,
        "customer_name": 120, "dropoff_contact_name": 120,
        "customer_phone": 30, "dropoff_contact_phone": 30,
        "requested_for": 40, "partner": 60,
        "subtotal_cents": 12, "fee_cents": 12, "total_cents": 12, "tip_cents": 12}

# In-memory per-IP throttle: 30 submissions/minute (dispatch-scale abuse guard)
_HITS: dict = {}


def _throttled(ip: str) -> bool:
    import time
    now = time.time()
    window = [t for t in _HITS.get(ip, []) if now - t < 60]
    window.append(now)
    _HITS[ip] = window
    if len(_HITS) > 5000:  # bound memory
        _HITS.clear()
    return len(window) > 30


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fingerprint(dropoff: str, items: str, requested_for: str) -> str:
    bucket = requested_for or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return hashlib.md5((dropoff.lower() + items.lower() + bucket.lower()).encode()).hexdigest()


def _log_owned(event_type: str, entity_ref: str, payload: dict):
    db = SessionLocal()
    try:
        db.add(Event(event_type=event_type, entity_ref=entity_ref,
                     tenant="gateway", actor="system", payload=json.dumps(payload)))
        db.commit()
    finally:
        db.close()


CONFIRM_PAGE = """<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Order Received — GateWay Delivery</title>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;600;800&family=IBM+Plex+Mono:wght@500&display=swap" rel="stylesheet">
<style>body{{font-family:'Archivo',system-ui,sans-serif;background:#f7f6f3;color:#16181b;
display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:20px}}
.card{{text-align:center;max-width:420px}}
.check{{width:72px;height:72px;border-radius:50%;background:#1f4d3a;color:#fff;font-size:2rem;
line-height:72px;margin:0 auto 20px}}
h1{{font-size:1.3rem;font-weight:800}}
p{{color:#5a5e64;line-height:1.6;font-size:.95rem}}
.oid{{font-family:'IBM Plex Mono',monospace;background:#fff;border:1.5px solid #e0ddd6;
border-radius:8px;padding:10px 16px;display:inline-block;margin:14px 0;font-size:.9rem}}
.foot{{font-family:'IBM Plex Mono',monospace;font-size:.65rem;color:#9a9ea5;margin-top:28px;
text-transform:uppercase;letter-spacing:.08em}}</style></head>
<body><div class="card"><div class="check">✓</div>
<h1>{headline}</h1>
<div class="oid">{order_id}</div>
<p>{message}</p>
<p class="foot">GateWay Delivery · Fivestone Holdings<br>Blount &amp; Knox County, Tennessee</p>
</div></body></html>"""


@router.api_route("/v0/intake", methods=["GET", "POST"])
async def intake(request: Request):
    # Accept form GET, form POST, or JSON POST
    data: dict = {}
    if request.method == "GET":
        data = dict(request.query_params)
    else:
        ctype = request.headers.get("content-type", "")
        if "application/json" in ctype:
            data = await request.json()
        else:
            form = await request.form()
            data = dict(form)

    data = {k: str(data.get(k, "")).strip()[:CAPS[k]] for k in FIELDS}
    client_ip = (request.headers.get("x-forwarded-for", "") or
                 (request.client.host if request.client else "?")).split(",")[0].strip()
    if _throttled(client_ip):
        return JSONResponse({"received": False, "error": "Too many requests"}, status_code=429)
    wants_html = request.method == "GET" or "form" in request.headers.get("content-type", "")

    if not data["dropoff_address"] or not data["items_description"]:
        if wants_html:
            return HTMLResponse(CONFIRM_PAGE.format(
                headline="Something's missing", order_id="—",
                message="We need at least a dropoff address and what we're delivering. Go back and try again."), status_code=400)
        return JSONResponse({"received": False, "error": "dropoff_address and items_description required"}, status_code=400)

    if data["partner"]:
        db = SessionLocal()
        try:
            p = db.get(Partner, data["partner"].lower())
        finally:
            db.close()
        if p and not p.accepting_orders:
            if wants_html:
                return HTMLResponse(CONFIRM_PAGE.format(
                    headline=f"{p.display_name} isn't taking orders right now",
                    order_id="—",
                    message="The kitchen is paused at the moment. Please check back soon — or call GateWay and we'll help."), status_code=423)
            return JSONResponse({"received": False, "error": "partner_paused"}, status_code=423)

    fp = _fingerprint(data["dropoff_address"], data["items_description"], data["requested_for"])
    order_id = "ORD-" + fp[:8].upper()

    duplicate = False
    if at.configured():
        existing = await at.list_records(at.ORDERS, formula=f"{{fingerprint}}='{fp}'", max_records=1)
        duplicate = bool(existing)
        if not duplicate:
            fields = {
                "order_id": order_id, "status": "received",
                "source_channel": "webhook",
                "pickup_address": data["pickup_address"],
                "dropoff_address": data["dropoff_address"],
                "dropoff_contact_name": data["dropoff_contact_name"],
                "dropoff_contact_phone": data["dropoff_contact_phone"],
                "items_description": data["items_description"],
                "special_instructions": data["special_instructions"],
                "fingerprint": fp, "received_at": _now(),
                "customer_name_raw": data["customer_name"],
                "customer_phone_raw": data["customer_phone"],
            }
            if data["partner"]:
                fields["partner_code"] = data["partner"]
            if data["requested_for"]:
                fields["requested_for"] = data["requested_for"]
            for money_field in ("subtotal_cents", "fee_cents", "total_cents", "tip_cents"):
                if data.get(money_field):
                    try:
                        fields[money_field] = int(data[money_field])
                    except (ValueError, TypeError):
                        pass
            await at.create_record(at.ORDERS, fields)
            _log_owned("order.received", order_id,
                       {"partner": data["partner"], "customer": data["customer_name"],
                        "dropoff": data["dropoff_address"], "items": data["items_description"],
                        "channel": "nucleus-intake"})
            if data["customer_phone"]:
                await notify.send_sms(order_id, data["customer_phone"],
                                      notify.msg_received(order_id))

    if wants_html:
        if duplicate:
            return HTMLResponse(CONFIRM_PAGE.format(
                headline="We already have this one!", order_id=order_id,
                message="This exact order was already received today — no duplicate was created. We're on it."))
        return HTMLResponse(
            f'<!DOCTYPE html><html><head><meta charset="UTF-8">'
            f'<meta http-equiv="refresh" content="0; url=/track/{order_id}">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'</head><body style="font-family:system-ui;background:#f7f6f3;text-align:center;padding-top:80px">'
            f'Order received — taking you to live tracking…'
            f'<script>location.replace("/track/{order_id}")</script></body></html>')
    return JSONResponse({"received": True, "order_id": order_id, "duplicate": duplicate})
