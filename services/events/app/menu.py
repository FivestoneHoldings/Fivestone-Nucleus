"""Menus v0 — per-partner catalogs powering DoorDash-style ordering.
Public read for the order form; board-key writes for management.
Seeded menus are DRAFTS grounded in each restaurant's published menus;
prices are confirmed/corrected by the partner via the board editor.
"""
import os
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import MenuItem, Partner

router = APIRouter()


def _check_key(key: str):
    admin = os.environ.get("ADMIN_KEY", "")
    if not admin or key != admin:
        raise HTTPException(403, "Bad board key")


def _grouped(items):
    cats: dict = {}
    for i in items:
        cats.setdefault(i.category, []).append({
            "id": i.id, "name": i.name, "description": i.description,
            "price_cents": i.price_cents, "available": i.available})
    return [{"name": c, "items": v} for c, v in cats.items()]


@router.get("/v0/partners/{code}/menu")
def public_menu(code: str):
    db: Session = SessionLocal()
    try:
        rows = (db.query(MenuItem)
                .filter(MenuItem.partner_code == code.lower().strip(),
                        MenuItem.available.is_(True))
                .order_by(MenuItem.sort, MenuItem.name).all())
    finally:
        db.close()
    if not rows:
        raise HTTPException(404, "No menu for this partner")
    return {"partner": code.lower().strip(), "categories": _grouped(rows)}


@router.get("/api/board/{key}/partners/{code}/menu")
def admin_menu(key: str, code: str):
    _check_key(key)
    db: Session = SessionLocal()
    try:
        rows = (db.query(MenuItem).filter(MenuItem.partner_code == code.lower().strip())
                .order_by(MenuItem.sort, MenuItem.name).all())
    finally:
        db.close()
    return {"partner": code.lower().strip(), "categories": _grouped(rows)}


@router.post("/api/board/{key}/partners/{code}/menu")
async def upsert_item(key: str, code: str, request: Request):
    _check_key(key)
    body = await request.json()
    name = str(body.get("name", "")).strip()
    if not name and not body.get("id"):
        raise HTTPException(400, "name required")
    db: Session = SessionLocal()
    try:
        item = db.get(MenuItem, body["id"]) if body.get("id") else None
        if item is None:
            item = MenuItem(partner_code=code.lower().strip(), name=name)
            db.add(item)
        if name:
            item.name = name
        for field, caster in (("category", str), ("description", str)):
            if body.get(field) is not None:
                setattr(item, field, caster(body[field])[:400])
        if body.get("price_cents") is not None:
            item.price_cents = max(0, int(body["price_cents"]))
        if body.get("available") is not None:
            item.available = bool(body["available"])
        db.commit()
        return {"ok": True, "id": item.id}
    finally:
        db.close()


@router.delete("/api/board/{key}/menu-items/{item_id}")
def delete_item(key: str, item_id: str):
    _check_key(key)
    db: Session = SessionLocal()
    try:
        item = db.get(MenuItem, item_id)
        if not item:
            raise HTTPException(404, "No such item")
        db.delete(item)
        db.commit()
    finally:
        db.close()
    return {"ok": True}


# ---------- SEEDS (drafts — grounded in published menus, partner-editable) ----------

SEED_PARTNERS = [("burgerboys", "Burger Boys & Friends BBQ"),
                 ("stephens", "Stephen's Pizzeria")]

SEED_MENUS = {
    "burgerboys": [
        ("Burgers — ½ lb fresh 80/20, FREE fries", [
            ("Classic Burger", "Half-pound fresh beef, dressed your way, free fries", 850),
            ("Kobe Burger", "Sauteed onions & green peppers dipped in steak sauce, tomato, lettuce", 950),
            ("Lil Dom Burger", "Mayo, ketchup, jalapenos, pepper jack, tomato, lettuce", 950),
            ("Lil Dre's Burger", "Loaded with everything in the garden, cheese, 6 strips of bacon", 1050),
            ("Fire Burger", "Habanero & cayenne sauces, jalapenos — for the brave", 1150),
        ]),
        ("BBQ", [
            ("Pulled Pork Sandwich", "Slow-smoked pork, house BBQ sauce, on a bun", 899),
            ("Smoked Chicken Plate", "Smoked BBQ chicken with 2 sides", 1199),
            ("Rib Plate", "Slow-smoked ribs with 2 sides", 1399),
        ]),
        ("Wings & More", [
            ("Chicken Wings (8)", "Fried or smoked, sauced", 999),
            ("Fish Sandwich", "Crispy fried fish, dressed", 899),
        ]),
        ("Sides", [
            ("Mac & Cheese", "", 349), ("Collard Greens", "", 349),
            ("Candied Yams", "", 349), ("Potato Salad", "", 349),
            ("Rice & Gravy", "", 349), ("Extra Fries", "More of the free fries", 100),
        ]),
        ("Desserts", [
            ("Sweet Potato Pie", "", 399), ("Cheesecake Slice", "", 449),
        ]),
    ],
    "stephens": [
        ("Appetizers", [
            ("Momma Mia Meatballs", "3 homemade meatballs in pasta sauce, mozzarella", 549),
            ("Garlic & Cheese Breadsticks", "14\" crust, garlic butter, cheese & herbs, marinara", 649),
            ("Boneless Wings (8)", "All-white meat; hot, hotter, honey BBQ, or BBQ", 699),
        ]),
        ("Pizzas — NY style, hand-tossed", [
            ("Cheese Pizza 10\"", "Stephen's traditional red, mozzarella", 999),
            ("Cheese Pizza 16\"", "Stephen's traditional red, mozzarella", 1599),
            ("Pepperoni Pizza 10\"", "The fan favorite", 1149),
            ("Pepperoni Pizza 16\"", "The fan favorite", 1799),
            ("Two-Topping Pizza 16\"", "Mozzarella plus your choice of two toppings", 1899),
            ("Supreme Pizza 16\"", "Sausage, pepperoni, onions, green peppers", 1999),
        ]),
        ("Calzones", [
            ("Cheese Calzone", "Stuffed with mozzarella, side of marinara", 999),
            ("Sausage & Mushroom Calzone", "House Italian sausage, mushrooms", 1199),
        ]),
        ("Hoagies", [
            ("Philly Cheesesteak", "Seasoned steak, cooked onions, mozzarella, lettuce, mayo", 999),
            ("Buffalo Chicken Hoagie", "Buffalo-seasoned chicken, blue cheese spread, mozzarella", 949),
        ]),
        ("Salads & Pasta", [
            ("Greek Salad", "Crisp greens, fresh vegetables, tangy dressing", 849),
            ("Spaghetti & Meatballs", "Stephen's marinara, grated cheese, cheese toast", 1049),
        ]),
        ("Desserts", [
            ("Tiramisu", "Made fresh", 599),
        ]),
    ],
}


def seed_menus():
    db: Session = SessionLocal()
    try:
        for code, name in SEED_PARTNERS:
            if db.get(Partner, code) is None:
                db.add(Partner(code=code, display_name=name, status="pilot"))
        db.commit()
        for code, cats in SEED_MENUS.items():
            if db.query(MenuItem).filter(MenuItem.partner_code == code).count() == 0:
                sort = 0
                for cat, items in cats:
                    for name, desc, cents in items:
                        db.add(MenuItem(partner_code=code, category=cat, name=name,
                                        description=desc, price_cents=cents, sort=sort))
                        sort += 1
                db.commit()
    finally:
        db.close()
