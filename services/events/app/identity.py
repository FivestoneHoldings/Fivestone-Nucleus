"""Identity v0 — partner/tenant registry (staged in the monolith per ADR-008).
Public: name lookup for co-branding. Key-gated: full list + create/update.
"""
import os
import secrets
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import Partner, ReopenAlert

router = APIRouter()

SEED = [("asiacafe", "Asia Cafe"), ("asiacafexpress", "Asia Cafe Xpress")]


def _todays_special(p) -> str:
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return p.special_text if (p.special_date == today and p.special_text) else ""


def _new_portal_token() -> str:
    return "kt-" + secrets.token_hex(5)


def seed_partners():
    db: Session = SessionLocal()
    try:
        if db.query(Partner).count() == 0:
            for code, name in SEED:
                db.add(Partner(code=code, display_name=name, status="pilot",
                               portal_token=_new_portal_token()))
            db.commit()
        # backfill portal tokens on existing partners (idempotent)
        for p in db.query(Partner).filter(Partner.portal_token == "").all():
            p.portal_token = _new_portal_token()
        db.commit()
    finally:
        db.close()


def _check_key(key: str):
    admin = os.environ.get("ADMIN_KEY", "")
    if not admin or not secrets.compare_digest(str(key), admin):
        raise HTTPException(403, "Bad board key")


@router.get("/v0/partners")
def public_partner_directory():
    """Public: active/pilot partners that have a menu — the 'restaurant list'."""
    from .models import MenuItem
    db: Session = SessionLocal()
    try:
        rows = (db.query(Partner)
                .filter(Partner.status.in_(["active", "pilot"]))
                .order_by(Partner.display_name).all())
        out = []
        for p in rows:
            has_menu = (db.query(MenuItem)
                        .filter(MenuItem.partner_code == p.code,
                                MenuItem.available.is_(True)).count() > 0)
            if has_menu:
                out.append({
                    "code": p.code,
                    "display_name": p.display_name,
                    "address": p.address,
                    "delivery_fee_cents": p.delivery_fee_cents,
                    "accepting_orders": p.accepting_orders,
                    "hero_url": p.hero_url,
                    "about_blurb": p.about_blurb,
                    "special": _todays_special(p),
                    "cuisine": p.cuisine,
                    "tagline": p.tagline,
                    "brand_color": p.brand_color,
                    "logo_url": p.logo_url,
                    "featured": p.featured,
                    "demo": p.demo,
                })
    finally:
        db.close()
    return {"partners": out}


@router.get("/v0/partners/{code}")
def partner_lookup(code: str):
    """Public co-branding lookup — name and status only."""
    db: Session = SessionLocal()
    try:
        p = db.get(Partner, code.lower().strip())
    finally:
        db.close()
    if not p:
        raise HTTPException(404, "Unknown partner")
    return {"code": p.code, "display_name": p.display_name, "status": p.status,
            "address": p.address, "delivery_fee_cents": p.delivery_fee_cents,
            "accepting_orders": p.accepting_orders,
            "about_blurb": p.about_blurb,
            "hero_url": p.hero_url,
            "cuisine": p.cuisine,
            "tagline": p.tagline,
            "brand_color": p.brand_color,
            "logo_url": p.logo_url,
            "demo": p.demo,
            "special": _todays_special(p)}


@router.get("/api/board/{key}/partners")
def list_partners(key: str):
    _check_key(key)
    db: Session = SessionLocal()
    try:
        rows = db.query(Partner).order_by(Partner.created_at).all()
    finally:
        db.close()
    return {"partners": [{"code": p.code, "display_name": p.display_name,
                          "status": p.status, "contact": p.contact,
                          "address": p.address, "delivery_fee_cents": p.delivery_fee_cents,
                          "accepting_orders": p.accepting_orders,
                          "portal_token": p.portal_token,
                          "thank_you_note": p.thank_you_note,
                          "about_blurb": p.about_blurb,
                          "hero_url": p.hero_url,
                          "cuisine": p.cuisine,
                          "tagline": p.tagline,
                          "brand_color": p.brand_color,
                          "logo_url": p.logo_url,
                          "featured": p.featured,
                          "demo": p.demo,
                          "special": _todays_special(p)}
                         for p in rows]}


