"""v1.1 STOREFRONT ERA — the contracts that must never quietly break.

The load-bearing test in this file is test_hostile_client_cannot_invent_a_discount:
the client is a PREVIEW. If a tampered browser could post discount_cents=999999,
the driver would show up at the door and collect the wrong cash. The server is the
only authority on money, and this file proves it.
"""
import os

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import SessionLocal
from app.models import Lead, PromoCode, SupportTicket, Partner
from app import intake as intake_mod

client = TestClient(app)
ROOT = os.path.join(os.path.dirname(__file__), "..")

CREATED = []   # every order the app wrote to Airtable — the money assertions read this


async def fake_list(table, formula="", fields=None, max_records=100):
    return []


async def fake_create(table, fields):
    CREATED.append(fields)
    return {"id": "recS", "fields": fields}


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    monkeypatch.setattr(intake_mod.at, "list_records", fake_list)
    monkeypatch.setattr(intake_mod.at, "create_record", fake_create)
    intake_mod._HITS.clear()
    CREATED.clear()
    yield


def _page(name):
    return open(os.path.join(ROOT, "app", "ui", name)).read()


# ---------------- money: the server decides, not the browser ----------------

def test_promo_preview_endpoint_agrees_with_the_seeded_code():
    r = client.get("/v0/promo/WELCOME10", params={"subtotal_cents": 2000})
    assert r.status_code == 200
    d = r.json()
    assert d["valid"] is True
    assert d["discount_cents"] == 200          # 10% of $20.00


def test_promo_preview_rejects_a_code_that_does_not_exist():
    assert client.get("/v0/promo/NOTAREALCODE",
                      params={"subtotal_cents": 2000}).json()["valid"] is False


def test_promo_never_exceeds_the_subtotal():
    """A discount can zero an order. It can never make GateWay owe the customer."""
    db = SessionLocal()
    try:
        if not db.get(PromoCode, "BIGCENTS"):
            db.add(PromoCode(code="BIGCENTS", kind="cents", value=9999,
                             description="Absurd fixed discount"))
            db.commit()
    finally:
        db.close()
    d = client.get("/v0/promo/BIGCENTS", params={"subtotal_cents": 1000}).json()
    assert d["discount_cents"] == 1000          # clamped to the subtotal, not 9999


def test_referral_code_shape_is_honored_and_capped():
    d = client.get("/v0/promo/GW-AB12", params={"subtotal_cents": 10000}).json()
    assert d["valid"] is True
    assert d["discount_cents"] == 1500          # 20% of $100 = $20, capped at $15


def test_hostile_client_cannot_invent_a_discount():
    """THE ONE THAT MATTERS. A tampered form posts a $500 discount on a $20 order
    with no promo code at all. The server must ignore it — otherwise the driver
    collects the wrong cash at the door."""
    r = client.get("/v0/intake", params={
        "customer_name": "Hostile", "customer_phone": "8655550100",
        "pickup_address": "1 Demo St", "dropoff_address": "2 Demo St",
        "items_description": "1x Burger", "subtotal_cents": "2000",
        "fee_cents": "399", "tip_cents": "0",
        "discount_cents": "50000",              # <-- the attack
        "total_cents": "1",                     # <-- and the lie it enables
    })
    assert r.status_code in (200, 201)
    # The server recomputed: 2000 + 399 + 0 tip - 0 discount = 2399. NOT the 1 the
    # client claimed, and NOT a $500 discount it never earned.
    fields = CREATED[-1]
    assert fields["total_cents"] == 2399
    assert int(fields.get("discount_cents") or 0) == 0


def test_a_real_promo_is_applied_by_the_server_not_the_client():
    r = client.get("/v0/intake", params={
        "customer_name": "Honest", "customer_phone": "8655550101",
        "pickup_address": "1 Demo St", "dropoff_address": "3 Demo St",
        "items_description": "1x Plate", "subtotal_cents": "2000",
        "fee_cents": "399", "tip_cents": "300",
        "promo_code": "welcome10",              # lowercase — server normalizes
        "discount_cents": "99999",              # client lies; server overrules
        "total_cents": "1",
    })
    assert r.status_code in (200, 201)
    fields = CREATED[-1]
    assert fields["discount_cents"] == 200      # server's 10%, not the client's
    assert fields["total_cents"] == 2000 + 399 + 300 - 200


