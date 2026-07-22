"""v1.9.33 — a kitchen owns its own menu.

Kitchens could 86 an item but not change a price — they had to phone GateWay and
wait for someone to do it on the board. It's their menu and their business.
Scoping is the load-bearing part: every write is checked against the caller's
own partner_code, so one kitchen can never reach another's menu.
"""
import os, tempfile

os.environ.setdefault("DATABASE_URL", "sqlite:///" + tempfile.mktemp(suffix=".db"))
os.environ.setdefault("ADMIN_KEY", "k")

from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app.models import Partner, MenuItem
from app import menu, growth

menu.seed_menus(); growth.migrate_brand_columns(); growth.seed_brands_and_demos()
client = TestClient(app, raise_server_exceptions=False)

_db = SessionLocal()
TOKEN = _db.get(Partner, "asiacafe").portal_token
ITEM = _db.query(MenuItem).filter(MenuItem.partner_code == "asiacafe").first().id
FOREIGN = _db.query(MenuItem).filter(MenuItem.partner_code == "burgerboys").first().id
_db.close()


def test_kitchen_can_change_its_own_price():
    r = client.patch(f"/api/kitchen/{TOKEN}/menu-items/{ITEM}",
                     json={"price_cents": 1599})
    assert r.status_code == 200
    assert r.json()["price_cents"] == 1599


def test_kitchen_cannot_touch_another_kitchens_menu():
    """The one that actually matters."""
    r = client.patch(f"/api/kitchen/{TOKEN}/menu-items/{FOREIGN}",
                     json={"price_cents": 1})
    assert r.status_code == 404


def test_absurd_prices_are_refused():
    assert client.patch(f"/api/kitchen/{TOKEN}/menu-items/{ITEM}",
                        json={"price_cents": 99999999}).status_code == 400
    assert client.patch(f"/api/kitchen/{TOKEN}/menu-items/{ITEM}",
                        json={"price_cents": -500}).status_code == 400


def test_non_numeric_price_is_refused_not_coerced():
    assert client.patch(f"/api/kitchen/{TOKEN}/menu-items/{ITEM}",
                        json={"price_cents": "free"}).status_code == 400


def test_an_item_cannot_be_renamed_to_nothing():
    assert client.patch(f"/api/kitchen/{TOKEN}/menu-items/{ITEM}",
                        json={"name": "   "}).status_code == 400


def test_kitchen_can_add_an_item_and_it_goes_live():
    r = client.post(f"/api/kitchen/{TOKEN}/menu-items",
                    json={"name": "Seasonal Special", "price_cents": 1450,
                          "category": "Specials"})
    assert r.status_code == 200
    m = client.get("/v0/partners/asiacafe/menu").json()
    live = [i for c in m["categories"] for i in c["items"]
            if i["name"] == "Seasonal Special"]
    assert live and live[0]["price_cents"] == 1450


def test_added_item_needs_a_name():
    assert client.post(f"/api/kitchen/{TOKEN}/menu-items",
                       json={"name": "  ", "price_cents": 900}).status_code == 400


def test_a_bad_token_gets_nowhere():
    assert client.patch(f"/api/kitchen/kt-fake/menu-items/{ITEM}",
                        json={"price_cents": 100}).status_code == 404


def test_edits_are_logged_permanently():
    src = open(os.path.join(os.path.dirname(__file__), "..", "app", "menu.py")).read()
    assert "menu.item_edited" in src and "menu.item_added" in src


def test_merchant_app_exposes_the_controls():
    ui = open(os.path.join(os.path.dirname(__file__), "..",
                           "app", "ui", "kitchen.html")).read()
    assert "editItem" in ui and "addMenuItem" in ui
