"""Menus v0 — per-partner catalogs powering DoorDash-style ordering.
Public read for the order form; board-key writes for management.
Seeded menus are DRAFTS grounded in each restaurant's published menus;
prices are confirmed/corrected by the partner via the board editor.
"""
import os
import secrets
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import MenuItem, Partner, Event

router = APIRouter()


def _check_key(key: str):
    admin = os.environ.get("ADMIN_KEY", "")
    if not admin or not secrets.compare_digest(str(key), admin):
        raise HTTPException(403, "Bad board key")


def _grouped(items):
    cats: dict = {}
    for i in items:
        cats.setdefault(i.category, []).append({
            "id": i.id, "name": i.name, "description": i.description,
            "price_cents": i.price_cents, "available": i.available,
            "image_url": i.image_url})
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
        if body.get("image_url") is not None:
            url = str(body["image_url"]).strip()[:500]
            if url and not url.startswith(("https://", "http://")):
                raise HTTPException(400, "image_url must start with https://")
            item.image_url = url
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

SEED_PARTNERS = [
    ("burgerboys", "Burger Boys", "3000 N Broadway, Knoxville, TN 37917"),
    ("friendsbbq", "Friends BBQ", "2580 E Magnolia Ave, Knoxville, TN 37914"),
    ("stephens", "Stephen's Pizzeria", "5049 Bobby Hicks Hwy #105, Gray, TN 37615"),
]