def test_tip_is_computed_on_the_pre_discount_subtotal():
    """A coupon is GateWay's gift to the customer. It must never come out of the
    driver's tip."""
    form = _page("order-form.html")
    assert "TIP_CENTS = Math.round(sub * TIP_PCT / 100)" in form
    assert "sub - DISCOUNT_CENTS) * TIP_PCT" not in form


# ---------------- the cart bar the founder missed ----------------

def test_cart_bar_is_fixed_not_trapped_inside_the_menu():
    """v1.0 regression: the bar was position:sticky INSIDE #menuZone, so it
    vanished the moment you scrolled past the menu. It must float over the page."""
    form = _page("order-form.html")
    assert ".cartbar{position:fixed" in form
    assert "position:sticky;bottom:12px;background:#16337a" not in form


def test_cart_bar_shows_the_whole_money_story():
    form = _page("order-form.html")
    for needle in ("cbSub", "cbFee", "cbTip", "cbDisc", "cartTot", "Review order"):
        assert needle in form


# ---------------- the branded storefront splash ----------------

def test_order_form_has_a_branded_splash():
    form = _page("order-form.html")
    assert 'id="splash"' in form
    assert "paintSplash" in form
    assert "brand_color" in form


def test_splash_falls_back_to_gateway_when_the_merchant_has_no_brand():
    form = _page("order-form.html")
    assert "/static/gwd-emblem.png" in form
    assert "Powered by GateWay" in form


def test_partner_api_exposes_the_brand_layer():
    """The splash and the food court both read these. If the API stops sending
    them, both surfaces silently go generic."""
    d = client.get("/v0/partners").json()["partners"]
    assert d, "no partners in the directory"
    for key in ("cuisine", "tagline", "brand_color", "featured", "demo"):
        assert key in d[0], f"partner directory dropped '{key}'"


# ---------------- the food court ----------------

def test_home_is_a_food_court_not_a_landing_page():
    html = client.get("/").text
    for needle in ("chips", "featured", "CAT_ICON", "paintFeatured", "Featured kitchens"):
        assert needle in html


def test_demo_merchants_fill_out_the_categories():
    """Until real merchants sign each category, demo rows keep the marketplace
    from looking empty — and they carry a PREVIEW badge so nobody is misled."""
    partners = client.get("/v0/partners").json()["partners"]
    cuisines = {p["cuisine"] for p in partners if p["cuisine"]}
    assert len(cuisines) >= 5, f"food court is thin: {cuisines}"
    assert any(p["demo"] for p in partners)
    assert "PREVIEW" in client.get("/").text


def test_real_pilots_are_never_marked_demo():
    partners = {p["code"]: p for p in client.get("/v0/partners").json()["partners"]}
    for code in ("burgerboys", "friendsbbq", "stephens"):
        if code in partners:
            assert partners[code]["demo"] is False, f"{code} is a REAL kitchen"


def test_home_has_empty_states_that_dont_leave_a_blank_screen():
    html = client.get("/").text
    assert "The kitchens are warming up" in html      # nothing loaded
    assert "We couldn't load the kitchens" in html    # fetch failed
    assert "No kitchens here yet" in html             # category is empty


# ---------------- growth surfaces ----------------

def test_team_page_carries_the_codes_the_home_gave_up():
    t = client.get("/team")
    assert t.status_code == 200
    for needle in ("Driver day code", "Kitchen code", "Dispatch key", "Driver Hub"):
        assert needle in t.text


def test_driver_lead_is_captured():
    r = client.post("/v0/leads", json={"kind": "driver", "name": "Jordan Ellis",
                                       "phone": "8655550100", "message": "weekends"})
    assert r.status_code == 201
    db = SessionLocal()
    try:
        assert db.query(Lead).filter(Lead.kind == "driver",
                                     Lead.name == "Jordan Ellis").count() == 1
    finally:
        db.close()


def test_merchant_lead_is_captured():
    r = client.post("/v0/leads", json={"kind": "merchant", "name": "Phillip Lim",
                                       "phone": "8655550111", "message": "Asia Cafe"})
    assert r.status_code == 201


