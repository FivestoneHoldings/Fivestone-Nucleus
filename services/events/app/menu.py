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
from .options import options_for_items

router = APIRouter()


def _check_key(key: str):
    admin = os.environ.get("ADMIN_KEY", "")
    if not admin or not secrets.compare_digest(str(key), admin):
        raise HTTPException(403, "Bad board key")


def _grouped(items, db=None):
    opts = options_for_items(db, [i.id for i in items]) if db is not None else {}
    cats: dict = {}
    for i in items:
        cats.setdefault(i.category, []).append({
            "id": i.id, "name": i.name, "description": i.description,
            "price_cents": i.price_cents, "available": i.available,
            "image_url": i.image_url, "featured": i.featured, "options": opts.get(i.id, [])})
    return [{"name": c, "items": v} for c, v in cats.items()]


@router.get("/v0/partners/{code}/menu")
def public_menu(code: str):
    db: Session = SessionLocal()
    try:
        rows = (db.query(MenuItem)
                .filter(MenuItem.partner_code == code.lower().strip(),
                        MenuItem.available.is_(True))
                .order_by(MenuItem.sort, MenuItem.name).all())
        if not rows:
            raise HTTPException(404, "No menu for this partner")
        return {"partner": code.lower().strip(), "categories": _grouped(rows, db)}
    finally:
        db.close()


@router.get("/api/board/{key}/partners/{code}/menu")
def admin_menu(key: str, code: str):
    _check_key(key)
    db: Session = SessionLocal()
    try:
        rows = (db.query(MenuItem).filter(MenuItem.partner_code == code.lower().strip())
                .order_by(MenuItem.sort, MenuItem.name).all())
        return {"partner": code.lower().strip(), "categories": _grouped(rows, db)}
    finally:
        db.close()


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
        if body.get("featured") is not None:
            item.featured = bool(body["featured"])
        db.commit()
        return {"ok": True, "id": item.id}
    finally:
        db.close()


# ---------- KITCHEN-SCOPED 86 (v1.3) ----------
# The person who knows the fryer just died, or the shrimp ran out, is standing at
# the KITCHEN screen — not logged into the board. Before this, 86'ing an item
# required the board key, which the cook doesn't have and shouldn't need for a
# thirty-second fix. This endpoint is scoped to ONE partner's own portal token and
# can only flip availability — it cannot touch price, name, or add new items.
@router.get("/api/kitchen/{token}/menu")
async def kitchen_menu(token: str):
    from .kitchen import _partner_by_token
    p = _partner_by_token(token)
    db: Session = SessionLocal()
    try:
        items = (db.query(MenuItem)
                 .filter(MenuItem.partner_code == p.code)
                 .order_by(MenuItem.category, MenuItem.sort).all())
        return {"partner": p.code, "categories": _grouped(items, db)}
    finally:
        db.close()


@router.post("/api/kitchen/{token}/menu-items/{item_id}/86")
async def kitchen_toggle_86(token: str, item_id: str, request: Request):
    from .kitchen import _partner_by_token
    p = _partner_by_token(token)
    body = await request.json()
    db: Session = SessionLocal()
    try:
        item = db.get(MenuItem, item_id)
        if not item or item.partner_code != p.code:
            raise HTTPException(404, "No such item on your menu")
        item.available = bool(body.get("available", not item.available))
        db.commit()
        db.add(Event(event_type="menu.86" if not item.available else "menu.un86",
                     entity_ref=item.id, tenant="gateway", actor=f"kitchen:{p.code}",
                     payload=f'{{"name":"{item.name[:80]}"}}'))
        db.commit()
        return {"ok": True, "id": item.id, "available": item.available, "name": item.name}
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
    # Real pricing sourced from Asia Cafe's own delivery listings (Cedar Bluff /
    # Callahan locations) — DRAFT until Phillip confirms at go-live.
    ("asiacafe", "Asia Cafe", "1708 Callahan Dr, Knoxville, TN 37912"),
    ("asiacafexpress", "Asia Cafe Xpress", "8926 Town and Country Cir, Knoxville, TN 37923"),
]