SEED_MENUS = {
    # VERIFIED from Burger Boys' live Toast ordering page (3000 N Broadway), July 2026.
    "burgerboys": [
        ("Burgers — ½ lb fresh 80/20 · Home of the FREE Fries", [
            ("Kobe Burger", "½ lb beef, sautéed onions & green peppers dipped in steak sauce, tomato & lettuce", 875),
            ("Lil Dom", "Mayo, ketchup, jalapeños, pepper jack, tomato & lettuce", 875),
            ("Lil Dre", "Loaded garden toppings, cheese, bacon", 975),
            ("Dante", "Onion straws, light mustard, American cheese", 850),
            ("Vol Burger", "½ lb, made to your specifications", 900),
            ("Big Dom", "1 lb beef, spicy peppers & sauce, tomato & lettuce", 1400),
        ]),
        ("Chicken Wings", [
            ("Chicken Wings (5 pc)", "", 900),
            ("Chicken Wings (10 pc)", "", 1700),
            ("Chicken Wings Meal", "5 pc with 2 sides", 1350),
        ]),
        ("Sides", [
            ("Mashed Potatoes (sm)", "", 350), ("Mashed Potatoes (lg)", "", 600),
            ("Mac & Cheese (sm)", "", 400), ("Mac & Cheese (lg)", "", 700),
            ("Collard Greens (sm)", "", 425), ("Collard Greens (lg)", "", 775),
            ("Potato Salad (sm)", "", 350), ("Potato Salad (lg)", "", 700),
        ]),
        ("Desserts & Drinks", [
            ("Cheesecake", "", 350), ("Sweet Potato Pie", "", 300),
            ("Coke Products (12 oz)", "", 150),
        ]),
    ],
    # VERIFIED from Friends BBQ's live Marble City Market listing, 2026.
    "friendsbbq": [
        ("Smoked Meats", [
            ("Turkey Leg", "Bone-in, all dark meat", 1500),
            ("Spare Ribs (slab)", "Slow-smoked", 1800),
            ("Rib Portion", "Bone-in", 1300),
            ("Brisket", "Sliced beef", 1200),
            ("Smoked Meatloaf", "", 1000),
            ("Pulled Chicken", "", 800),
            ("Pulled Pork", "", 600),
            ("Bologna Sandwich", "Thick-cut, lettuce & tomato", 600),
            ("Smoked Sausage", "", 500),
            ("Chicken Wing (each)", "Bone-in", 225),
        ]),
        ("Sides", [
            ("Fried Green Tomatoes", "", 660),
            ("Collard Greens", "", 440), ("Mac-n-Cheese", "", 440),
            ("Baked Beans", "", 440), ("Coleslaw", "", 440),
            ("Potato Salad", "", 440), ("Green Beans", "", 440),
            ("Fried Potato Chips", "", 440),
        ]),
        ("Family Packs — call to confirm pricing", [
            ("Pork Pack (serves 5)", "20 oz meat, 3 pint sides, sauce, 5 buns, 5 cookies", 3999),
            ("Chicken Pack (serves 5)", "20 oz meat, 3 pint sides, sauce, 5 buns, 5 cookies", 3999),
            ("Ribs Pack (serves 5)", "2.5 lb ribs, 3 pint sides, sauce, 5 cookies", 4999),
            ("Pork Pack (serves 10)", "40 oz meat, 3 quart sides, 10 buns, 10 cookies", 6999),
        ]),
        ("Drinks", [
            ("Pineapple Lemonade", "", 330),
        ]),
    ],
    # VERIFIED from Stephen's Pizzeria published menu, 2026.
    "stephens": [
        ("Appetizers", [
            ("Momma Mia Meatball Appetizer", "Homemade meatballs in pasta sauce", 549),
            ("Garlic & Cheese Breadsticks", "Garlic butter, cheese & herbs, marinara", 649),
            ("Boneless Chicken Wings", "All-white meat", 699),
            ("Roasted Garlic Hummus", "", 749),
        ]),
        ("Pizzas — NY style, hand-tossed 50-yr family recipe", [
            ("Personal Pizza 10\"", "Cheese; add toppings in notes", 867),
            ("Large Pizza 14\"", "Cheese; add toppings in notes", 1259),
            ("Extra Large Pizza 16\"", "Cheese; add toppings in notes", 1449),
            ("Pizza by the Slice", "", 259),
        ]),
        ("Specialty Pizzas (Large 14\")", [
            ("Queen's Margherita", "Fresh mozzarella, basil", 1470),
            ("Hawaiian", "Ham & pineapple", 1529),
            ("Spinach Tomato Alfredo", "Alfredo base", 1529),
            ("Big Babbo", "The house special", 1679),
            ("Jamaican Jerk", "Jerk-spiced chicken", 1679),
            ("Pesto Chicken", "Pesto base, grilled chicken", 1679),
            ("Buffalo Chicken Blue Cheese", "", 1679),
            ("Mega Meat", "Loaded with meats", 1879),
        ]),
        ("Calzones & Pasta", [
            ("New Classic New York Calzone", "Ricotta & mozzarella, marinara side", 749),
            ("Stephen's Spaghetti", "House marinara", 829),
        ]),
        ("Hoagies & Italian Wedges", [
            ("Stephen's Classic Italian Hoagie", "", 869),
            ("Mega Meatball Wedge", "", 899),
            ("Philly Cheese Steak", "", 899),
            ("Italian Philly", "", 899),
            ("Chicken Philly", "", 899),
            ("Buffalo Chicken Wedge", "", 899),
            ("Grilled Chicken Wedge", "", 899),
            ("Ham & Cheese", "", 799),
        ]),
        ("Salads", [
            ("Garden Salad (half)", "", 399),
            ("Garden Salad (whole)", "", 599),
            ("\"Best in Show\" Sweet BBQ Chicken Southwest Salad", "", 899),
            ("Premium Grilled Chicken Salad", "", 849),
            ("Premium Chef's Salad", "", 829),
            ("Italian Gorgonzola Salad", "", 829),
        ]),
        ("Desserts & Drinks", [
            ("Homemade Tiramisu", "", 599),
            ("Chocolate Cannoli", "", 499),
            ("Soft Drink / Tea", "", 239),
        ]),
    ],
}


MENU_DATA_VERSION = "real-v1"


def migrate_real_menus():
    """One-time: replace DRAFT seeded menus with the VERIFIED published menus
    (Burger Boys' Toast page, Friends BBQ's Marble City listing, Stephen's menu).
    Idempotent via a marker event. Founder edits made AFTER this run are preserved
    because the migration only fires once."""
    from .models import Event
    db: Session = SessionLocal()
    try:
        done = (db.query(Event)
                .filter(Event.event_type == "menu.migrated",
                        Event.entity_ref == MENU_DATA_VERSION).count() > 0)
        if done:
            return
        for code in SEED_MENUS:
            db.query(MenuItem).filter(MenuItem.partner_code == code).delete(
                synchronize_session=False)
        db.commit()
        for code, cats in SEED_MENUS.items():
            sort = 0
            for cat_name, items in cats:
                for name, desc, cents in items:
                    sort += 1
                    db.add(MenuItem(partner_code=code, category=cat_name, name=name,
                                    description=desc, price_cents=cents, sort=sort))
        db.add(Event(event_type="menu.migrated", entity_ref=MENU_DATA_VERSION,
                     tenant="gateway", actor="system",
                     payload='{"source":"published menus verified 2026-07"}'))
        db.commit()
    finally:
        db.close()


