"""v1.4 — ITEM OPTIONS + SERVER-AUTHORITATIVE CART.

Researched from Asia Cafe's own real menu: entrees are priced 'Chicken $13.05+,
Steak $14.05+, Shrimp $15.05+' because the protein is a REQUIRED CHOICE that
changes the price. Before this, GateWay's ordering flow only captured quantity —
it silently dropped the thing the restaurant's own menu treats as the point of
the item.

The load-bearing test is test_hostile_cart_cannot_underpay: exactly the same
posture as the v1.1 promo fix, now applied to the whole cart.
"""
import json
import os

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import SessionLocal
from app.models import MenuItem, OptionChoice, OptionGroup, Partner
import app.intake as intake_mod

client = TestClient(app)
KEY = os.environ.get("ADMIN_KEY", "test-key")
ROOT = os.path.join(os.path.dirname(__file__), "..")

CREATED = []


async def fake_list(table, formula="", fields=None, max_records=100):
    return []


async def fake_create(table, fields):
    CREATED.append(fields)
    return {"id": "recOPT", "fields": fields}


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    monkeypatch.setattr(intake_mod.at, "list_records", fake_list)
    monkeypatch.setattr(intake_mod.at, "create_record", fake_create)
    intake_mod._HITS.clear()
    CREATED.clear()
    yield


@pytest.fixture
def _item_with_protein_options():
    """A hibachi entree with a required 'Choose your protein' group — exactly
    Asia Cafe's real pricing pattern: Chicken (no charge), Steak (+$1), Shrimp (+$2)."""
    db = SessionLocal()
    try:
        item = MenuItem(partner_code="burgerboys", category="Test",
                        name="Hibachi Test Plate", price_cents=1305, available=True)
        db.add(item)
        db.commit()
        g = OptionGroup(item_id=item.id, name="Choose your protein",
                        min_select=1, max_select=1, sort=0)
        db.add(g)
        db.commit()
        db.add(OptionChoice(group_id=g.id, name="Chicken", price_delta_cents=0,
                            is_default=True, sort=0))
        db.add(OptionChoice(group_id=g.id, name="Steak", price_delta_cents=100, sort=1))
        db.add(OptionChoice(group_id=g.id, name="Shrimp", price_delta_cents=200, sort=2))
        db.commit()
        item_id, group_id = item.id, g.id
    finally:
        db.close()
    yield item_id, group_id
    db = SessionLocal()
    try:
        db.query(OptionChoice).filter(OptionChoice.group_id == group_id).delete()
        db.query(OptionGroup).filter(OptionGroup.id == group_id).delete()
        it = db.get(MenuItem, item_id)
        if it:
            db.delete(it)
        db.commit()
    finally:
        db.close()


# ---------------- options appear on the public menu ----------------

def test_option_groups_appear_on_the_public_menu(_item_with_protein_options):
    item_id, _ = _item_with_protein_options
    m = client.get("/v0/partners/burgerboys/menu").json()
    found = None
    for cat in m["categories"]:
        for it in cat["items"]:
            if it["id"] == item_id:
                found = it
    assert found is not None
    assert found["options"][0]["name"] == "Choose your protein"
    names = {c["name"] for c in found["options"][0]["choices"]}
    assert names == {"Chicken", "Steak", "Shrimp"}


def test_86d_choices_are_hidden_from_the_public_menu(_item_with_protein_options):
    item_id, group_id = _item_with_protein_options
    choice = SessionLocal().query(OptionChoice).filter(
        OptionChoice.group_id == group_id, OptionChoice.name == "Shrimp").first()
    r = client.patch(f"/api/board/{KEY}/option-choices/{choice.id}",
                     json={"available": False})
    assert r.status_code == 200
    m = client.get("/v0/partners/burgerboys/menu").json()
    for cat in m["categories"]:
        for it in cat["items"]:
            if it["id"] == item_id:
                names = {c["name"] for c in it["options"][0]["choices"]}
                assert "Shrimp" not in names


# ---------------- server-authoritative pricing ----------------

def test_hostile_cart_cannot_underpay(_item_with_protein_options):
    """THE ONE THAT MATTERS. A tampered client claims $0.01 for two Shrimp
    Hibachi plates ($15.05 each = $30.10). The server must recompute from the
    database, exactly like the v1.1 promo-discount fix."""
    item_id, group_id = _item_with_protein_options
    shrimp = SessionLocal().query(OptionChoice).filter(
        OptionChoice.group_id == group_id, OptionChoice.name == "Shrimp").first()
    r = client.post("/v0/intake", json={
        "dropoff_address": "1 Test St", "items_description": "2x Hibachi",
        "partner": "burgerboys", "subtotal_cents": "1",
        "cart_json": json.dumps([{"item_id": item_id, "qty": 2,
                                  "choice_ids": [shrimp.id]}]),
    })
    assert r.status_code in (200, 201)
    assert CREATED[-1]["subtotal_cents"] == (1305 + 200) * 2


