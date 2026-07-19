"""OWNED intake — GateWay Dispatch orders enter through Fivestone infrastructure.
Same dedup contract as the Make v0.2 pipeline (fingerprint-compatible), so both
paths coexist. This is the canonical path from v0.4 forward.
"""
import hashlib
import json
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from . import airtable_client as at
from . import notify
from .bizday import MARKET_TZ
from .db import SessionLocal
from .models import Event, MenuItem, Partner

router = APIRouter()

FIELDS = ["customer_name", "customer_phone", "pickup_address", "dropoff_address",
          "dropoff_contact_name", "dropoff_contact_phone", "items_description",
          "special_instructions", "requested_for", "partner",
          "subtotal_cents", "fee_cents", "total_cents", "tip_cents",
          "promo_code", "discount_cents", "cart_json"]

CAPS = {"items_description": 1000, "special_instructions": 600,
        "pickup_address": 300, "dropoff_address": 300,
        "customer_name": 120, "dropoff_contact_name": 120,
        "customer_phone": 30, "dropoff_contact_phone": 30,
        "requested_for": 40, "partner": 60,
        "subtotal_cents": 12, "fee_cents": 12, "total_cents": 12, "tip_cents": 12,
        "promo_code": 30, "discount_cents": 12, "cart_json": 8000}

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


