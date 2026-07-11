"""Identity v0 — partner/tenant registry (staged in the monolith per ADR-008).
Public: name lookup for co-branding. Key-gated: full list + create/update.
"""
import os
import secrets
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import Partner

router = APIRouter()

SEED = [("asiacafe", "Asia Cafe"), ("asiacafexpress", "Asia Cafe Xpress")]


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
                out.append({"code": p.code, "display_name": p.display_name})
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
            "accepting_orders": p.accepting_orders}


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
                          "thank_you_note": p.thank_you_note}
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
        else:
            db.add(Partner(code=code, display_name=name,
                           status=str(body.get("status", "pilot"))[:30],
                           contact=str(body.get("contact", ""))[:200],
                           address=str(body.get("address", ""))[:300],
                           delivery_fee_cents=max(0, int(body.get("delivery_fee_cents", 399)))))
        db.commit()
    finally:
        db.close()
    return {"ok": True, "code": code, "order_link": f"/order?partner={code}"}


@router.post("/api/board/{key}/partners/{code}/accepting")
async def set_accepting(key: str, code: str, request: Request):
    """Pause/resume ordering for a partner (kitchen slammed, closed, etc)."""
    _check_key(key)
    body = await request.json()
    on = bool(body.get("on", True))
    db: Session = SessionLocal()
    try:
        p = db.get(Partner, code.lower().strip())
        if not p:
            raise HTTPException(404, "Unknown partner")
        p.accepting_orders = on
        db.commit()
    finally:
        db.close()
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