@router.post("/api/board/{key}/partners")
async def upsert_partner(key: str, request: Request):
    _check_key(key)
    body = await request.json()
    import re
    code = re.sub(r"[^a-z0-9-]", "", str(body.get("code", "")).lower().strip().replace(" ", ""))
    name = str(body.get("display_name", "")).strip()
    if not code or not name:
        raise HTTPException(400, "code and display_name required (code: a-z, 0-9, dash)")
    db: Session = SessionLocal()
    try:
        p = db.get(Partner, code)
        if p:
            p.display_name = name
            if body.get("status"):
                p.status = str(body["status"])[:30]
            if body.get("contact") is not None:
                p.contact = str(body["contact"])[:200]
            if body.get("address") is not None:
                p.address = str(body["address"])[:300]
            if body.get("delivery_fee_cents") is not None:
                p.delivery_fee_cents = max(0, int(body["delivery_fee_cents"]))
            for f, cap in (("cuisine", 40), ("tagline", 120),
                           ("brand_color", 9), ("logo_url", 500)):
                if body.get(f) is not None:
                    setattr(p, f, str(body[f]).strip()[:cap])
            if body.get("featured") is not None:
                p.featured = bool(body["featured"])
            if body.get("demo") is not None:
                p.demo = bool(body["demo"])
        else:
            db.add(Partner(code=code, display_name=name,
                           status=str(body.get("status", "pilot"))[:30],
                           contact=str(body.get("contact", ""))[:200],
                           address=str(body.get("address", ""))[:300],
                           delivery_fee_cents=max(0, int(body.get("delivery_fee_cents", 399))),
                           cuisine=str(body.get("cuisine", ""))[:40],
                           tagline=str(body.get("tagline", ""))[:120],
                           brand_color=str(body.get("brand_color", ""))[:9],
                           logo_url=str(body.get("logo_url", ""))[:500],
                           featured=bool(body.get("featured", False)),
                           portal_token=_new_portal_token()))
        db.commit()
    finally:
        db.close()
    return {"ok": True, "code": code, "order_link": f"/order?partner={code}"}


@router.post("/api/board/{key}/partners/{code}/accepting")
async def set_accepting(key: str, code: str, request: Request,
                        background_tasks: BackgroundTasks):
    """Pause/resume ordering for a partner (kitchen slammed, closed, etc)."""
    _check_key(key)
    body = await request.json()
    on = bool(body.get("on", True))
    db: Session = SessionLocal()
    try:
        p = db.get(Partner, code.lower().strip())
        if not p:
            raise HTTPException(404, "Unknown partner")
        was = p.accepting_orders
        p.accepting_orders = on
        name = p.display_name
        db.commit()
    finally:
        db.close()
    if on and not was:
        background_tasks.add_task(_flush_reopen_alerts, code.lower().strip(), name)
    return {"ok": True, "accepting_orders": on}


@router.post("/api/board/{key}/partners/{code}/thanks")
async def set_thanks(key: str, code: str, request: Request):
    """The kitchen's personal thank-you, shown to customers on delivery."""
    _check_key(key)
    body = await request.json()
    note = str(body.get("note", "")).strip()[:300]
    db: Session = SessionLocal()
    try:
        p = db.get(Partner, code.lower().strip())
        if not p:
            raise HTTPException(404, "Unknown partner")
        p.thank_you_note = note
        db.commit()
    finally:
        db.close()
    return {"ok": True}


@router.post("/api/board/{key}/partners/{code}/about")
async def set_about(key: str, code: str, request: Request):
    """The kitchen's short story, shown to customers while they wait for a driver."""
    _check_key(key)
    body = await request.json()
    blurb = str(body.get("blurb", "")).strip()[:280]
    db: Session = SessionLocal()
    try:
        p = db.get(Partner, code.lower().strip())
        if not p:
            raise HTTPException(404, "Unknown partner")
        p.about_blurb = blurb
        db.commit()
    finally:
        db.close()
    return {"ok": True}


@router.post("/api/board/{key}/partners/{code}/hero")
async def set_hero(key: str, code: str, request: Request):
    """The kitchen's hero photo (their own food, their own rights)."""
    _check_key(key)
    body = await request.json()
    url = str(body.get("url", "")).strip()[:500]
    if url and not url.startswith(("https://", "http://")):
        raise HTTPException(400, "url must start with https://")
    db: Session = SessionLocal()
    try:
        p = db.get(Partner, code.lower().strip())
        if not p:
            raise HTTPException(404, "Unknown partner")
        p.hero_url = url
        db.commit()
    finally:
        db.close()
    return {"ok": True}


@router.post("/api/board/{key}/partners/{code}/hero")
async def set_hero(key: str, code: str, request: Request):
    """Restaurant hero photo (16:9). URL only — we never rehost a partner's imagery."""
    _check_key(key)
    body = await request.json()
    url = str(body.get("url", "")).strip()[:500]
    if url and not url.startswith(("https://", "/static/")):
        raise HTTPException(400, "Hero must be an https:// URL")
    db: Session = SessionLocal()
    try:
        p = db.get(Partner, code.lower().strip())
        if not p:
            raise HTTPException(404, "Unknown partner")
        p.hero_url = url
        db.commit()
    finally:
        db.close()
    return {"ok": True}