# How close together two identical orders must be to count as an accidental
# double-submit rather than a genuine repeat order. Long enough to absorb a
# double-tap, a rage-refresh, or a flaky connection retry; far short of the
# hours between a real lunch and a real dinner.
DEDUP_WINDOW_SECONDS = 8 * 60


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
<style>body{{font-family:'Archivo',system-ui,sans-serif;background:#f7f8fb;color:#16181b;
display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:20px}}
.card{{text-align:center;max-width:420px}}
.check{{width:72px;height:72px;border-radius:50%;background:#16337a;color:#fff;font-size:2rem;
line-height:72px;margin:0 auto 20px}}
h1{{font-size:1.3rem;font-weight:800}}
p{{color:#5a5e64;line-height:1.6;font-size:.95rem}}
.oid{{font-family:'IBM Plex Mono',monospace;background:#fff;border:1.5px solid #d9deea;
border-radius:8px;padding:10px 16px;display:inline-block;margin:14px 0;font-size:.9rem}}
.foot{{font-family:'IBM Plex Mono',monospace;font-size:.65rem;color:#9a9ea5;margin-top:28px;
text-transform:uppercase;letter-spacing:.08em}}</style></head>
<body><div class="card"><div class="check">✓</div>
<h1>{headline}</h1>
<div class="oid">{order_id}</div>
<p>{message}</p>
<p class="foot">GateWay Delivery · Fivestone Holdings<br>Knoxville, Tennessee &amp; surrounding areas</p>
</div></body></html>"""


@router.api_route("/v0/intake", methods=["GET", "POST"])
async def intake(request: Request, background_tasks: BackgroundTasks):
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

    from . import payments
    payment_method = payments.normalize_method(data.get("payment_method", ""))
    data = {k: str(data.get(k, "")).strip()[:CAPS[k]] for k in FIELDS}
    # A real browser form submission (order-form.html's <form method="GET">)
    # and an AJAX fetch() GET call (courier.html, so it can stay on the page
    # and show an inline confirmation card) are BOTH plain GET requests — the
    # method alone can't tell them apart. Without this override, courier's
    # fetch() got an HTML page back where its JS expected JSON: `await
    # r.json()` silently failed inside a try/catch, leaving the order ID blank
    # on the confirmation screen and the order never saved to the customer's
    # local order history. A caller that explicitly asks for JSON is honored
    # regardless of HTTP method.
    accept = request.headers.get("accept", "")
    if "application/json" in accept and "text/html" not in accept:
        wants_html = False
    else:
        wants_html = request.method == "GET" or "form" in request.headers.get("content-type", "")
    client_ip = (request.headers.get("x-forwarded-for", "") or
                 (request.client.host if request.client else "?")).split(",")[0].strip()
    if _throttled(client_ip):
        if wants_html:
            return HTMLResponse(CONFIRM_PAGE.format(
                headline="Whoa — slow down a second", order_id="—",
                message="Too many orders from this connection in one minute. Wait a moment and try again."), status_code=429)
        return JSONResponse({"received": False, "error": "Too many requests"}, status_code=429)
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

    # A scheduled order for a time that's already passed would sit forever as
    # neither "now" nor "today" to the kitchen — never cooked, never delivered.
    # The datetime picker sets a live min= to steer customers away from this,
    # but that's client-side and can't be trusted (stale page, edited devtools,
    # a direct API call). Reject anything more than a few minutes in the past;
    # small clock skew between browser and server shouldn't hard-fail a real
    # near-immediate order.
    if data["requested_for"]:
        try:
            _req = datetime.fromisoformat(data["requested_for"])
            if _req.tzinfo is None:
                _req = _req.replace(tzinfo=MARKET_TZ)
            if _req < datetime.now(MARKET_TZ) - timedelta(minutes=5):
                if wants_html:
                    return HTMLResponse(CONFIRM_PAGE.format(
                        headline="That time has already passed",
                        order_id="—",
                        message="Pick an upcoming time for a scheduled order, or choose ASAP instead."), status_code=400)
                return JSONResponse({"received": False, "error": "requested_for_in_past"}, status_code=400)
        except (ValueError, TypeError):
            data["requested_for"] = ""  # unparseable — drop it rather than 500 later

    fp = _fingerprint(data["dropoff_address"], data["items_description"], data["requested_for"])
    order_id = "ORD-" + fp[:8].upper()

    # --- CART RE-PRICING (v1.4), run BEFORE the try/except below ---
    # A raised HTTPException here must reach the customer as its real status
    # code and message ("An item in your cart is no longer available"), not get
    # swallowed by the broad except-Exception handler further down and turned
    # into a generic 503. It's caught and rendered locally (see except
    # HTTPException below) rather than left to propagate: the app-wide handler
    # in main.py only brands 404s and treats every /v0/ path as not wanting
    # HTML regardless of Accept header, so a real customer on a real GET form
    # submission would otherwise see a raw JSON blob mid-checkout instead of
    # GateWay's confirmation page. The server re-derives EVERY line's price
    # from the database and overwrites subtotal_cents — same posture as the
    # v1.1 promo fix. Options can only ADD cost (enforced at creation/edit
    # time), so this can only ever raise the subtotal versus a naive client
    # total, never lower it.
    cart_subtotal_override = None
    cart_raw = data.get("cart_json") or "[]"
    try:
        cart = json.loads(cart_raw) if isinstance(cart_raw, str) else cart_raw
    except (ValueError, TypeError):
        cart = []
    if isinstance(cart, list) and cart:
        from .options import validate_selected_options
        _db2 = SessionLocal()
        try:
            recomputed = 0
            for line in cart[:60]:            # hard cap — no absurd carts
                item_id = str(line.get("item_id", ""))[:36]
                qty = max(1, min(20, int(line.get("qty", 1))))
                choice_ids = [str(c)[:36] for c in (line.get("choice_ids") or [])][:20]
                item = _db2.get(MenuItem, item_id)
                if not item or not item.available:
                    raise HTTPException(422, "An item in your cart is no longer available.")
                if item.partner_code != data["partner"]:
                    raise HTTPException(422, "Cart item does not belong to this kitchen.")
                delta = validate_selected_options(_db2, item_id, choice_ids)
                recomputed += (item.price_cents + delta) * qty
            cart_subtotal_override = recomputed
        except HTTPException as _cart_exc:
            # The global handler only brands 404s and never treats /v0/ paths as
            # HTML-wanting regardless of Accept header — so letting this
            # propagate meant a real customer, mid-checkout on a real GET form
            # submission, saw a raw {"detail":"..."} JSON blob instead of
            # GateWay's confirmation page. Format it ourselves, the same way
            # every other error in this function already does.
            if wants_html:
                return HTMLResponse(CONFIRM_PAGE.format(
                    headline="One thing changed", order_id="—",
                    message=f"{_cart_exc.detail} Please go back, refresh the menu, "
                            f"and try again."), status_code=_cart_exc.status_code)
            return JSONResponse({"received": False, "error": "cart_item_invalid",
                                 "detail": _cart_exc.detail}, status_code=_cart_exc.status_code)
        finally:
            _db2.close()

    if not at.configured():
        if wants_html:
            return HTMLResponse(CONFIRM_PAGE.format(
                headline="We couldn't take your order online", order_id="—",
                message="Our order system is briefly unavailable. Please call GateWay and we'll take it by phone — sorry for the trouble."), status_code=503)
        return JSONResponse({"received": False, "error": "intake_unavailable"}, status_code=503)

    duplicate = False
    try:
        # Duplicate protection is meant to catch an ACCIDENTAL DOUBLE-SUBMIT
        # (double-tapped button, impatient refresh) — NOT a legitimate repeat
        # order. The old check treated any same-items/same-address order on the
        # same calendar day as a duplicate and silently refused to create it,
        # which broke real cases: an office where two people each want the same
        # dish, or a household that orders the same thing for lunch and again
        # for dinner. Now the fingerprint still buckets by day (so the Airtable
        # query stays a cheap exact match), but a match only counts as a
        # duplicate if it landed within the last few minutes.
        existing = await at.list_records(at.ORDERS, formula=f"{{fingerprint}}='{fp}'",
                                         max_records=5)
        now_utc = datetime.now(timezone.utc)
        for _rec in existing:
            _stamp = _rec.get("fields", {}).get("received_at", "")
            if not _stamp:
                continue
            try:
                _when = datetime.fromisoformat(str(_stamp).replace("Z", "+00:00"))
                if _when.tzinfo is None:
                    _when = _when.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
            if (now_utc - _when).total_seconds() <= DEDUP_WINDOW_SECONDS:
                duplicate = True
                break
        if not duplicate:
            # --- STANDING DELIVERY PREFERENCES (v1.5) ---
            # "Megan prefers no-contact delivery. Blue house, no garage. Always
            # knock." If this phone number has saved preferences, fold them
            # into what the DRIVER actually sees — special_instructions is the
            # one field that already flows all the way to the driver's day
            # sheet, so this needs no new Airtable schema to work today.
            std_note = ""
            if data["customer_phone"]:
                from .models import DeliveryPreference as _DP
                _pdb = SessionLocal()
                try:
                    pref = _pdb.get(_DP, "".join(ch for ch in data["customer_phone"] if ch.isdigit())[-15:])
                    if pref:
                        bits = []
                        style_word = {"leave_at_door": "Leave at the door",
                                     "meet_outside": "Meet outside",
                                     "hand_to_me": "Hand it to me"}.get(pref.dropoff_style, "")
                        if style_word:
                            bits.append(style_word)
                        if pref.avoid_doorbell:
                            bits.append("no doorbell")
                        if not pref.knock:
                            bits.append("don't knock")
                        if pref.home_description:
                            bits.append(pref.home_description[:120])
                        if pref.access_notes:
                            bits.append(pref.access_notes[:150])
                        if pref.driver_notes:
                            bits.append(pref.driver_notes[:150])
                        if pref.allergies:
                            bits.append("ALLERGY: " + pref.allergies[:100])
                        if bits:
                            std_note = "📋 Standing notes: " + " · ".join(bits)
                        # --- REQUEST A DRIVER (v1.5) ---
                        # A name saved to a profile is a wish, not a fact. We
                        # turn it into a real, trackable DriverRequest so
                        # dispatch can actually TRY — but the disclaimer on
                        # /me is honest: a driver has their own day, and we
                        # never promise what we can't keep.
                        if pref.preferred_driver:
                            from .models import DriverRequest as _DR
                            _pdb.add(_DR(order_id=order_id,
                                        requested_driver=pref.preferred_driver[:80],
                                        customer_phone=data["customer_phone"]))
                            _pdb.commit()
                finally:
                    _pdb.close()
            merged_instructions = data["special_instructions"]
            if std_note:
                merged_instructions = (std_note + (" — " + merged_instructions if merged_instructions else ""))[:600]

            fields = {
                "order_id": order_id, "status": "received",
                "source_channel": "webhook",
                "pickup_address": data["pickup_address"],
                "dropoff_address": data["dropoff_address"],
                "dropoff_contact_name": data["dropoff_contact_name"],
                "dropoff_contact_phone": data["dropoff_contact_phone"],
                "items_description": data["items_description"],
                "special_instructions": merged_instructions,
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
            if cart_subtotal_override is not None:
                fields["subtotal_cents"] = cart_subtotal_override

            # --- SERVER IS THE ONLY AUTHORITY ON MONEY (v1.1) ---
            # A tampered client must never be able to shrink what the driver
            # collects at the door. We re-derive the discount from the DB and
            # recompute the total; the client's discount_cents is ignored.
            sub = int(fields.get("subtotal_cents") or 0)
            fee = int(fields.get("fee_cents") or 0)
            tip = int(fields.get("tip_cents") or 0)
            promo = str(data.get("promo_code") or "").strip().upper()[:30]
            disc = 0
            if promo and sub > 0:
                from .growth import promo_discount_cents
                from .db import SessionLocal as _SL
                _db = _SL()
                try:
                    disc, desc = promo_discount_cents(promo, data["partner"], sub, _db)
                    if disc > 0:
                        from .models import PromoCode as _PC
                        row = _db.get(_PC, promo)
                        if row:
                            row.uses += 1
                            _db.commit()
                        _log_owned("order.promo_applied", order_id,
                                   {"code": promo, "discount_cents": disc, "description": desc})
                finally:
                    _db.close()
            disc = max(0, min(disc, sub))
            if disc:
                fields["promo_code"] = promo
                fields["discount_cents"] = disc
            if sub:
                fields["total_cents"] = max(0, sub + fee + tip - disc)
            await at.create_record(at.ORDERS, fields)
            _log_owned("order.payment_method", order_id, {"method": payment_method})
            _log_owned("order.received", order_id,
                       {"partner": data["partner"], "customer": data["customer_name"],
                        "dropoff": data["dropoff_address"], "items": data["items_description"],
                        "channel": "nucleus-intake"})
            if data["customer_phone"]:
                background_tasks.add_task(notify.send_sms, order_id,
                                          data["customer_phone"],
                                          notify.msg_received(order_id))
    except Exception as e:
        _log_owned("order.intake_error", order_id, {"error": str(e)[:300]})
        if wants_html:
            return HTMLResponse(CONFIRM_PAGE.format(
                headline="We couldn't save your order", order_id="—",
                message="Something went wrong on our side and your order was NOT placed. Please try again in a minute or call GateWay."), status_code=503)
        return JSONResponse({"received": False, "error": "intake_failed"}, status_code=503)

    if wants_html:
        if duplicate:
            return HTMLResponse(CONFIRM_PAGE.format(
                headline="We already have this one!", order_id=order_id,
                message="You just sent this same order a moment ago, so we didn't create a second one. We're already on it."))
        return HTMLResponse(
            f'<!DOCTYPE html><html><head><meta charset="UTF-8">'
            f'<meta http-equiv="refresh" content="0; url=/track/{order_id}">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'</head><body style="font-family:system-ui;background:#f7f8fb;text-align:center;padding-top:80px">'
            f'Order received — taking you to live tracking…'
            f'<script>location.replace("/track/{order_id}")</script></body></html>')
    return JSONResponse({"received": True, "order_id": order_id, "duplicate": duplicate})
