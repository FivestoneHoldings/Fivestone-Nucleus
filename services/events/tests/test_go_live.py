"""GO-LIVE — can this merchant actually take an order?

A partner can sit in the registry for weeks, invisible to every customer, and
nobody knows why. That is the gap between "Asia Cafe is onboarded" and "Asia Cafe
can take an order Monday." These tests hold that line.
"""
import os

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import SessionLocal
from app.models import MenuItem, Partner

client = TestClient(app)
KEY = os.environ.get("ADMIN_KEY", "test-key")
ROOT = os.path.join(os.path.dirname(__file__), "..")

CODE = "golivetest"


@pytest.fixture(autouse=True)
def _fresh():
    db = SessionLocal()
    try:
        db.query(MenuItem).filter(MenuItem.partner_code == CODE).delete()
        p = db.get(Partner, CODE)
        if p:
            db.delete(p)
        db.commit()
        db.add(Partner(code=CODE, display_name="Go Live Test", status="pilot",
                       portal_token="kt-golive"))
        db.commit()
    finally:
        db.close()
    yield


def _check():
    return client.get(f"/api/board/{KEY}/partners/{CODE}/go-live").json()


def _add_item(price=899):
    db = SessionLocal()
    try:
        db.add(MenuItem(partner_code=CODE, category="Menu", name="Test Plate",
                        price_cents=price, available=True))
        db.commit()
    finally:
        db.close()


def _set(**kw):
    db = SessionLocal()
    try:
        p = db.get(Partner, CODE)
        for k, v in kw.items():
            setattr(p, k, v)
        db.commit()
    finally:
        db.close()


# ---------------- the blocking truths ----------------

def test_a_merchant_with_no_menu_is_hidden_and_the_board_says_so():
    """THE ONE THAT MATTERS FOR MONDAY. Asia Cafe was sitting in the registry with
    no menu — invisible to every customer, with nothing anywhere saying why."""
    d = _check()
    assert d["visible_to_customers"] is False
    assert "menu" in d["blocking"]
    assert d["code"] not in [p["code"] for p in
                             client.get("/v0/partners").json()["partners"]]


def test_no_pickup_address_blocks_go_live():
    _add_item()
    assert "address" in _check()["blocking"]


def test_an_unpriced_item_blocks_go_live():
    """A $0.00 item WILL be ordered, and the driver will collect $0 at the door.
    That is a real loss to a real kitchen — it must block."""
    _add_item(price=0)
    _set(address="1 Real St, Knoxville, TN")
    d = _check()
    assert "priced" in d["blocking"]
    assert d["visible_to_customers"] is False


def test_a_paused_kitchen_is_not_go_live():
    _add_item()
    _set(address="1 Real St", accepting_orders=False)
    assert "accepting" in _check()["blocking"]


def test_a_fully_set_up_merchant_goes_live_and_appears_to_customers():
    _add_item()
    _set(address="1 Real St, Knoxville, TN", accepting_orders=True,
         cuisine="Asian", brand_color="#c0392b", tagline="Neighborhood Asian kitchen")
    d = _check()
    assert d["visible_to_customers"] is True, d["blocking"]
    assert d["blocking"] == []
    codes = [p["code"] for p in client.get("/v0/partners").json()["partners"]]
    assert CODE in codes, "checklist said LIVE but the customer still can't see them"


def test_brand_gaps_warn_but_never_block():
    """Missing brand means a generic splash and no category chip — bad, but it
    must not stop a hungry neighbor from ordering food tonight."""
    _add_item()
    _set(address="1 Real St", accepting_orders=True)
    d = _check()
    assert d["visible_to_customers"] is True
    ids = {c["id"]: c for c in d["checks"]}
    assert ids["brand"]["ok"] is False
    assert ids["brand"]["blocking"] is False


def test_the_checklist_tells_you_how_to_fix_every_gap():
    """A checklist that says 'no' without saying 'how' is just a complaint."""
    for c in _check()["checks"]:
        assert c["fix"], f"check '{c['id']}' has no fix instructions"


def test_go_live_hands_over_the_two_links_a_launch_actually_needs():
    d = _check()
    assert d["order_link"] == f"/order?partner={CODE}"
    assert d["kitchen_link"].startswith("/kitchen/")


# ---------------- brand editing ----------------

def test_the_board_can_set_a_merchants_brand():
    r = client.post(f"/api/board/{KEY}/partners", json={
        "code": CODE, "display_name": "Go Live Test", "cuisine": "Asian",
        "tagline": "Knoxville's neighborhood Asian kitchen", "brand_color": "#c0392b"})
    assert r.status_code == 200
    p = client.get(f"/v0/partners/{CODE}").json()
    assert p["cuisine"] == "Asian"
    assert p["brand_color"] == "#c0392b"
    assert "neighborhood Asian" in p["tagline"]


def test_board_partner_list_carries_the_brand_so_the_editor_can_prefill():
    rows = {p["code"]: p for p in
            client.get(f"/api/board/{KEY}/partners").json()["partners"]}
    assert "cuisine" in rows[CODE] and "brand_color" in rows[CODE]


def test_go_live_is_key_gated():
    assert client.get(f"/api/board/guess/partners/{CODE}/go-live").status_code == 403


def test_board_surfaces_the_go_live_check():
    b = open(os.path.join(ROOT, "app", "ui", "board.html")).read()
    assert "goLive" in b and "go-live" in b
    assert "HIDDEN from customers" in b
    assert "editBrand" in b
