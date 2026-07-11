"""Favorite/reorder profile surfaces + kitchen load signal & slammed mode."""
import datetime as _dt
import pytest
from fastapi.testclient import TestClient
import app.airtable_client as at
import app.kitchen as kitchen_mod
from app.db import SessionLocal
from app.models import Partner
from app.main import app
from tests.fake_airtable import FakeAirtable

client = TestClient(app)
fake = FakeAirtable()
TODAY = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    monkeypatch.setattr(at, "list_records", fake.list_records)
    monkeypatch.setattr(kitchen_mod.at, "list_records", fake.list_records)
    yield


def _seed(partner, n, status="received"):
    for i in range(n):
        fake.seed(at.ORDERS, {"order_id": f"ORD-{partner}-{status}-{i}", "status": status,
                              "partner_code": partner, "items_description": "x",
                              "received_at": f"{TODAY}T12:{i:02d}:00.000Z"})


def _tok(code):
    db = SessionLocal(); t = db.get(Partner, code).portal_token; db.close(); return t


def test_kitchen_load_steady_busy_slammed():
    _seed("stephens", 2)               # steady (<4)
    d = client.get(f"/api/kitchen/{_tok('stephens')}/orders").json()
    assert d["load"] == "steady"
    _seed("burgerboys", 5)             # busy (4-7)
    d = client.get(f"/api/kitchen/{_tok('burgerboys')}/orders").json()
    assert d["load"] == "busy"
    _seed("friendsbbq", 8)             # slammed (>=8)
    d = client.get(f"/api/kitchen/{_tok('friendsbbq')}/orders").json()
    assert d["load"] == "slammed"
    assert d["in_kitchen_now"] == 8


def test_kitchen_page_has_slammed_controls():
    html = client.get(f"/kitchen/{_tok('stephens')}").text
    assert "pauseFifteen" in html and "gw_kitchen_resume" in html and "loadBanner" in html


def test_home_and_me_have_reorder_surfaces():
    assert "quickReorder" in client.get("/").text
    me = client.get("/me").text
    assert "toggleFav" in me
    prof = client.get("/static/gw-profile.js").text
    assert "topKitchen" in prof and "setFavorite" in prof
