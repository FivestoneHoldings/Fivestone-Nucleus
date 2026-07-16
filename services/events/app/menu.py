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
        ('Beverages', [
            ('Sweet Tea', '', 335),
            ('Unsweet Tea', '', 335),
            ('Thai Tea', '', 335),
            ('Bubble Tea - Mango', '', 405),
            ('Bubble Tea - Strawberry', '', 405),
            ('Coconut Water', '', 405),
            ('Code Blue Gatorade', '', 328),
            ('Bottle Water', '', 155),
            ('AC Coffee 4 in 1 Single', '', 150),
            ('AC Coffee 4 in 1 Bag', '', 500),
            ('AC Coffee 6 in 1 Bag', '', 1305),
            ('AC Coffee 8 in 1 Bag', '', 800),
            ('Pepsi - Fountain', 'The bold, refreshing, robust cola', 255),
            ('Pepsi Zero Sugar - Fountain', 'Real cola taste, no sugar', 255),
            ('Mtn Dew - Fountain', 'One of a kind citrus taste', 255),
            ('Dr. Pepper - Fountain', 'A signature blend of 23 flavors', 255),
            ('Diet Dr. Pepper - Fountain', '23 flavors, without the calories', 255),
            ('Starry - Fountain', 'Crisp, clear lemon lime', 255),
            ('Crush Orange - Fountain', 'The original orange soda', 255),
            ('Tropicana Lemonade - Fountain', 'Freshly squeezed lemon taste', 255),
        ]),
        ('Appetizers', [
            ('Crab Rangoons', 'Deep fried pastry, crab meat & cream cheese', 905),
            ('Gyoza', 'Pan-fried dumplings', 805),
            ('Edamame', 'Steamed soybeans', 705),
            ('Roti Canai', 'Flaky flatbread with curry dipping sauce', 805),
            ('Fried Tofu', '', 705),
            ('Salt and Pepper Calamari', '', 905),
            ('Satay Chicken', 'Grilled skewers with peanut sauce', 905),
            ('Shish Kebob', '', 905),
            ('Tempura Vegetables', '', 805),
            ('Shrimp Tempura', '', 905),
            ('Asia Cafe Platter', 'Mixed appetizer sampler', 1305),
            ('Single Vegetable Spring Roll (1)', '', 205),
            ('Lumpia Shanghai (4)', 'Filipino-style fried spring rolls', 505),
            ('Chicken Wings', '', 805),
        ]),
        ('Soups', [
            ('Mushroom Soup (Sm)', '', 305),
            ('Mushroom Soup (Md)', '', 405),
            ('Mushroom Soup (Lg)', '', 505),
            ('Egg Drop Soup (Sm)', '', 305),
            ('Egg Drop Soup (Md)', '', 405),
            ('Egg Drop Soup (Lg)', '', 505),
            ('Hot and Sour Soup (Sm)', '', 305),
            ('Hot and Sour Soup (Md)', '', 405),
            ('Hot and Sour Soup (Lg)', '', 505),
            ('Tom Yum Soup (Sm)', 'Spicy & sour Thai soup', 305, 'SPICE'),
            ('Tom Yum Soup (Md)', 'Spicy & sour Thai soup', 405, 'SPICE'),
            ('Tom Yum Soup (Lg)', 'Spicy & sour Thai soup', 505, 'SPICE'),
            ('Tom Kha Soup (Sm)', 'Coconut milk Thai soup', 405),
            ('Tom Kha Soup (Md)', 'Coconut milk Thai soup', 505),
            ('Tom Kha Soup (Lg)', 'Coconut milk Thai soup', 605),
            ('Wonton Soup (Sm)', '', 405),
            ('Wonton Soup (Md)', '', 505),
            ('Wonton Soup (Lg)', '', 605),
            ('Miso Soup (Sm)', '', 405),
            ('Miso Soup (Md)', '', 505),
            ('Miso Soup (Lg)', '', 605),
        ]),
        ('Salads', [
            ('House Salad', 'With ginger dressing', 505),
            ('Ginger Salad', '', 505),
            ('Malaysian Salad', '', 905),
            ('Seaweed Salad', 'Seasoned seaweed salad', 605),
            ('Cucumber Salad', 'Thin sliced, ponzu & sesame', 605),
            ('Squid Salad', 'Seasoned thin sliced squid', 805),
            ('Snowcrab Salad', 'Snow crab, avocado, asparagus & masago', 805),
            ('Seafood Salad', 'Assorted fish, shrimp & octopus', 905),
            ('Tuna Salad', 'Tuna, cucumber, masago, avocado, ponzu', 905),
            ('Kani Salad', 'Crab stick salad', 805),
        ]),
        ('Asian Entrees', [
            ('General Tso Chicken D43', 'Broccoli with special hot and spicy sauce', 1305),
            ('Sesame D44', 'With broccoli and special sauce', 1305, 'PROTEIN'),
            ('Sweet Sour Chicken D45', 'Pineapple, carrots, onions & bell peppers', 1305),
            ('Black Pepper D46', 'Onions, black pepper & special sauce', 1305, 'PROTEIN'),
            ('Moo Goo Pan D47', 'Carrots, onions, mushrooms, zucchini, snow peas', 1305, 'PROTEIN'),
            ('Sha Cha Sauce D48', 'Mixed vegetables & sha cha sauce', 1305, 'PROTEIN'),
            ('Mongolian D49', 'Green onions & jumbo onions', 1305, 'PROTEIN'),
            ('Pepper D50', 'Carrots, red & green bell peppers, jumbo onions', 1305, 'PROTEIN'),
            ('Hunan D51', 'Zucchini, bell peppers, broccoli, carrots, snow peas', 1305, 'PROTEIN'),
            ('Pad Prik D52', 'Bell pepper, onion & green onion, light brown sauce', 1305, 'PROTEIN'),
            ('Broccoli D53', 'Broccoli, carrots & snow peas', 1305, 'PROTEIN'),
            ('Kung Pao D54', 'Green & red peppers, zucchini, mushrooms, onion', 1305, 'PROTEIN'),
            ('Cashew D55', 'Peppers, zucchini, mushrooms, onions & cashews', 1305, 'PROTEIN'),
            ('Shrimp with Lobster Sauce D56', 'Lobster sauce, mushrooms, peas & carrots', 1405),
            ('Garlic', 'Broccoli & carrots in white sauce', 1305, 'PROTEIN'),
            ('Orange Chicken', '', 1305),
            ('Cilantro Stir Fry', '', 1305, 'PROTEIN'),
            ('Beef and Scallops', '', 1405),
            ('Sweet Sour Shrimp', '', 1398),
            ('Mojarra Fried Tilapia D43', '', 1505),
            ('Grilled Fish and Shrimp D44', '', 1505),
            ('Lechon Kawali', 'Crispy Filipino pork belly', 1498),
        ]),
        ('Noodle Dishes', [
            ('Satay Noodles D70', 'Stir fried noodles in satay sauce', 1305, 'PROTEIN'),
            ('Chinese Lo Mein D71', 'Onions, green onions & soy sauce', 1305, 'PROTEIN'),
            ('Penang Mee Goreng D72', 'Malaysian chili sauce, tomatoes & egg', 1305, 'PROTEIN'),
            ('Pad Thai D73', 'Peanuts, cilantro, egg, tomatoes & spicy sauce', 1305, 'PROTEIN'),
            ('Drunken Noodle D74', 'Bell peppers, onions, tomatoes & eggs', 1305, 'PROTEIN'),
            ('Thai Mee Siam D75', 'Thin rice noodles, carrots, cabbage, scallions', 1305, 'PROTEIN'),
            ('Wonton Mee Noodle Soup D76', 'Egg noodles, homemade pork & dumplings', 1405),
            ('Chow Kueh Teow D77', 'Malaysian flat rice noodles, egg, chili sauce', 1405, 'PROTEIN'),
            ('Singapore Rice Noodles D78', 'Light soy, chili, onions & curry powder', 1405, 'PROTEIN'),
            ('Curry Mee Noodle Soup D79', 'Chili base, curry powder, coconut milk, eggplant', 1305),
            ('Black Pepper Sauce Noodles D80', 'Bell peppers, onions, green onions', 1305, 'PROTEIN'),
            ('Shrimp Laksa Mee Hoon D81', 'Carrots, napa, bean sprouts, coconut milk', 1405),
            ("Chef's Special Broad Noodle Soup D82", 'Shrimp, chicken & vegetables', 1405),
        ]),
        ('Curries', [
            ('Green Curry D58', 'Potatoes, carrots, eggplant, snow peas, coconut milk', 1305, 'PROTEIN'),
            ('Red Curry D59', 'Red chilis, carrots, bell peppers, eggplant, coconut milk', 1305, 'PROTEIN'),
            ('Rama Curry D60', 'Yellow curry, peanut sauce, broccoli, carrots, peppers', 1305, 'PROTEIN'),
            ('Masama Curry D61', 'Coconut milk, potatoes, onions, pineapple & peanuts', 1305, 'PROTEIN'),
            ('Penang Curry D62', 'Richer red curry, potatoes, broccoli, lime leaves', 1305, 'PROTEIN'),
            ('Sotong Curry D63', 'Squid, green curry, carrots, snow peas, coconut milk', 1305),
        ]),
        ('Fried Rice & Vegetarian', [
            ('Chinese Fried Rice D39', 'Eggs, onions, carrots & green onions', 1305, 'PROTEIN'),
            ('Thai Fried Rice D40', 'Pineapple, egg, curry powder, cilantro', 1305, 'PROTEIN'),
            ('Malaysian Nasi Goreng D41', 'Peas, pineapple, chili sauce, carrots, tomatoes', 1305, 'PROTEIN'),
            ('Basil Fried Rice D42', 'Curry powder, cilantro, egg, green onions, pineapple', 1305, 'PROTEIN'),
            ('Chop Suey D64', 'Snow peas, broccoli, carrots, mushrooms, celery, napa', 1205),
            ('Asia Cafe Veg Entree D65', 'Carrots, bell peppers, broccoli, zucchini, sauce on side', 1205),
            ('Basil Eggplant D66', 'Bell peppers, onions, carrots, zucchini, basil', 1205),
            ('Szechuan Eggplant D67', 'Carrots, snow peas, celery, eggplant', 1205),
            ('Hunan Tofu D68', 'Zucchini, bell peppers, broccoli, carrots, snow peas, tofu', 1205),
            ('Garden Delight D69', 'Napa, carrots, green & red bell peppers, zucchini', 1205),
            ('Egg Foo Young D70', '', 1205),
        ]),
        ('Bentos & Exotics', [
            ('Bento Box Chicken D14', '', 1505, 'SPICE'),
            ('Bento Box Steak D15', '', 1505, 'SPICE'),
            ('Bento Box Vegetarian D17', '', 1505, 'SPICE'),
            ('Bento Box Shrimp D18', '', 1605, 'SPICE'),
            ('Chicken with Fries D2', 'Marinated in Chinese spices, deep-fried', 1605),
            ('Malaysian Bak Kut Teh D3', 'Chinese mushrooms, garlic, barbecue ribs, herbs', 1505),
            ('Malaysian Beef Rendang D4', 'Cucumber, banana leaf, grated coconut', 1505),
            ('Malaysian Style Shrimp and Squid D5', 'Chili base, lemon grass, coconut milk', 1505),
            ('Thai Style Chicken and Shrimp D6', 'Chili base, lemon grass, coconut milk', 1505),
            ('Shrimp and Scallop Garlic Sauce D7', 'Carrots, broccoli, snow peas', 1505),
            ('Asia Cafe Seafood Delight', '', 1505),
            ('Asia Cafe Spring Chicken', '', 1598),
            ('Chicken Feet D1', 'Chinese mushrooms, green onions & carrots', 1298),
            ('Roast Duck', '', 2998),
        ]),
        ('Hibachi Singles', [
            ('Hibachi Vegetable D18', 'Fried rice, soup & veg included', 1205, 'SPICE'),
            ('Hibachi Tofu D19', 'Fried rice, soup & veg included', 1205, 'SPICE'),
            ('Hibachi Chicken D20', 'Fried rice, soup & veg included', 1305, 'SPICE'),
            ('Hibachi Steak D21', 'Fried rice, soup & veg included', 1305, 'SPICE'),
            ('Hibachi Shrimp D22', 'Fried rice, soup & veg included', 1305, 'SPICE'),
            ('Hibachi Crab Meat D23', 'Fried rice, soup & veg included', 1305, 'SPICE'),
            ('Hibachi Ribeye D26', 'Fried rice, soup & veg included', 1705, 'SPICE'),
            ('Hibachi Filet Mignon', 'Fried rice, soup & veg included', 2005, 'SPICE'),
        ]),
        ('Hibachi Combos', [
            ('Chicken and Steak D27', 'Fried rice, soup & veg included', 1405, 'SPICE'),
            ('Steak and Shrimp D28', 'Fried rice, soup & veg included', 1405, 'SPICE'),
            ('Chicken and Shrimp D29', 'Fried rice, soup & veg included', 1405, 'SPICE'),
            ('Steak and Crab D31', 'Fried rice, soup & veg included', 1405, 'SPICE'),
            ('Shrimp and Crab D32', 'Fried rice, soup & veg included', 1405, 'SPICE'),
            ('Chicken and Crab D33', 'Fried rice, soup & veg included', 1405, 'SPICE'),
        ]),
        ('Imperial Dinners', [
            ('Chicken Shrimp Steak D37', '', 1505, 'SPICE'),
            ('Chicken Shrimp Crab D38', '', 1505, 'SPICE'),
            ('Imperial Dinner D41', 'Chicken, steak, shrimp & crab meat', 2005, 'SPICE'),
        ]),
        ('Vietnamese Pho & Vermicelli', [
            ('VA1 Tai & Nam', 'Rare steak & flank steak in house pho', 1405),
            ('VA2 Tai & Gan', 'Rare steak & tendon in house pho', 1405),
            ('VA3 Tai & Sach', 'Rare steak & tripe in house pho', 1405),
            ('VA4 Tai', 'Rare steak in house pho, herbs & broth', 1305),
            ('VA5 Bo Vien', 'Beef meatballs in house pho', 1305),
            ('VA6 Pho Ga', 'White meat chicken in house pho', 1305),
            ('VA7 Pho Tom', 'Shrimp in house pho', 1305),
            ('VA8 Pho Combo', 'Rare steak, flank steak, meatballs & tendon', 1905),
            ('VA10 Bun Dac Biet', 'Grilled pork, shrimp & egg roll over vermicelli', 1505),
            ('VA11 Bun Thit Nuong', 'Grilled pork over vermicelli', 1405),
            ('VA12 Bun Tom Nuong', 'Grilled shrimp over vermicelli', 1505),
            ('VA13 Bun Cha Gio', 'Egg roll over vermicelli', 1305),
            ('VA14 Bun Cha Gio Thit Nuong', 'Grilled pork & egg roll over vermicelli', 1405),
            ('Goi Cuon', 'Fresh spring rolls, shrimp, herbs, peanut sauce', 605),
        ]),
        ('Lunch Menu · 11am-4pm · fried rice + choice of soup', [
            ('L Cilantro Vegetable Stir Fry L1', 'Chili base, red onions, eggplant, cabbage', 998, 'PROTEIN'),
            ('L Szechuan Eggplant L2', 'Carrots, snow peas, celery, eggplant', 998, 'PROTEIN'),
            ('L Sweet Sour Chicken L3', 'Pineapple, onions, carrots, bell peppers', 998, 'PROTEIN'),
            ('L General Tso Chicken L4', 'Broccoli, hot & spicy sauce, dried chili', 998, 'PROTEIN'),
            ('L Sesame Chicken L5', 'Broccoli, special sauce & sesame seeds', 998, 'PROTEIN'),
            ('L Moo Goo Pan L6', 'White meat chicken, mushrooms, carrots, cabbage', 998, 'PROTEIN'),
            ('L Garlic L7', 'Broccoli & carrots in white sauce', 998, 'PROTEIN'),
            ('L Broccoli L8', 'Broccoli & carrots in brown sauce', 998, 'PROTEIN'),
            ('L Black Pepper L9', 'Jumbo onions, bell peppers, light brown sauce', 998, 'PROTEIN'),
            ('L Lo Mein L10', 'Cabbage, carrots, onions, green onions, noodles', 998, 'PROTEIN'),
            ('L Mongolian L11', 'Green onions & jumbo onions', 998, 'PROTEIN'),
            ('L Pepper L12', 'Carrots, red & green bell peppers, jumbo onions', 998, 'PROTEIN'),
            ('L Hunan L13', 'Zucchini, bell peppers, broccoli, carrots, snow peas', 998, 'PROTEIN'),
            ('L Cashew L14', 'Onions, peppers, carrots, zucchini, mushrooms, cashews', 998, 'PROTEIN'),
            ('L Hibachi-Teriyaki L15', 'Broccoli, onions, zucchini, mushrooms', 998, 'PROTEIN'),
            ('L Hibachi-Teriyaki Combo L16', 'Chicken, steak, shrimp & veg', 1298),
            ('L Penang Curry L18', 'Richer red curry, potatoes, broccoli, lime leaves', 998, 'PROTEIN'),
            ('L Red Curry L19', 'Red chilis, basil, carrots, bell peppers, coconut milk', 998, 'PROTEIN'),
            ('L Rama Curry L20', 'Yellow curry, peanut sauce, broccoli, carrots', 998, 'PROTEIN'),
            ('L Masaman Curry L21', 'Coconut milk, potatoes, onions, pineapple, peanuts', 998, 'PROTEIN'),
            ('L Green Curry L22', 'Potatoes, carrots, eggplant, snow peas, coconut milk', 998, 'PROTEIN'),
            ('L Thai Mee Siam L23', 'Thin rice noodles, carrots, cabbage, scallions', 998, 'PROTEIN'),
            ('L Malaysian Mee Goreng L24', 'Chicken or beef, chili sauce, egg & soy', 998, 'PROTEIN'),
            ('L Kung Pao', 'Green & red peppers, zucchini, mushrooms, onion', 998, 'PROTEIN'),
        ]),
        ('Kids · 12 and under', [
            ('Kids Sweet Sour Chicken K1', 'With fried rice', 805),
            ('Kids General Tso Chicken K2', '', 805),
            ('Kids Hibachi/Teriyaki', 'Zucchini, onions, broccoli, fried rice', 805),
            ('Kids Sesame Chicken K6', '', 805),
            ('Kids Chicken Fingers w Fries', '', 805),
        ]),
        ('Sushi Appetizers', [
            ('Tuna Tataki', 'Black pepper tuna, ponzu, masago & scallions', 1005),
            ('Baked Salmon', 'Salmon rolled in snow crab, sweet tangy sauce', 1005),
            ('Tempura Salmon Cheese', 'Salmon, cream cheese, jalapeno, deep fried, ponzu', 1005),
            ('Salmon Skin Salad', 'Salmon skin, seaweed, tamago, cucumber, avocado', 705),
            ('Chef Salad', 'Tuna, cucumber, seaweed, avocado, crunchy', 805),
            ('Unagi Salad', '', 805),
        ]),
        ('Sushi Rolls', [
            ('California Roll', 'Crab, avocado, cucumber, masago', 705),
            ('Spicy Tuna Roll', 'Spicy tuna, avocado, cucumber, spicy mayo', 905, 'SPICE'),
            ('Spicy Salmon Roll', 'Salmon, avocado, cucumber, spicy mayo, crunchy', 905, 'SPICE'),
            ('Spicy Scallop Roll', 'Chopped scallop, sriracha, spicy mayo, crunchy', 905, 'SPICE'),
            ('Philadelphia Roll', 'Smoked salmon, cream cheese & avocado', 905),
            ('Shrimp Tempura Roll', 'Tempura shrimp, cucumber, avocado, eel sauce', 905),
            ('Crunchy Roll', 'Snow crab, crunchy & asparagus', 705),
            ('Boston Roll', 'Boiled shrimp, avocado & cucumber', 705),
            ('Dynamite Roll', 'Chopped fish, masago, spicy mayo & sriracha', 905, 'SPICE'),
            ('Eel Roll', 'Eel, cucumber, avocado, eel sauce', 905),
            ('Crunchy Shrimp Roll', 'Boiled shrimp, avocado, crunchy, spicy mayo', 805),
            ('Salmon Roll', 'Salmon with seaweed wrapper', 805),
            ('Tuna Roll', 'Tuna with seaweed wrapper', 905),
            ('Yellowtail Roll', 'Yellowtail & scallion, seaweed wrapper', 1005),
            ('Avocado Roll', 'Avocado with seaweed wrapper', 505),
            ('Cucumber Roll', '', 505),
            ('Vegetable Roll', 'Assorted vegetables & Japanese pickles', 605),
            ('Rainbow Roll', 'Snow crab, avocado, tuna, salmon & white tuna', 1505),
            ('Dragon Roll', 'Crabstick, cucumber, avocado, BBQ eel', 1605),
            ('Volcano Roll', 'Crab, avocado, cucumber, crawfish & scallop, baked', 1605),
            ('Spider Roll', 'Fried soft shell crab, snow crab & avocado', 1505),
            ('Asia Cafe Roll', 'Soft shell crab, shrimp tempura, crawfish, spicy mayo', 1605),
            ("Chef's Special Roll", 'Yellowtail, tuna, salmon, mango, snow crab, eel', 1605),
            ('Knoxville Roll', 'Shrimp tempura, cream cheese, crawfish, snow crab', 1505),
            ('Tennessee Roll', 'Spicy tuna & shrimp tempura, sweet tangy sauce', 1105, 'SPICE'),
            ('Sunshine Roll', 'Shrimp tempura, avocado, cream cheese, boiled shrimp', 1405),
            ('Surf and Turf Roll', 'Shrimp tempura, cream cheese, smoked salmon, snow crab', 1505),
            ('Crazy Crab Roll', 'Crabstick, avocado, snow crab, spicy mayo, sriracha', 1305, 'SPICE'),
            ('New York Roll', 'Salmon, avocado, cream cheese, topped with salmon', 1505),
            ('Chicago Roll', 'Tuna, avocado, cream cheese, topped with tuna', 1505),
            ('Pink Lady Roll', 'Spicy salmon, snow crab, avocado, crunchy, pink wrap', 1205, 'SPICE'),
            ('Deep Fried Bagel Roll', 'Smoked salmon, cream cheese, crab, deep fried', 1505),
        ]),
        ('Nigiri (3 per order)', [
            ('Salmon (Sake) Nigiri', '', 805),
            ('Tuna (Maguro) Nigiri', '', 905),
            ('Fresh Water Eel (Unagi) Nigiri', '', 905),
            ('Escolar Nigiri', '', 805),
            ('Flying Fish Roe (Tobiko) Nigiri', '', 805),
            ('Crab Stick (Kani) Nigiri', '', 705),
            ('Octopus (Tako) Nigiri', '', 805),
            ('Shrimp (Ebi) Nigiri', '', 705),
            ('Egg Custard (Tamago) Nigiri', '', 605),
        ]),
        ('Sashimi (3 per order)', [
            ('Salmon (Sake) Sashimi', '', 1005),
            ('Tuna (Maguro) Sashimi', '', 1005),
            ('Yellow Tail Sashimi', '', 1205),
            ('Fresh Water Eel (Unagi) Sashimi', '', 1005),
            ('Escolar Sashimi', '', 1005),
            ('Octopus (Tako) Sashimi', '', 1005),
            ('Egg Custard (Tamago) Sashimi', '', 705),
        ]),
        ('Dinners from the Sushi Bar', [
            ('Sushi Deluxe', '9 pieces nigiri & 1 California roll', 2505),
            ('Sashimi Deluxe', '12 piece chef choice & 1 salmon roll', 3105),
            ('Nigiri and Sashimi Dinner', '6 nigiri, 6 sashimi & 1 tuna roll', 3205),
            ('Ninja Platter', '12 pieces chef choice, California & spicy tuna roll', 3405),
            ('Chirashi', 'Assorted sashimi over sushi rice', 1705),
            ('Unagi-Don', 'BBQ eel over sushi rice', 1505),
            ('Asia Cafe Love Boat', '15 sashimi, 6 nigiri, veg roll & special roll', 6805),
        ]),
        ('Desserts', [
            ('Meltdown', 'Chocolate cake, ganache center, vanilla ice cream', 705),
            ('Turtle Lava', 'Chocolate cake, caramel center, pecans, ice cream', 698),
            ('Cheesecake', 'Rich cream cheese & pure vanilla', 605),
            ('Pineapple Upside Down Cake', 'Warm, pineapple & chocolate topping', 705),
            ('Chinese Doughnuts', '', 605),
            ('Tempura Banana', '', 505),
            ('Sesame Balls', '', 505),
            ('Ice Cream', '', 398),
        ]),
        ('Side Orders', [
            ('Side Fried Rice', '', 255),
            ('Side Steamed Rice', '', 255),
            ('Side Vegetables', '', 505),
            ('Side Soba Noodles', '', 505),
            ('Side Chicken', '', 605),
            ('Side Steak', '', 705),
            ('Side Shrimp', '', 705),
            ('Side French Fries', '', 405),
            ('Side Sweet Carrots', '', 405),
            ('Side Broccoli', '', 505),
            ('Side Zucchini', '', 505),
            ('Side Roti Bread', '', 155),
            ('Fortune Cookie', '', 25),
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


MENU_DATA_VERSION = "real-v2-asiacafe-complete"


def migrate_real_menus():
    """Replace DRAFT seeded menus with VERIFIED published menus. Idempotent via a
    per-version marker event; founder edits are preserved because a given version
    only ever fires once.

    v1 (real-v1) seeded all pilot menus. v2 (real-v2-asiacafe-complete) is a
    SURGICAL rebuild of ONLY Asia Cafe — the full 270+ item menu transcribed from
    asiacafe.org — so it must NOT touch Burger Boys / Friends BBQ / Stephen's,
    whose menus the founder may have hand-tuned since v1. The rebuild scope is
    therefore keyed to the version, not a blanket wipe of every seed partner."""
    from .models import Event, OptionGroup, OptionChoice
    # which partners this version is allowed to rebuild
    REBUILD_SCOPE = {
        "real-v1": list(SEED_MENUS.keys()),
        "real-v2-asiacafe-complete": ["asiacafe"],
    }
    scope = REBUILD_SCOPE.get(MENU_DATA_VERSION, list(SEED_MENUS.keys()))
    db: Session = SessionLocal()
    try:
        done = (db.query(Event)
                .filter(Event.event_type == "menu.migrated",
                        Event.entity_ref == MENU_DATA_VERSION).count() > 0)
        if done:
            return
        for code in scope:
            # clear options belonging to this partner's items, then the items
            item_ids = [i.id for i in db.query(MenuItem)
                        .filter(MenuItem.partner_code == code).all()]
            if item_ids:
                grp_ids = [g.id for g in db.query(OptionGroup)
                           .filter(OptionGroup.item_id.in_(item_ids)).all()]
                if grp_ids:
                    db.query(OptionChoice).filter(
                        OptionChoice.group_id.in_(grp_ids)).delete(synchronize_session=False)
                    db.query(OptionGroup).filter(
                        OptionGroup.id.in_(grp_ids)).delete(synchronize_session=False)
            db.query(MenuItem).filter(MenuItem.partner_code == code).delete(
                synchronize_session=False)
        db.commit()
        for code in scope:
            cats = SEED_MENUS.get(code, [])
            sort = 0
            for cat_name, items in cats:
                for row in items:
                    name, desc, cents = row[0], row[1], row[2]
                    sort += 1
                    item = MenuItem(partner_code=code, category=cat_name, name=name,
                                    description=desc, price_cents=cents, sort=sort)
                    db.add(item)
                    db.flush()
                    marker = row[3] if len(row) > 3 else ""
                    if marker == "PROTEIN":
                        _attach_protein_options(db, item)
                        _attach_spice_options(db, item)   # protein dishes are spice-customizable too
                    elif marker == "SPICE":
                        _attach_spice_options(db, item)
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



def _attach_spice_options(db, item):
    """Asia Cafe's menu marks many dishes customizable — Mongolian, curries,
    hibachi and spicy rolls all take a heat level. Reviews specifically call out
    'customizable spiciness levels'. Free choice, no upcharge; Medium default."""
    from .models import OptionGroup, OptionChoice
    g = OptionGroup(item_id=item.id, name="Spice level", min_select=1, max_select=1, sort=1)
    db.add(g)
    db.flush()
    for i, (nm, default) in enumerate([
        ("Mild", False), ("Medium", True), ("Hot", False),
        ("Thai Hot 🔥", False), ("No spice", False),
    ]):
        db.add(OptionChoice(group_id=g.id, name=nm, price_delta_cents=0,
                            is_default=default, sort=i))


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
                        marker = row[3] if len(row) > 3 else ""
                        if marker == "PROTEIN":
                            _attach_protein_options(db, item)
                            _attach_spice_options(db, item)
                        elif marker == "SPICE":
                            _attach_spice_options(db, item)
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