@router.post("/v0/partners/{code}/notify-me")
async def notify_me(code: str, request: Request):
    """Public: 'text me when they're back.' A paused kitchen keeps the customer."""
    import re as _re
    body = await request.json()
    phone = _re.sub(r"[^0-9+]", "", str(body.get("phone", "")))[:20]
    if len(phone) < 10:
        raise HTTPException(400, "A valid phone number is required")
    db: Session = SessionLocal()
    try:
        p = db.get(Partner, code.lower().strip())
        if not p:
            raise HTTPException(404, "Unknown partner")
        dupe = (db.query(ReopenAlert)
                .filter(ReopenAlert.partner_code == p.code,
                        ReopenAlert.phone == phone,
                        ReopenAlert.notified == False).count())  # noqa: E712
        if not dupe:
            db.add(ReopenAlert(partner_code=p.code, phone=phone))
            db.commit()
    finally:
        db.close()
    return {"ok": True}


async def _flush_reopen_alerts(code: str, display_name: str):
    """When a kitchen resumes, tell everyone who asked. Runs in the background."""
    from . import notify
    db: Session = SessionLocal()
    try:
        waiting = (db.query(ReopenAlert)
                   .filter(ReopenAlert.partner_code == code,
                           ReopenAlert.notified == False).all())  # noqa: E712
        phones = [w.phone for w in waiting]
        for w in waiting:
            w.notified = True
        db.commit()
    finally:
        db.close()
    for ph in phones:
        await notify.send_sms(f"reopen:{code}", ph,
                              f"{display_name} is taking orders again on GateWay. "
                              f"Order now: https://fivestone-nucleus-production.up.railway.app/order?partner={code}")
    return len(phones)


@router.get("/api/board/{key}/partners/{code}/go-live")
def go_live_checklist(key: str, code: str):
    """What is STILL blocking this merchant from being visible to a customer?

    A partner can sit in the registry for weeks, invisible, and nobody knows why.
    This endpoint answers that in one place — it is the difference between
    'Asia Cafe is onboarded' and 'Asia Cafe can actually take an order Monday'.
    """
    from .models import MenuItem
    _check_key(key)
    db: Session = SessionLocal()
    try:
        p = db.get(Partner, code.lower().strip())
        if not p:
            raise HTTPException(404, "Unknown partner")
        items = (db.query(MenuItem)
                 .filter(MenuItem.partner_code == p.code,
                         MenuItem.available.is_(True)).count())
        priced = (db.query(MenuItem)
                  .filter(MenuItem.partner_code == p.code,
                          MenuItem.available.is_(True),
                          MenuItem.price_cents > 0).count())
        checks = [
            {"id": "menu", "ok": items > 0, "blocking": True,
             "label": f"Menu has items ({items})",
             "fix": "Add at least one item — a merchant with no menu is HIDDEN from "
                    "customers entirely, no matter what else is set."},
            {"id": "priced", "ok": items > 0 and priced == items, "blocking": True,
             "label": f"Every item is priced ({priced}/{items})",
             "fix": "A $0.00 item will be ordered — and the driver will collect $0 "
                    "at the door. Price everything before go-live."},
            {"id": "address", "ok": bool(p.address.strip()), "blocking": True,
             "label": "Pickup address set",
             "fix": "Without it the driver has nowhere to go."},
            {"id": "accepting", "ok": bool(p.accepting_orders), "blocking": True,
             "label": "Accepting orders (not paused)",
             "fix": "Resume orders when the kitchen is ready."},
            {"id": "brand", "ok": bool(p.brand_color.strip() and p.cuisine.strip()),
             "blocking": False,
             "label": "Brand set (color + cuisine)",
             "fix": "Without a color and cuisine they get the generic GateWay splash "
                    "and won't appear under any category chip."},
            {"id": "tagline", "ok": bool(p.tagline.strip()), "blocking": False,
             "label": "Tagline written",
             "fix": "One line telling a neighbor why to eat here."},
            {"id": "photo", "ok": bool(p.hero_url.strip()), "blocking": False,
             "label": "Hero photo",
             "fix": "A kitchen with no photo gets the GateWay emblem."},
            {"id": "notdemo", "ok": not p.demo, "blocking": False,
             "label": "Not a PREVIEW placeholder",
             "fix": "Clear the demo flag once this is a real signed merchant."},
        ]
        blocking = [c for c in checks if c["blocking"] and not c["ok"]]
        return {
            "code": p.code,
            "display_name": p.display_name,
            "visible_to_customers": len(blocking) == 0,
            "blocking": [c["id"] for c in blocking],
            "checks": checks,
            "order_link": f"/order?partner={p.code}",
            "kitchen_link": f"/kitchen/{p.portal_token}",
        }
    finally:
        db.close()
