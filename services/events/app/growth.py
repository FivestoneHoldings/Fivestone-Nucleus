"""Growth & care — leads (drive/partner with us), support tickets, promo codes,
brand-column migration, and demo merchants that fill out the marketplace until
real ones take their place.

Money rule: the SERVER is the only authority on what a promo is worth
(app/intake.py re-validates at order time). The client only previews.
"""
import json
import os
import re
import uuid
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from .db import SessionLocal, engine
from .models import Event, Lead, Partner, PromoCode, SupportTicket

router = APIRouter()


# ---------- abuse guard ----------
# The founder's inbox is a real inbox. A bot that can post 10,000 fake merchant
# leads doesn't just make noise — it BURIES the one real message from a restaurant
# owner who actually wants in. Rate-limiting this is protecting a relationship,
# not just a database.
_LEAD_HITS: dict = {}
_PROMO_HITS: dict = {}


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else
            (request.client.host if request.client else "unknown"))


def _throttled(bucket: dict, ip: str, limit: int, window_s: int = 60) -> bool:
    import time
    now = time.time()
    hits = [t for t in bucket.get(ip, []) if now - t < window_s]
    hits.append(now)
    bucket[ip] = hits
    if len(bucket) > 5000:      # bound memory
        bucket.clear()
    return len(hits) > limit


# ---------- idempotent column migration (create_all won't ALTER) ----------