SEED_MENUS = {
    # ===== VERIFIED from Lim Dynasty Asia Cafe's own live ordering site
    # (asiacafe.org/menu/northknoxville, fetched 2026-07) and Asia Cafe Xpress's
    # DoorDash listing (Alcoa location). Real D-codes and real prices — this is
    # a representative slice of a genuinely large menu (300+ items including
    # sushi bar), not the whole catalog; Phillip fills in anything we trimmed
    # via the board editor. Items marked ("PROTEIN", base_delta) get a real
    # 'Choose your protein' option group attached after seeding — Asia Cafe's
    # own menu prices these AS a required choice (Chicken $13.05+, Steak
    # $14.05+, Shrimp $15.05+), not a flat price.
    "asiacafe": [
        ("Beverages", [
            ("Sweet Tea", "", 335), ("Unsweet Tea", "", 335), ("Thai Tea", "", 335),
            ("Bubble Tea - Mango", "", 405), ("Bubble Tea - Strawberry", "", 405),
            ("Coconut Water", "", 405), ("Bottle Water", "", 155),
            ("AC Coffee 4 in 1 Single", "", 150), ("AC Coffee 4 in 1 Bag", "", 500),
            ("Fountain Drink", "Pepsi, Mtn Dew, Dr Pepper & more", 255),
        ]),
        ("Apps, Soups & Salads", [
            ("Crab Rangoons", "", 905), ("Gyoza", "", 805), ("Edamame", "", 705),
            ("Roti Canai", "", 805), ("Fried Tofu", "", 705),
            ("Salt and Pepper Calamari", "", 905), ("Satay Chicken", "", 905),
            ("Shish Kebob", "", 905), ("Tempura Vegetables", "", 805),
            ("Shrimp Tempura", "", 905), ("Asia Cafe Platter", "Mixed appetizer sampler", 1305),
            ("Single Vegetable Spring Roll", "", 205),
            ("Md Mushroom Soup", "", 405), ("Md Egg Drop Soup", "", 405),
            ("Md Hot and Sour Soup", "", 405), ("Md Tom Yum Soup D", "", 405),
            ("Md Wonton Soup", "", 505), ("House Salad", "", 505),
            ("Malaysian Salad", "", 905), ("Ginger Salad", "", 505),
            ("Chicken Wings", "", 805),
        ]),
        ("Asian Entrees D43-D56 · fried rice & choice of soup included", [
            ("General Tso Chicken D43", "Broccoli, special hot and spicy sauce", 1305),
            ("Sesame D44", "Broccoli, special sauce", 1305, "PROTEIN"),
            ("Sweet Sour Chicken D45", "Pineapple, carrots, onions, bell peppers", 1305),
            ("Black Pepper D46", "Onions, black pepper, special sauce", 1305, "PROTEIN"),
            ("Moo Goo Pan D47", "Carrots, onions, mushrooms, zucchini, snow peas", 1305, "PROTEIN"),
            ("Mongolian D49", "Green onions, jumbo onions", 1305, "PROTEIN"),
            ("Pepper D50", "Carrots, red & green bell peppers, jumbo onions", 1305, "PROTEIN"),
            ("Hunan D51", "Zucchini, bell peppers, broccoli, carrots, snow peas", 1305, "PROTEIN"),
            ("Broccoli D53", "Broccoli, carrots, snow peas", 1305, "PROTEIN"),
            ("Kung Pao D54", "Peppers, zucchini, mushrooms, jumbo onion", 1305, "PROTEIN"),
            ("Cashew D55", "Peppers, zucchini, mushrooms, onions, cashews", 1305, "PROTEIN"),
            ("Shrimp with Lobster Sauce D56", "Mushrooms, peas, carrots", 1405),
            ("Orange Chicken", "", 1305),
        ]),
        ("Noodle Dishes D70-D82", [
            ("Chinese Lo Mein D71", "Onions, green onions, soy sauce", 1305, "PROTEIN"),
            ("Pad Thai D73", "Peanuts, cilantro, egg, tomatoes, spicy sauce", 1305, "PROTEIN"),
            ("Drunken Noodle D74", "Bell peppers, onions, tomatoes, eggs", 1305, "PROTEIN"),
            ("Satay Noodles D70", "Stir fried in satay sauce", 1305, "PROTEIN"),
            ("Penang Mee Goreng D72", "Malaysian chili sauce, tomatoes, egg", 1305, "PROTEIN"),
            ("Wonton Mee Noodle Soup D76", "Homemade pork & dumplings", 1405),
        ]),
        ("Curries, Fried Rice & Vegetarian", [
            ("Chinese Fried Rice D39", "Eggs, onions, carrots, green onions", 1305, "PROTEIN"),
            ("Thai Fried Rice D40", "Pineapple, egg, curry powder, cilantro", 1305, "PROTEIN"),
            ("Basil Fried Rice D42", "Curry powder, cilantro, egg, pineapple", 1305, "PROTEIN"),
            ("Green Curry D58", "Potatoes, carrots, eggplant, coconut milk", 1305, "PROTEIN"),
            ("Red Curry D59", "Red chilis, carrots, bell peppers, coconut milk", 1305, "PROTEIN"),
            ("Rama Curry D60", "Yellow curry, peanut sauce, broccoli, carrots", 1305, "PROTEIN"),
            ("Masama Curry D61", "Coconut milk, potatoes, onions, peanuts", 1305, "PROTEIN"),
            ("Penang Curry D62", "Richer red curry, potatoes, broccoli, lime leaves", 1305, "PROTEIN"),
            ("Chop Suey D64", "Snow peas, broccoli, carrots, mushrooms, celery", 1205),
            ("Asia Cafe Veg Entree D65", "Carrots, bell peppers, broccoli, zucchini", 1205),
        ]),
        ("Hibachi Singles & Combos D18-D33 · fried rice, soup & veg included", [
            ("Vegetable D18", "", 1205), ("Tofu D19", "", 1205),
            ("Chicken D20", "", 1305), ("Steak D21", "", 1305),
            ("Shrimp D22", "", 1305), ("Ribeye D26", "", 1705),
            ("Chicken and Steak D27", "", 1405), ("Steak and Shrimp D28", "", 1405),
            ("Chicken and Shrimp D29", "", 1405), ("Steak and Crab D31", "", 1405),
        ]),
        ("Vietnamese — House-Made Pho", [
            ("VA6 Pho Ga", "White meat chicken, rice noodles, herbs, broth", 1305),
            ("VA4 Tai", "Rare steak, rice noodles, thinly sliced onions", 1305),
            ("VA5 Bo Vien", "Beef meatballs, rice noodles, broth", 1305),
            ("VA7 Pho Tom", "Shrimp, rice noodles, broth", 1305),
            ("VA8 Pho Combo", "Rare steak, flank steak, meatballs, tendon", 1905),
            ("VA10 Bun Dac Biet", "Grilled pork, shrimp, egg roll, vermicelli", 1505),
            ("VA11 Bun Thit Nuong", "Grilled pork, vermicelli, herbs", 1405),
            ("Goi Cuon", "Spring rolls — shrimp, herbs, rice paper, peanut sauce", 605),
        ]),
        ("Kids · 12 and under", [
            ("Kids Sweet Sour Chicken K1", "With fried rice", 805),
            ("Kids General Tso Chicken K2", "", 805),
            ("Kids Hib/Teri", "Zucchini, onions, broccoli, fried rice", 805),
            ("Kids Chicken Fingers w Fries", "", 805),
        ]),
        ("Desserts", [
            ("Meltdown", "Chocolate cake, ganache center, vanilla ice cream", 705),
            ("Turtle Lava", "Chocolate cake, caramel center, pecans, ice cream", 698),
            ("Cheesecake", "", 605),
            ("Chinese Doughnuts", "", 605),
            ("Tempura Banana", "", 505),
        ]),
        ("Side Orders", [
            ("Side Fried Rice", "", 255), ("Side Steamed Rice", "", 255),
            ("Side Vegetables", "", 505), ("Side Chicken", "", 605),
            ("Side Steak", "", 705), ("Side Shrimp", "", 705),
            ("Side French Fries", "", 405), ("Side Broccoli", "", 505),
            ("Fortune Cookie", "", 25),
        ]),
        ("2. Sushi Rolls — Full sushi bar available, ask your driver for the complete list", [
            ("California Roll", "Crab, avocado, cucumber, masago", 705),
            ("Spicy Tuna Roll", "Avocado, cucumber, spicy mayo", 905),
            ("Spicy Salmon Roll", "Avocado, cucumber, spicy mayo, crunchy", 905),
            ("Philadelphia Roll", "Smoked salmon, cream cheese, avocado", 905),
            ("Shrimp Tempura Roll", "Cucumber, avocado, eel sauce", 905),
            ("Rainbow Roll", "Snow crab, avocado, tuna, salmon, white tuna", 1505),
            ("Dragon Roll", "Crabstick, cucumber, avocado, BBQ eel", 1605),
            ("Volcano Roll", "Crab stick, crawfish, baked, wasabi mayo", 1605),
            ("Knoxville Roll", "Shrimp tempura, cream cheese, crawfish, snow crab", 1505),
        ]),
    ],
    # ===== Asia Cafe Xpress — Alcoa location, same D-code system as the
    # flagship. Counter-service concept: tighter menu, faster turn. Pricing
    # verified against their live DoorDash listing (this location's real
    # prices run a bit above Callahan's).
    "asiacafexpress": [
        ("Featured", [
            ("Xpress Combo", "Two entrees, fried rice, egg roll", 1895),
            ("Chinese Lo Mein D71", "", 1625, "PROTEIN"),
            ("Sweet Sour Chicken D45", "", 1625),
            ("L HIB/TER L15", "Lunch hibachi/teriyaki, broccoli, onions, zucchini", 1215),
        ]),
        ("Beverages", [
            ("Fountain Drink", "Free refills", 255), ("Sweet Tea", "", 335),
            ("Bottled Water", "", 155),
        ]),
        ("Lunch Menu · 11am-4pm · fried rice + choice of soup", [
            ("L Sweet Sour Chicken L3", "Pineapple, onions, carrots, bell peppers", 998),
            ("L General Tso Chicken L4", "Broccoli, hot & spicy sauce", 998),
            ("L Sesame Chicken L5", "Broccoli, sesame seeds", 998),
            ("L Broccoli L8", "Broccoli, carrots, brown sauce", 998, "PROTEIN"),
            ("L Lo Mein L10", "Cabbage stir fry, carrots, onions, noodles", 998, "PROTEIN"),
            ("L Hib-Teri L15", "Broccoli, onions, zucchini, mushrooms", 998, "PROTEIN"),
            ("L Hib-Teri Combo L16", "Chicken, steak, shrimp, veg", 1298),
        ]),
        ("Apps and Soups", [
            ("Crab Rangoons", "", 1195), ("Gyoza", "", 1065),
            ("Spring Rolls Goi Con", "", 805), ("Egg Drop Soup (md)", "", 405),
        ]),
        ("Dinners D43-D56", [
            ("General Tso Chicken D43", "", 1625),
            ("Sesame D44", "", 1625, "PROTEIN"),
            ("Broccoli D53", "", 1625, "PROTEIN"),
            ("Kung Pao D54", "", 1625, "PROTEIN"),
        ]),
        ("Kids · 12 and under", [
            ("Kids Sweet Sour Chicken", "With fried rice", 995),
            ("Kids Hib/Teri", "Small portion, fried rice", 995),
        ]),
        ("Desserts", [
            ("Cheesecake", "", 695), ("Chinese Doughnuts", "", 695),
        ]),
        ("Hibachi and Teriyaki D18-D22 · zucchini, onions, mushrooms, broccoli", [
            ("Vegetable D18", "", 1425), ("Chicken D20", "", 1625),
            ("Steak D21", "", 1625), ("Shrimp D22", "", 1625),
        ]),
        ("Side Orders", [
            ("Side Fried Rice", "", 295), ("Side French Fries", "", 450),
            ("Side Steak", "", 795), ("Side Shrimp", "", 795),
        ]),
    ],
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
                for row in items:
                    name, desc, cents = row[0], row[1], row[2]
                    sort += 1
                    item = MenuItem(partner_code=code, category=cat_name, name=name,
                                    description=desc, price_cents=cents, sort=sort)
                    db.add(item)
                    db.flush()
                    if len(row) > 3 and row[3] == "PROTEIN":
                        _attach_protein_options(db, item)
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



def _attach_protein_options(db, item):
    """Asia Cafe's own menu prices these entrees 'Chicken $13.05+, Steak $14.05+,
    Shrimp $15.05+' — the protein is a REQUIRED choice that changes the price,
    not a flat-priced dish. $1/$2 deltas match the site's own tiering."""
    from .models import OptionGroup, OptionChoice
    g = OptionGroup(item_id=item.id, name="Choose your protein", min_select=1, max_select=1, sort=0)
    db.add(g)
    db.flush()
    for i, (nm, delta, default) in enumerate([
        ("Chicken", 0, True), ("Tofu", 0, False), ("Beef", 100, False),
        ("Steak", 100, False), ("Shrimp", 200, False),
    ]):
        db.add(OptionChoice(group_id=g.id, name=nm, price_delta_cents=delta,
                            is_default=default, sort=i))

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
                    for row in items:
                        name, desc, cents = row[0], row[1], row[2]
                        item = MenuItem(partner_code=code, category=cat, name=name,
                                        description=desc, price_cents=cents, sort=sort)
                        db.add(item)
                        db.flush()
                        if len(row) > 3 and row[3] == "PROTEIN":
                            _attach_protein_options(db, item)
                        sort += 1
                db.commit()
    finally:
        db.close()
    # stories must run AFTER all partners exist (seed-ordering lesson, debug #14)
    migrate_real_menus()
    migrate_partner_stories()


@router.get("/api/board/{key}/photo-coverage")
def photo_coverage(key: str):
    """What still needs a photo — the founder's shot list."""
    _check_key(key)
    db: Session = SessionLocal()
    try:
        out = []
        for p in db.query(Partner).order_by(Partner.code).all():
            items = db.query(MenuItem).filter(MenuItem.partner_code == p.code).all()
            with_photo = [i for i in items if i.image_url]
            missing = [{"id": i.id, "name": i.name} for i in items if not i.image_url][:12]
            out.append({
                "code": p.code, "display_name": p.display_name,
                "hero": bool(p.hero_url),
                "items": len(items), "items_with_photo": len(with_photo),
                "pct": round(100 * len(with_photo) / len(items)) if items else 0,
                "missing_sample": missing,
            })
        return {"partners": out}
    finally:
        db.close()
