"""v1.3 — SEARCH THE WHOLE MARKETPLACE, 86 FROM THE KITCHEN.

Both close a real gap: a customer shouldn't have to guess which restaurant sells
burgers, and a cook whose shrimp just ran out shouldn't need the board key to say
so.
"""
import os

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import SessionLocal
from app.models import MenuItem, Partner

client = TestClient(app)
ROOT = os.path.join(os.path.dirname(__file__), "..")


def _page(name):
    return open(os.path.join(ROOT, "app", "ui", name)).read()


# ---------------- marketplace search ----------------

def test_search_finds_a_dish_regardless_of_which_merchant_page_youre_on():
    d = client.get("/v0/search", params={"q": "burger"}).json()
    names = [i["name"] for i in d["items"]]
    assert any("Burger" in n or "burger" in n.lower() for n in names), names


def test_search_finds_kitchens_by_cuisine_not_just_name():
    d = client.get("/v0/search", params={"q": "bbq"}).json()
    codes = [m["code"] for m in d["merchants"]]
    assert "friendsbbq" in codes


def test_search_never_surfaces_a_paused_kitchen():
    db = SessionLocal()
    try:
        p = db.get(Partner, "burgerboys")
        was = p.accepting_orders
        p.accepting_orders = False
        db.commit()
    finally:
        db.close()
    try:
        d = client.get("/v0/search", params={"q": "burger"}).json()
        assert "burgerboys" not in [m["code"] for m in d["merchants"]]
        assert all(i["partner_code"] != "burgerboys" for i in d["items"])
    finally:
        db2 = SessionLocal()
        try:
            db2.get(Partner, "burgerboys").accepting_orders = was
            db2.commit()
        finally:
            db2.close()


def test_search_never_surfaces_an_86d_item():
    db = SessionLocal()
    try:
        item = (db.query(MenuItem)
                .filter(MenuItem.partner_code == "burgerboys",
                        MenuItem.name.ilike("%Kobe%")).first())
        assert item is not None
        item.available = False
        db.commit()
        item_id = item.id
    finally:
        db.close()
    try:
        d = client.get("/v0/search", params={"q": "kobe"}).json()
        assert all(i["id"] != item_id for i in d["items"])
    finally:
        db2 = SessionLocal()
        try:
            db2.get(MenuItem, item_id).available = True
            db2.commit()
        finally:
            db2.close()


def test_search_requires_at_least_two_characters():
    """A single keystroke must not fire a query across the whole database."""
    d = client.get("/v0/search", params={"q": "b"}).json()
    assert d["merchants"] == [] and d["items"] == []


def test_search_is_immune_to_injection():
    d = client.get("/v0/search", params={"q": "%' OR '1'='1"})
    assert d.status_code == 200
    assert len(d.json()["items"]) < 50   # did not dump the whole table


def test_home_has_a_real_search_box():
    home = _page("home.html")
    assert 'id="gsInput"' in home
    assert "runSearch" in home and "/v0/search" in home


def test_search_results_replace_the_browse_view_not_stack_under_it():
    """Founder-style bug class: a results panel that doesn't hide the browse
    view underneath makes the page feel broken, not helpful."""
    home = _page("home.html")
    assert "showBrowse" in home
    assert "browseWrap" in home


# ---------------- kitchen-scoped 86 ----------------

TOKEN = "kt-undotest"     # reuses the fixture kitchen from test_undo_back_inbox


@pytest.fixture
def _menu_item():
    db = SessionLocal()
    try:
        if not db.get(Partner, "undokitchen"):
            db.add(Partner(code="undokitchen", display_name="Undo Kitchen",
                           status="pilot", portal_token=TOKEN))
            db.commit()
        item = MenuItem(partner_code="undokitchen", category="Test",
                        name="Test Plate", price_cents=899, available=True)
        db.add(item)
        db.commit()
        iid = item.id
    finally:
        db.close()
    yield iid
    db = SessionLocal()
    try:
        it = db.get(MenuItem, iid)
        if it:
            db.delete(it)
            db.commit()
    finally:
        db.close()


def test_a_cook_can_86_an_item_with_their_own_kitchen_token(_menu_item):
    r = client.post(f"/api/kitchen/{TOKEN}/menu-items/{_menu_item}/86",
                    json={"available": False})
    assert r.status_code == 200
    assert r.json()["available"] is False


def test_an_86d_item_disappears_from_the_public_menu(_menu_item):
    """The public endpoint only ever returns available items — this is the
    fixture's ONLY item, so 86'ing it correctly empties the menu to a 404.
    Add a second always-available item to prove the 86'd one specifically
    is what's missing, not that the whole menu vanished."""
    db = SessionLocal()
    try:
        db.add(MenuItem(partner_code="undokitchen", category="Test",
                        name="Always Available", price_cents=500, available=True))
        db.commit()
    finally:
        db.close()
    client.post(f"/api/kitchen/{TOKEN}/menu-items/{_menu_item}/86", json={"available": False})
    m = client.get("/v0/partners/undokitchen/menu").json()
    all_items = [i["id"] for c in m["categories"] for i in c["items"]]
    assert _menu_item not in all_items
    assert any(i["name"] == "Always Available" for c in m["categories"] for i in c["items"])


def test_a_cook_can_bring_an_item_back(_menu_item):
    client.post(f"/api/kitchen/{TOKEN}/menu-items/{_menu_item}/86", json={"available": False})
    r = client.post(f"/api/kitchen/{TOKEN}/menu-items/{_menu_item}/86", json={"available": True})
    assert r.json()["available"] is True


def test_a_kitchen_cannot_86_another_kitchens_item(_menu_item):
    r = client.post(f"/api/kitchen/kt-other-fake-token/menu-items/{_menu_item}/86",
                    json={"available": False})
    assert r.status_code == 404


def test_the_86_endpoint_cannot_touch_price_or_name(_menu_item):
    """This is a one-job endpoint. It must not become a backdoor for a kitchen
    token to rewrite its own prices without going through the board."""
    src = open(os.path.join(ROOT, "app", "menu.py")).read()
    fn = src[src.index("kitchen_toggle_86"):src.index("kitchen_toggle_86") + 900]
    assert "price_cents" not in fn
    assert "item.name =" not in fn


def test_kitchen_ui_offers_86_without_the_board_key():
    k = _page("kitchen.html")
    assert "show86" in k and "toggle86" in k
    assert "86 an item" in k
