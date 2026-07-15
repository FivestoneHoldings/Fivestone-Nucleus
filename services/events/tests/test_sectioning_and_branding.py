"""v1.5 — SECTIONING, FEATURED PRODUCTS, AND THE FOUNDER'S SCREEN-BY-SCREEN NOTES.

Each test traces to a specific complaint: 'the courier tab just randomly sits
under the menu,' 'the Details button does nothing,' 'the menus still show
GateWay Delivery name and icons.'
"""
import os

from fastapi.testclient import TestClient

from app.main import app
from app.db import SessionLocal
from app.models import MenuItem

client = TestClient(app)
ROOT = os.path.join(os.path.dirname(__file__), "..")
UI = os.path.join(ROOT, "app", "ui")


def _page(name):
    return open(os.path.join(UI, name)).read()


# ---------------- home sectioning ----------------

def test_courier_tile_lives_inside_a_named_section():
    """Founder originally: 'there's just a GateWay courier tab that's just like
    there. It should be like a section?' — so it became a real card.

    v1.7 update: the founder then asked for it to be 'much more prominent and
    independent'. It's now a standalone hero card promoted above the restaurant
    list AND a first-class bottom-nav destination — no longer tucked in a
    'More ways to get things done' footnote."""
    home = _page("home.html")
    # standalone, prominent card exists and is a link to its own surface
    assert 'class="courier"' in home
    assert 'href="/courier"' in home
    # promoted above the restaurant list, not below it
    assert home.index('class="courier"') < home.index('id="restaurants"')
    # and it's an independent nav destination
    assert "<span>Courier</span>" in home


def test_tracking_tile_also_has_a_section_header():
    home = _page("home.html")
    assert "Your account" in home


def test_featured_products_endpoint_returns_real_picks_only():
    d = client.get("/v0/featured-items").json()
    assert d["items"], "no featured products seeded"
    for it in d["items"]:
        assert it["partner_code"] not in ("riseshine", "summitcof", "elcamino",
                                          "magnolia", "gardengrn"), \
            "a demo/PREVIEW merchant leaked into the curated featured rail"


def test_featured_products_never_shows_two_items_from_one_kitchen():
    """One per merchant so the rail reads as curated, not one kitchen crowding it."""
    d = client.get("/v0/featured-items").json()
    codes = [it["partner_code"] for it in d["items"]]
    assert len(codes) == len(set(codes))


def test_featured_products_excludes_86d_items():
    db = SessionLocal()
    try:
        item = db.query(MenuItem).filter(MenuItem.name == "Kobe Burger").first()
        assert item is not None
        item.available = False
        db.commit()
    finally:
        db.close()
    try:
        d = client.get("/v0/featured-items").json()
        assert all(it["name"] != "Kobe Burger" for it in d["items"])
    finally:
        db2 = SessionLocal()
        try:
            db2.query(MenuItem).filter(MenuItem.name == "Kobe Burger").first().available = True
            db2.commit()
        finally:
            db2.close()


def test_home_has_a_featured_products_rail():
    home = _page("home.html")
    assert "paintFeaturedProducts" in home
    assert "/v0/featured-items" in home
    assert "Featured products" in home


# ---------------- the courier Details button ----------------

def test_courier_details_button_actually_does_something():
    """Founder: 'the details button on courier page total element does
    nothing.' It must toggle a real breakdown, not call .focus() on an
    unrelated textarea."""
    c = _page("courier.html")
    assert "toggleQuoteDetails" in c
    assert 'id="qBreak"' in c
    # the Details button itself must call the real toggle, not the old no-op
    assert 'onclick="toggleQuoteDetails()" id="qDetailsBtn"' in c


def test_courier_has_more_task_categories():
    """Founder: 'the what do you need moved should have more options.'"""
    c = _page("courier.html")
    for job in ("Groceries", "Flowers", "Return", "Laundry", "Pet supplies",
               "Office", "Furniture"):
        assert job.split()[0] in c, job


def test_courier_has_a_size_selector_and_care_options():
    c = _page("courier.html")
    assert "paintSizes" in c and "SIZES" in c
    assert "paintCare" in c and "Fragile" in c


# ---------------- promo box, redesigned ----------------

def test_promo_box_has_no_dashed_debug_looking_border():
    """Founder: 'the promo code area is still a bit weird on mobile.' A dashed
    border reads as an unfinished placeholder, not a shipped feature."""
    form = _page("order-form.html")
    css = form[form.index("<style>"):form.index("</style>")]
    assert "border:1.5px dashed" not in css


def test_promo_apply_button_only_activates_once_something_is_typed():
    form = _page("order-form.html")
    assert "paintPromoBtn" in form
    assert "classList.toggle('ready'" in form


# ---------------- GateWay branding leak on partner order forms ----------------

def test_partner_order_form_header_shows_the_merchants_own_name():
    """Founder: 'the actual menus still show GateWay Delivery name and icons.'
    A merchant's storefront should say THEIR name up top — GateWay stays as the
    small 'Powered by' credit, not the headline."""
    form = _page("order-form.html")
    assert 'id="headerMark"' in form
    assert "PARTNER_NAME.replace" in form and "· GateWay</span>" in form


def test_the_generic_courier_form_header_still_says_gateway():
    """The header rebrand only fires once a partner is actually known — the
    no-menu courier form correctly keeps the GateWay identity."""
    form = _page("order-form.html")
    assert '<div class="mark" id="headerMark">GateWay <span>Delivery</span></div>' in form


def test_browser_tab_title_becomes_the_merchants_name_on_a_partner_page():
    form = _page("order-form.html")
    assert "document.title = d.display_name" in form


def test_powered_by_gateway_credit_still_exists():
    """The GateWay brand doesn't disappear — it just steps back to a footer
    credit instead of the headline, exactly matching the white-label posture
    from v1.2 (branded splash IS the seam between marketplace and white-label)."""
    form = _page("order-form.html")
    assert "Powered by" in form and "GateWay Delivery" in form