_PARTNER_COLS = [
    ("cuisine", "VARCHAR(40) NOT NULL DEFAULT ''"),
    ("tagline", "VARCHAR(120) NOT NULL DEFAULT ''"),
    ("brand_color", "VARCHAR(9) NOT NULL DEFAULT ''"),
    ("logo_url", "VARCHAR(500) NOT NULL DEFAULT ''"),
    ("featured", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("demo", "BOOLEAN NOT NULL DEFAULT FALSE"),
]


def migrate_brand_columns():
    """ALTER partners to add brand columns, once, on both SQLite and Postgres."""
    with engine.connect() as conn:
        for col, ddl in _PARTNER_COLS:
            try:
                conn.execute(text(f"ALTER TABLE partners ADD COLUMN {col} {ddl}"))
                conn.commit()
            except Exception:
                conn.rollback()  # already exists — fine


# ---------- brand + demo-merchant seeds ----------

# Real pilots get their brand identity; demo merchants fill the food court so the
# marketplace reads as a full picture. Demo rows carry demo=True and a PREVIEW
# badge in the UI — they are swapped out as real merchants sign in each category.
BRAND_SEED = {
    "burgerboys":      dict(cuisine="Burgers",   brand_color="#b3202c", tagline="Half-pound burgers · home of the FREE fries", featured=True),
    "friendsbbq":      dict(cuisine="BBQ",       brand_color="#5c3a21", tagline="Slow-smoked meats & family packs", featured=True),
    "stephens":        dict(cuisine="Pizza",     brand_color="#1d6f42", tagline="NY-style pies, made from scratch", featured=True),
    "asiacafe":        dict(cuisine="Asian",     brand_color="#c0392b", tagline="Knoxville's neighborhood Asian kitchen"),
    "asiacafexpress":  dict(cuisine="Asian",     brand_color="#c0392b", tagline="Asia Cafe, to go — fast"),
}

DEMO_MERCHANTS = [
    ("riseshine",  "Rise & Shine Diner",    "Breakfast", "#e8a13a", "Biscuits, gravy & sunrise plates till 2pm",
     "1200 Demo Ave, Maryville, TN"),
    ("summitcof",  "Summit Coffee Co.",     "Coffee",    "#6f4e37", "Small-batch roasts & morning pastries",
     "88 Demo Ridge Rd, Maryville, TN"),
    ("elcamino",   "El Camino Taqueria",    "Mexican",   "#d35400", "Street tacos, burritos & fresh salsa verde",
     "410 Demo Blvd, Alcoa, TN"),
    ("magnolia",   "Sweet Magnolia Bakery", "Desserts",  "#b56576", "Layer cakes, cookies & Southern pies",
     "77 Demo Lane, Knoxville, TN"),
    ("gardengrn",  "Garden Greens",         "Healthy",   "#2e7d32", "Big salads, grain bowls & fresh-pressed juice",
     "23 Demo Circle, Knoxville, TN"),
]

DEMO_MENUS = {
    "riseshine": [("Morning plates", [
        ("Sunrise Stack", "3 buttermilk pancakes, maple syrup", 799),
        ("Biscuits & Gravy", "2 scratch biscuits, sausage gravy", 749),
        ("Farmhouse Breakfast", "2 eggs, bacon, hash browns, toast", 999),
    ])],
    "summitcof": [("Drinks & pastries", [
        ("Summit Latte", "Double shot, house syrup", 525),
        ("Cold Brew (16 oz)", "Steeped 18 hours", 450),
        ("Butter Croissant", "Baked every morning", 375),
    ])],
    "elcamino": [("Tacos & more", [
        ("Street Tacos (3)", "Carne asada, onion, cilantro, lime", 899),
        ("Burrito Grande", "Rice, beans, cheese, choice of meat", 1049),
        ("Chips & Salsa Verde", "Made fresh daily", 449),
    ])],
    "magnolia": [("Sweets", [
        ("Slice of Caramel Cake", "Old-fashioned Southern layer cake", 599),
        ("Half-dozen Cookies", "Baker's choice", 799),
        ("Sweet Tea Pie", "Whole pie, serves 8", 2199),
    ])],
    "gardengrn": [("Bowls & juice", [
        ("Harvest Bowl", "Quinoa, roasted veg, tahini", 1149),
        ("Classic Cobb", "Greens, chicken, egg, avocado", 1099),
        ("Green Machine Juice", "Kale, apple, ginger, lemon", 699),
    ])],
}


def seed_brands_and_demos():
    """Apply brand identity to real pilots; create demo merchants + tiny menus."""
    from .models import MenuItem
    db: Session = SessionLocal()
    try:
        for code, brand in BRAND_SEED.items():
            p = db.get(Partner, code)
            if p:
                if not p.cuisine:
                    p.cuisine = brand.get("cuisine", "")
                if not p.brand_color:
                    p.brand_color = brand.get("brand_color", "")
                if not p.tagline:
                    p.tagline = brand.get("tagline", "")
                if brand.get("featured") and not p.featured:
                    p.featured = True
        for code, name, cuisine, color, tagline, addr in DEMO_MERCHANTS:
            if not db.get(Partner, code):
                db.add(Partner(code=code, display_name=name, status="pilot",
                               cuisine=cuisine, brand_color=color, tagline=tagline,
                               address=addr, demo=True,
                               portal_token="kt-" + secrets.token_hex(5)))
        db.commit()
        for code, sections in DEMO_MENUS.items():
            has = db.query(MenuItem).filter(MenuItem.partner_code == code).count()
            if has:
                continue
            for section, items in sections:
                for name, desc, cents in items:
                    db.add(MenuItem(partner_code=code, category=section, name=name,
                                    description=desc, price_cents=cents, available=True))
        db.commit()
    finally:
        db.close()


# ---------- promo seeds + validation ----------

PROMO_SEED = [
    ("WELCOME10", "percent", 10, "10% off your first GateWay order"),
    ("LOYAL10",   "percent", 10, "Loyalty reward — every 10th order, on us (10% off)"),
]


def seed_promos():
    db: Session = SessionLocal()
    try:
        for code, kind, value, desc in PROMO_SEED:
            if not db.get(PromoCode, code):
                db.add(PromoCode(code=code, kind=kind, value=value, description=desc))
        db.commit()
    finally:
        db.close()


_REFERRAL_RE = re.compile(r"^GW-[A-Z0-9]{4,8}$")


def promo_discount_cents(code: str, partner_code: str, subtotal_cents: int, db: Session):
    """Single source of truth for what a code is worth. Returns
    (discount_cents, description) or (0, reason_string_starting_with_'!')."""
    code = (code or "").strip().upper()[:30]
    if not code or subtotal_cents <= 0:
        return 0, "!no_code"
    if _REFERRAL_RE.match(code):
        # Friend-referral: 20% off, first-order spirit. Usage is logged so the
        # referrer's credit can be honored (see referral.used events).
        return min(subtotal_cents * 20 // 100, 1500), "Referral — 20% off (up to $15)"
    p = db.get(PromoCode, code)
    if not p or not p.active:
        return 0, "!invalid"
    if p.max_uses and p.uses >= p.max_uses:
        return 0, "!exhausted"
    if p.partner_code and p.partner_code != (partner_code or ""):
        return 0, "!wrong_merchant"
    if p.kind == "cents":
        return min(p.value, subtotal_cents), p.description
    return subtotal_cents * max(0, min(p.value, 100)) // 100, p.description


@router.get("/v0/promo/{code}")
def check_promo(request: Request, code: str, partner: str = "", subtotal_cents: int = 0):
    """Client-side PREVIEW of a promo. The same math re-runs at intake."""
    # 20/min: enough for a customer fumbling a code, far too slow to brute-force
    # the referral-code space.
    if _throttled(_PROMO_HITS, _client_ip(request), 20):
        raise HTTPException(429, "Too many code attempts — wait a minute and try again.")
    db: Session = SessionLocal()
    try:
        disc, desc = promo_discount_cents(code, partner, max(0, subtotal_cents), db)
        if disc <= 0:
            return {"valid": False}
        return {"valid": True, "discount_cents": disc, "description": desc}
    finally:
        db.close()


# ---------- leads + support ----------

class LeadIn(BaseModel):
    kind: str = Field(pattern="^(driver|merchant)$")
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(default="", max_length=40)
    email: str = Field(default="", max_length=160)
    message: str = Field(default="", max_length=1000)


@router.post("/v0/leads", status_code=201)
def create_lead(request: Request, body: LeadIn):
    if _throttled(_LEAD_HITS, _client_ip(request), 5):
        raise HTTPException(429, "We've got your message — give us a minute to read it.")
    if not body.phone.strip() and not body.email.strip():
        raise HTTPException(422, "Leave a phone number or an email so we can reach you.")
    db: Session = SessionLocal()
    try:
        lead = Lead(id=str(uuid.uuid4()), kind=body.kind, name=body.name.strip(),
                    phone=body.phone.strip(), email=body.email.strip(),
                    message=body.message.strip())
        db.add(lead)
        db.add(Event(event_type=f"lead.{body.kind}", entity_ref=lead.id,
                     tenant="gateway", actor="public:web",
                     payload=json.dumps({"name": lead.name, "phone": lead.phone,
                                         "email": lead.email})))
        db.commit()
        return {"ok": True, "id": lead.id}
    finally:
        db.close()


class SupportIn(BaseModel):
    name: str = Field(default="", max_length=120)
    phone: str = Field(default="", max_length=40)
    order_id: str = Field(default="", max_length=40)
    message: str = Field(min_length=3, max_length=1000)


@router.post("/v0/support", status_code=201)
def create_ticket(request: Request, body: SupportIn):
    if _throttled(_LEAD_HITS, _client_ip(request), 5):
        raise HTTPException(429, "We've got your message — give us a minute to read it.")
    db: Session = SessionLocal()
    try:
        t = SupportTicket(id=str(uuid.uuid4()), name=body.name.strip(),
                          phone=body.phone.strip(),
                          order_id=body.order_id.strip().upper(),
                          message=body.message.strip())
        db.add(t)
        db.add(Event(event_type="support.ticket", entity_ref=t.id,
                     tenant="gateway", actor="public:web",
                     payload=json.dumps({"name": t.name, "order_id": t.order_id,
                                         "message": t.message[:200]})))
        db.commit()
        return {"ok": True, "id": t.id}
    finally:
        db.close()


def _check_key(key: str):
    admin = os.environ.get("ADMIN_KEY", "")
    if not admin or not secrets.compare_digest(str(key), admin):
        raise HTTPException(403, "Bad board key")


@router.get("/v0/leads")
def list_leads(key: str):
    _check_key(key)
    db: Session = SessionLocal()
    try:
        rows = db.query(Lead).order_by(Lead.created_at.desc()).limit(200).all()
        return {"leads": [dict(id=l.id, kind=l.kind, name=l.name, phone=l.phone,
                               email=l.email, message=l.message, status=l.status,
                               created_at=l.created_at.isoformat()) for l in rows]}
    finally:
        db.close()


@router.get("/v0/support-tickets")
def list_tickets(key: str):
    _check_key(key)
    db: Session = SessionLocal()
    try:
        rows = db.query(SupportTicket).order_by(SupportTicket.created_at.desc()).limit(200).all()
        return {"tickets": [dict(id=t.id, name=t.name, phone=t.phone, order_id=t.order_id,
                                 message=t.message, status=t.status,
                                 created_at=t.created_at.isoformat()) for t in rows]}
    finally:
        db.close()
