"""ITEM OPTIONS (v1.4) — 'Choose your protein', 'Spice level', 'Add a side'.

Researched from the pilots' own real menus: Asia Cafe prices most entrees with a
'+' (Chicken $13.05+, Steak $14.05+, Shrimp $15.05+) because the protein is a
REQUIRED CHOICE that changes the price. Before this, our menu only let a customer
pick a quantity — it silently dropped the thing the restaurant's own menu treats
as the whole point of the item.

MONEY RULE, same as promos: the client renders options and previews a total, but
the SERVER is the only authority on what an order actually costs. A tampered
client claiming "Filet Mignon, $0 upcharge" must be rejected the same way a
tampered $500 discount was rejected in v1.1 — see validate_selected_options().
"""
import json
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import Event, MenuItem, OptionChoice, OptionGroup, Partner

router = APIRouter()


def _check_key(key: str):
    import os
    admin = os.environ.get("ADMIN_KEY", "")
    if not admin or not secrets.compare_digest(str(key), admin):
        raise HTTPException(403, "Bad board key")


def _partner_by_token(token: str) -> Partner:
    from .kitchen import _partner_by_token as _lookup
    return _lookup(token)


# ---------- read: attach options to a menu payload ----------

def options_for_items(db: Session, item_ids: list) -> dict:
    """item_id -> [{group}, ...] — batched so a 40-item menu is one query, not 40."""
    if not item_ids:
        return {}
    groups = (db.query(OptionGroup)
              .filter(OptionGroup.item_id.in_(item_ids))
              .order_by(OptionGroup.sort).all())
    if not groups:
        return {}
    gids = [g.id for g in groups]
    choices = (db.query(OptionChoice)
               .filter(OptionChoice.group_id.in_(gids), OptionChoice.available.is_(True))
               .order_by(OptionChoice.sort).all())
    by_group: dict = {}
    for c in choices:
        by_group.setdefault(c.group_id, []).append({
            "id": c.id, "name": c.name, "price_delta_cents": c.price_delta_cents,
            "is_default": c.is_default})
    out: dict = {}
    for g in groups:
        out.setdefault(g.item_id, []).append({
            "id": g.id, "name": g.name, "min_select": g.min_select,
            "max_select": g.max_select, "choices": by_group.get(g.id, [])})
    return out


# ---------- board: manage a menu item's option groups ----------

@router.get("/api/board/{key}/menu-items/{item_id}/options")
def board_get_options(key: str, item_id: str):
    _check_key(key)
    db: Session = SessionLocal()
    try:
        return {"groups": options_for_items(db, [item_id]).get(item_id, [])}
    finally:
        db.close()


@router.post("/api/board/{key}/menu-items/{item_id}/options")
async def board_add_group(key: str, item_id: str, request: Request):
    """Create one option group with its choices in a single call — the board UI
    builds the whole 'Choose your protein: Chicken / Steak +$1 / Shrimp +$2'
    picker in one round trip rather than five."""
    _check_key(key)
    body = await request.json()
    db: Session = SessionLocal()
    try:
        item = db.get(MenuItem, item_id)
        if not item:
            raise HTTPException(404, "No such item")
        name = str(body.get("name", "")).strip()[:80]
        if not name:
            raise HTTPException(422, "Give the option group a name, e.g. 'Choose your protein'")
        min_select = max(0, int(body.get("min_select", 0)))
        max_select = max(1, int(body.get("max_select", 1)))
        if min_select > max_select:
            raise HTTPException(422, "min_select cannot exceed max_select")
        g = OptionGroup(item_id=item_id, name=name, min_select=min_select,
                        max_select=max_select, sort=int(body.get("sort", 0)))
        db.add(g)
        db.flush()
        for i, ch in enumerate(body.get("choices", [])):
            delta = int(ch.get("price_delta_cents", 0))
            if delta < 0:
                raise HTTPException(422, "An option can only ADD cost, never subtract")
            db.add(OptionChoice(group_id=g.id, name=str(ch.get("name", ""))[:80],
                                price_delta_cents=delta,
                                is_default=bool(ch.get("is_default", False)), sort=i))
        db.commit()
        return {"ok": True, "group_id": g.id}
    finally:
        db.close()


@router.delete("/api/board/{key}/option-groups/{group_id}")
def board_delete_group(key: str, group_id: str):
    _check_key(key)
    db: Session = SessionLocal()
    try:
        db.query(OptionChoice).filter(OptionChoice.group_id == group_id).delete()
        db.query(OptionGroup).filter(OptionGroup.id == group_id).delete()
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@router.patch("/api/board/{key}/option-choices/{choice_id}")
async def board_toggle_choice(key: str, choice_id: str, request: Request):
    _check_key(key)
    body = await request.json()
    db: Session = SessionLocal()
    try:
        c = db.get(OptionChoice, choice_id)
        if not c:
            raise HTTPException(404, "No such choice")
        if "available" in body:
            c.available = bool(body["available"])
        if "price_delta_cents" in body:
            delta = int(body["price_delta_cents"])
            if delta < 0:
                raise HTTPException(422, "An option can only ADD cost, never subtract")
            c.price_delta_cents = delta
        db.commit()
        return {"ok": True}
    finally:
        db.close()


# ---------- kitchen: quick 86 of a single choice (e.g. "we're out of shrimp") ----------

@router.post("/api/kitchen/{token}/option-choices/{choice_id}/86")
async def kitchen_toggle_choice(token: str, choice_id: str, request: Request):
    p = _partner_by_token(token)
    body = await request.json()
    db: Session = SessionLocal()
    try:
        c = db.get(OptionChoice, choice_id)
        if not c:
            raise HTTPException(404, "No such choice")
        g = db.get(OptionGroup, c.group_id)
        item = db.get(MenuItem, g.item_id) if g else None
        if not item or item.partner_code != p.code:
            raise HTTPException(403, "That option belongs to a different kitchen")
        c.available = bool(body.get("available", not c.available))
        db.commit()
        return {"ok": True, "available": c.available, "name": c.name}
    finally:
        db.close()


# ---------- SERVER-AUTHORITATIVE VALIDATION (called from intake.py) ----------

def validate_selected_options(db: Session, item_id: str, selected_choice_ids: list) -> int:
    """Re-derive the option upcharge from the DATABASE, ignoring whatever price
    the client claims. Returns total price_delta_cents to add to the item's base
    price. Raises HTTPException if a required group was left unanswered or a
    max_select was exceeded — the same posture as promo_discount_cents in v1.1:
    the client renders and previews, the server decides what's true.
    """
    groups = db.query(OptionGroup).filter(OptionGroup.item_id == item_id).all()
    if not groups:
        return 0
    selected = set(selected_choice_ids or [])
    delta = 0
    for g in groups:
        choices = (db.query(OptionChoice)
                   .filter(OptionChoice.group_id == g.id, OptionChoice.available.is_(True)).all())
        valid_ids = {c.id for c in choices}
        picked = selected & valid_ids
        if len(picked) < g.min_select:
            raise HTTPException(422, f"'{g.name}' needs at least {g.min_select} choice"
                                     f"{'s' if g.min_select != 1 else ''}.")
        if len(picked) > g.max_select:
            raise HTTPException(422, f"'{g.name}' allows at most {g.max_select} choice"
                                     f"{'s' if g.max_select != 1 else ''}.")
        for c in choices:
            if c.id in picked:
                delta += c.price_delta_cents
    return delta