STORIES = {
    "burgerboys": {
        "about": "Founded in 2017 by Andre Bryant and built from the ground up. After eight years on Chapman Highway, the community helped us reopen on North Broadway — there's a supporter wall inside to prove it. Half-pound, fresh, never-frozen. Home of the FREE fries.",
        "thanks": "From my family to yours — thank you for keeping the little guy going. — Andre, Burger Boys",
    },
    "friendsbbq": {
        "about": "Knoxville born and raised. We bring soul to soul food — ribs, wings, turkey legs, pulled pork and smoked meatloaf. Every bite sends you down memory lane. We're not just friends, we're family.",
        "thanks": "Thank you for eating with us. We're not just friends, we're family. — Friends BBQ",
    },
    "stephens": {
        "about": "Hand-tossed New York style from a 50-year-old family recipe. Dough rolled nightly, vegetables sliced every morning, and a buttery blended cheese that makes your taste buds sing. Life, happiness, pizza.",
        "thanks": "Grazie for choosing our family's pizza. Life, happiness, pizza. — Stephen's Pizzeria",
    },
}

STORY_VERSION = "stories-v1"


def migrate_partner_stories():
    """Seed each pilot kitchen's real voice (idempotent, event-guarded)."""
    db: Session = SessionLocal()
    try:
        done = (db.query(Event)
                .filter(Event.event_type == "partner.stories_seeded",
                        Event.entity_ref == STORY_VERSION).count() > 0)
        if done:
            return
        for code, story in STORIES.items():
            p = db.get(Partner, code)
            if not p:
                continue
            if not p.about_blurb:
                p.about_blurb = story["about"][:280]
            if not p.thank_you_note:
                p.thank_you_note = story["thanks"][:300]
        db.add(Event(event_type="partner.stories_seeded", entity_ref=STORY_VERSION,
                     tenant="gateway", actor="system", payload="{}"))
        db.commit()
    finally:
        db.close()


def migrate_split_burgerboys():
    """One-time repair: burgerboys was seeded as a combined 'Burger Boys & Friends
    BBQ' partner. They are two separate restaurants. Renames the partner, moves the
    BBQ category to friendsbbq, and lets seed_menus fill the rest. Idempotent."""
    db: Session = SessionLocal()
    try:
        p = db.get(Partner, "burgerboys")
        if p and "Friends" in p.display_name:
            p.display_name = "Burger Boys"
            if db.get(Partner, "friendsbbq") is None:
                db.add(Partner(code="friendsbbq", display_name="Friends BBQ", status="pilot"))
            moved = (db.query(MenuItem)
                     .filter(MenuItem.partner_code == "burgerboys",
                             MenuItem.category == "BBQ").all())
            for item in moved:
                item.partner_code = "friendsbbq"
                item.category = "Sandwiches & Plates"
            db.commit()
    finally:
        db.close()


def seed_menus():
    migrate_split_burgerboys()
    db: Session = SessionLocal()
    try:
        for code, name, addr in SEED_PARTNERS:
            existing = db.get(Partner, code)
            if existing is None:
                db.add(Partner(code=code, display_name=name, status="pilot", address=addr))
            elif not existing.address:
                existing.address = addr
        db.commit()
        # ensure every partner has a kitchen portal token (runs after ALL partner creation)
        from .identity import _new_portal_token
        for p in db.query(Partner).filter(Partner.portal_token == "").all():
            p.portal_token = _new_portal_token()
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
    # stories must run AFTER all partners exist (seed-ordering lesson, debug #14)
    migrate_real_menus()
    migrate_partner_stories()
