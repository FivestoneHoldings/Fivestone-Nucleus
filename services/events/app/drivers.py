"""Drivers are the face of GateWay, not routing tokens.

This module gives a driver a real profile — a name customers see, an avatar or
a photo, the car that's pulling up, and a line about who they are — and it lets
a customer see *who* is bringing their order, the way Uber shows you a face and
a plate before the car arrives.

Two audiences, two surfaces:
  * the DRIVER edits their own card from the hub (GET/POST /api/driver/{token}/profile)
  * the CUSTOMER sees a read-only card for the driver on their order
    (GET /v0/order/{order_id}/driver) — only ever the safe-to-share fields.

The profile lives in the local DriverProfile table (keyed by driver_id), so it
survives independently of Airtable's operational record and never exposes a
driver's phone or token to a customer.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.orm import Session

from . import airtable_client as at
from .db import SessionLocal
from .models import DriverProfile

router = APIRouter()

# Same vetted set the customer avatars draw from — no free-text emoji, no XSS
# surface. A driver picks a face or uploads a photo; nothing else renders.
AVATAR_ALLOWLIST = set(
    "😀😃😄😁😊🙂😎🤠🥳😇🧑👩👨👵👴👱🧔🐶🐱🦊🐻🐼🐨🦁🐯🦄"
    "🌟⭐️🔥💙💚💛🧡💜🤍🖤🚗🚙🛻🏎️🛵🚲🧢🕶️🍕🌮🌸"
)

_SAFE_STR = 300


def _clean(s, n=_SAFE_STR):
    # length-cap AND strip angle brackets: the customer card escapes on render,
    # but stripping here means stored data is clean even if a future surface
    # forgets to escape. Belt and suspenders on the one field a stranger sees.
    v = ("" if s is None else str(s))[:n].strip()
    return v.replace("<", "").replace(">", "")


def _profile_dict(p: DriverProfile) -> dict:
    """Only ever the fields a stranger is allowed to see. No phone. No token."""
    return {
        "driver_id": p.driver_id,
        "display_name": p.display_name,
        "avatar": p.avatar,
        "photo_url": p.photo_url,
        "vehicle": p.vehicle,
        "vehicle_color": p.vehicle_color,
        "bio": p.bio,
    }


def get_or_make(db: Session, driver_id: str, default_name: str = "") -> DriverProfile:
    p = db.get(DriverProfile, driver_id)
    if p is None:
        p = DriverProfile(driver_id=driver_id, display_name=default_name or "")
        db.add(p)
        db.commit()
        db.refresh(p)
    return p


# ---------------------------------------------------------------- DRIVER SELF

@router.get("/api/driver/{day_token}/profile")
async def read_own_profile(day_token: str):
    """The driver's own editable card. Resolves their token -> driver_id, then
    returns the stored profile (creating a blank one seeded with their name the
    first time they open it)."""
    from .dispatch import _driver_by_token
    drv = await _driver_by_token(day_token)
    did = drv["fields"].get("driver_id") or drv["id"]
    name = drv["fields"].get("display_name", "")
    db: Session = SessionLocal()
    try:
        p = get_or_make(db, did, name)
        d = _profile_dict(p)
    finally:
        db.close()
    # the driver may also see their own first-seen date; customers never do
    return d


@router.post("/api/driver/{day_token}/profile")
async def write_own_profile(day_token: str, request: Request):
    from .dispatch import _driver_by_token
    drv = await _driver_by_token(day_token)
    did = drv["fields"].get("driver_id") or drv["id"]
    name = drv["fields"].get("display_name", "")
    body = await request.json()
    db: Session = SessionLocal()
    try:
        p = get_or_make(db, did, name)
        if "avatar" in body:
            av = _clean(body.get("avatar"), 10)
            p.avatar = av if av in AVATAR_ALLOWLIST else ""
        if "photo_url" in body:
            # only accept our own uploaded paths — never an arbitrary URL
            ph = _clean(body.get("photo_url"), 500)
            p.photo_url = ph if ph.startswith("/static/") else ""
        if "vehicle" in body:
            p.vehicle = _clean(body.get("vehicle"), 120)
        if "vehicle_color" in body:
            p.vehicle_color = _clean(body.get("vehicle_color"), 40)
        if "bio" in body:
            p.bio = _clean(body.get("bio"), 300)
        db.commit()
        d = _profile_dict(p)
    finally:
        db.close()
    return d


# ------------------------------------------------------------- CUSTOMER VIEW

@router.get("/v0/order/{order_id}/driver")
async def driver_for_order(order_id: str):
    """Customer-facing: who's bringing THIS order. Returns a read-only card once
    a driver is assigned, or {assigned:false} before that. Never leaks phone,
    token, or location — only the face, the name, the car, the bio."""
    if not at.configured():
        return {"assigned": False}
    from .dispatch import _fq, _cget, _cput
    # resolve order -> driver record id. Any lookup hiccup degrades to "no driver
    # card yet" — a customer's tracking page must never break because the driver
    # lookup failed.
    try:
        recs = await at.list_records(
            at.ORDERS, formula=f"{{order_id}}='{_fq(order_id)}'", max_records=1)
    except Exception:
        return {"assigned": False}
    if not recs:
        return {"assigned": False}
    f = recs[0]["fields"]
    status = f.get("status", "")
    drv_link = f.get("driver") or []
    if status not in ("assigned", "in_transit") or not drv_link:
        return {"assigned": False, "status": status}
    dref = drv_link[0]
    # map Airtable record ref -> our driver_id (cached; it never changes)
    did = _cget(f"did:{dref}")
    if did is None:
        try:
            dr = await at.list_records(
                at.DRIVERS, formula=f"RECORD_ID()='{_fq(dref)}'", max_records=1)
        except Exception:
            return {"assigned": False}
        if not dr:
            return {"assigned": False}
        did = dr[0]["fields"].get("driver_id") or dref
        # if there's no local profile yet, seed a minimal one from Airtable so
        # the customer at least sees a name + any avatar/vehicle already set
        _fallback = {
            "display_name": dr[0]["fields"].get("display_name", "Your driver"),
            "vehicle": dr[0]["fields"].get("vehicle", ""),
        }
        _cput(f"did:{dref}", did, 3600)
        _cput(f"dfb:{dref}", _fallback, 3600)
    fb = _cget(f"dfb:{dref}") or {}
    db: Session = SessionLocal()
    try:
        p = db.get(DriverProfile, did)
        if p is None:
            card = {
                "display_name": (fb.get("display_name") or "Your driver"),
                "avatar": "", "photo_url": "",
                "vehicle": fb.get("vehicle", ""), "vehicle_color": "", "bio": "",
            }
        else:
            card = _profile_dict(p)
            if not card["display_name"]:
                card["display_name"] = fb.get("display_name") or "Your driver"
            if not card["vehicle"]:
                card["vehicle"] = fb.get("vehicle", "")
    finally:
        db.close()
    card["assigned"] = True
    card["status"] = status
    # customers see first name only — friendly, and a little safer for the driver
    card["first_name"] = (card["display_name"] or "Your driver").split(" ")[0]
    return card


def seed_driver_profiles():
    """Give the pilot drivers real cards so the customer view isn't empty on day
    one. Idempotent — only fills a profile that doesn't exist yet, never
    overwrites something a driver has edited."""
    seeds = [
        # driver_id,      name,          avatar, vehicle,               color,     bio
        ("DRV-JORDAN", "Jordan Ellis", "😎", "Honda Civic",         "Silver",
         "Knoxville born and raised. I'll text when I'm close and always double-check the order before I leave the kitchen."),
        ("DRV-MAYA",   "Maya Torres",  "🚗", "Toyota RAV4",         "Blue",
         "Five years driving these roads. Contactless or hand-to-you — whatever you set, that's what you get."),
        ("DRV-SAM",    "Sam Whitfield", "🧢", "Ford Escape",         "Black",
         "New to the GateWay crew, not new to Knoxville. Ask me for the scenic drop-off."),
    ]
    db: Session = SessionLocal()
    try:
        for did, name, avatar, vehicle, color, bio in seeds:
            if db.get(DriverProfile, did) is None:
                db.add(DriverProfile(
                    driver_id=did, display_name=name, avatar=avatar,
                    vehicle=vehicle, vehicle_color=color, bio=bio))
        db.commit()
    finally:
        db.close()