def test_required_option_group_cannot_be_skipped(_item_with_protein_options):
    """The protein choice is REQUIRED (min_select=1) — exactly like Asia Cafe's
    own menu. An order with no protein selected must be rejected, not silently
    priced at the base rate."""
    item_id, _ = _item_with_protein_options
    r = client.post("/v0/intake", json={
        "dropoff_address": "1 Test St", "items_description": "1x Hibachi, no protein",
        "partner": "burgerboys",
        "cart_json": json.dumps([{"item_id": item_id, "qty": 1, "choice_ids": []}]),
    })
    assert r.status_code == 422
    assert "protein" in r.json()["detail"].lower()


def test_error_reaches_the_customer_as_422_not_a_swallowed_503(_item_with_protein_options):
    """A real bug caught in this pass: the cart-validation HTTPException was
    originally raised INSIDE the broad except-Exception block and got turned
    into a generic 'something went wrong' 503. It must surface as its real
    status code and message."""
    r = client.post("/v0/intake", json={
        "dropoff_address": "1 Test St", "items_description": "ghost",
        "partner": "burgerboys",
        "cart_json": json.dumps([{"item_id": "not-a-real-item-id", "qty": 1}]),
    })
    assert r.status_code == 422
    assert r.json()["detail"] != "intake_failed"


def test_an_option_cannot_carry_a_negative_price(_item_with_protein_options):
    """An option must only ever ADD cost. A negative delta would let a
    'modifier' function as an undocumented discount."""
    r = client.post(f"/api/board/{KEY}/menu-items/{_item_with_protein_options[0]}/options",
                    json={"name": "Sneaky", "choices": [
                        {"name": "Discount", "price_delta_cents": -500}]})
    assert r.status_code == 422


def test_cart_item_must_belong_to_the_claimed_kitchen(_item_with_protein_options):
    """A cart claiming partner=friendsbbq but pointing at a Burger Boys item
    must be rejected — otherwise a customer could checkout at one kitchen using
    another kitchen's (possibly cheaper) item ids."""
    item_id, _ = _item_with_protein_options
    r = client.post("/v0/intake", json={
        "dropoff_address": "1 Test St", "items_description": "cross-kitchen",
        "partner": "friendsbbq",
        "cart_json": json.dumps([{"item_id": item_id, "qty": 1, "choice_ids": []}]),
    })
    assert r.status_code == 422


def test_86d_menu_item_cannot_be_ordered_via_cart(_item_with_protein_options):
    item_id, _ = _item_with_protein_options
    db = SessionLocal()
    try:
        db.get(MenuItem, item_id).available = False
        db.commit()
    finally:
        db.close()
    r = client.post("/v0/intake", json={
        "dropoff_address": "1 Test St", "items_description": "86d item",
        "partner": "burgerboys",
        "cart_json": json.dumps([{"item_id": item_id, "qty": 1, "choice_ids": []}]),
    })
    assert r.status_code == 422


def test_cart_line_count_is_capped():
    """A cart with hundreds of lines must not be processed as-is — this is an
    abuse surface, not a real order."""
    src = open(os.path.join(ROOT, "app", "intake.py")).read()
    assert "cart[:60]" in src


# ---------------- board authoring ----------------

def test_board_can_create_an_option_group_with_choices_in_one_call():
    item = MenuItem(partner_code="burgerboys", category="Test",
                    name="Board Option Test", price_cents=1000, available=True)
    db = SessionLocal()
    try:
        db.add(item)
        db.commit()
        item_id = item.id
    finally:
        db.close()
    try:
        r = client.post(f"/api/board/{KEY}/menu-items/{item_id}/options", json={
            "name": "Spice level", "min_select": 1, "max_select": 1,
            "choices": [{"name": "Mild", "is_default": True},
                       {"name": "Hot", "price_delta_cents": 0}]})
        assert r.status_code == 200
        got = client.get(f"/api/board/{KEY}/menu-items/{item_id}/options").json()
        assert got["groups"][0]["name"] == "Spice level"
        assert len(got["groups"][0]["choices"]) == 2
    finally:
        db2 = SessionLocal()
        try:
            db2.get(MenuItem, item_id) and db2.delete(db2.get(MenuItem, item_id))
            db2.commit()
        finally:
            db2.close()


def test_options_are_key_gated_on_the_board():
    assert client.post("/api/board/guess/menu-items/x/options",
                       json={"name": "x"}).status_code == 403


# ---------------- kitchen can 86 a single choice ----------------

def test_kitchen_can_86_a_single_choice_they_ran_out_of(_item_with_protein_options):
    """'We're out of shrimp today' is a real, common kitchen moment — narrower
    than 86ing the whole dish."""
    item_id, group_id = _item_with_protein_options
    db = SessionLocal()
    try:
        db.get(Partner, "burgerboys")
        shrimp = db.query(OptionChoice).filter(
            OptionChoice.group_id == group_id, OptionChoice.name == "Shrimp").first()
        shrimp_id = shrimp.id
    finally:
        db.close()
    tok = SessionLocal().query(Partner).filter(Partner.code == "burgerboys").first().portal_token
    r = client.post(f"/api/kitchen/{tok}/option-choices/{shrimp_id}/86",
                    json={"available": False})
    assert r.status_code == 200
    m = client.get("/v0/partners/burgerboys/menu").json()
    for cat in m["categories"]:
        for it in cat["items"]:
            if it["id"] == item_id:
                names = {c["name"] for c in it["options"][0]["choices"]}
                assert "Shrimp" not in names