def test_a_lead_with_no_way_to_reach_them_is_rejected():
    r = client.post("/v0/leads", json={"kind": "driver", "name": "Ghost"})
    assert r.status_code == 422


def test_support_ticket_reaches_a_human():
    r = client.post("/v0/support", json={"name": "Neighbor", "phone": "8655550102",
                                         "order_id": "ORD-ABC12345",
                                         "message": "My order never arrived."})
    assert r.status_code == 201
    db = SessionLocal()
    try:
        t = db.query(SupportTicket).order_by(SupportTicket.created_at.desc()).first()
        assert t.message == "My order never arrived."
        assert t.status == "open"
    finally:
        db.close()


def test_an_empty_support_message_is_rejected():
    assert client.post("/v0/support", json={"message": ""}).status_code == 422


# ---------------- a stranger must not read the founder's inbox ----------------

def test_leads_and_tickets_are_key_gated():
    assert client.get("/v0/leads").status_code == 422           # no key at all
    assert client.get("/v0/leads", params={"key": "guess"}).status_code == 403
    assert client.get("/v0/support-tickets",
                      params={"key": "guess"}).status_code == 403


def test_pages_render():
    for path in ("/support", "/drive-with-us", "/partner-with-us", "/team"):
        assert client.get(path).status_code == 200, path


# ---------------- naming (the founder's ear) ----------------

def test_the_driver_surface_is_called_the_driver_hub():
    d = client.get("/driver/anytoken").text
    assert "Driver Hub" in d
    assert "Day Sheet" not in d


def test_the_merchant_surface_is_called_merchant():
    assert "Merchant" in client.get("/kitchen/anytoken").text


def test_no_surface_lost_its_body_tag():
    """A regex backreference once leaked a literal '\\1' where <body> belonged on
    FIVE surfaces. Browsers silently recover; tests should not."""
    for name in ("home.html", "board.html", "driver.html", "kitchen.html",
                 "order-form.html", "me.html", "team.html", "support.html",
                 "lead-driver.html", "lead-merchant.html"):
        html = _page(name)
        assert "<body>" in html, f"{name} has no <body>"
        assert "\\1" not in html, f"{name} still has the leaked backreference"


# ---------------- abuse: the founder's inbox is a real inbox ----------------

def test_a_bot_cannot_bury_a_real_merchant_under_fake_leads():
    """If a script can post 10,000 fake leads, the ONE message from a restaurant
    owner who actually wants in gets buried. Throttling this protects a
    relationship, not just a table."""
    from app import growth as growth_mod
    growth_mod._LEAD_HITS.clear()
    codes = []
    for i in range(9):
        r = client.post("/v0/leads", json={"kind": "merchant", "name": f"Bot {i}",
                                           "phone": "8655550100"},
                        headers={"x-forwarded-for": "9.9.9.9"})
        codes.append(r.status_code)
    assert 429 in codes, "a bot could flood the founder's inbox unchecked"
    growth_mod._LEAD_HITS.clear()


def test_a_real_person_filling_the_form_once_is_never_throttled():
    from app import growth as growth_mod
    growth_mod._LEAD_HITS.clear()
    r = client.post("/v0/leads", json={"kind": "merchant", "name": "Phillip Lim",
                                       "phone": "8655550111"},
                    headers={"x-forwarded-for": "7.7.7.7"})
    assert r.status_code == 201
    growth_mod._LEAD_HITS.clear()


def test_referral_codes_cannot_be_brute_forced():
    from app import growth as growth_mod
    growth_mod._PROMO_HITS.clear()
    codes = [client.get(f"/v0/promo/GW-{i:04d}", params={"subtotal_cents": 2000},
                        headers={"x-forwarded-for": "6.6.6.6"}).status_code
             for i in range(25)]
    assert 429 in codes, "the referral-code space was brute-forceable"
    growth_mod._PROMO_HITS.clear()


def test_promo_ignores_a_negative_subtotal():
    """A negative subtotal must never produce a 'discount' that pays the customer."""
    d = client.get("/v0/promo/WELCOME10", params={"subtotal_cents": -9999}).json()
    assert d["valid"] is False
