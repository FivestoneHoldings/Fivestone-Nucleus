"""v1.1 UNDO, BACK, INBOX.

The load-bearing test here is test_kitchen_cannot_undo_once_the_driver_has_the_food:
undo is a mercy for a slipped thumb, not a time machine. Once a driver is holding
the bag, the kitchen does not get to rewrite where that food is.
"""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import SessionLocal
from app.models import Event, Partner
from app import kitchen as kitchen_mod
import app.airtable_client as at

client = TestClient(app)
ROOT = os.path.join(os.path.dirname(__file__), "..")

TOKEN = "kt-undotest"
CODE = "undokitchen"
ORDERS_ROWS = []


def _page(name):
    return open(os.path.join(ROOT, "app", "ui", name)).read()


async def fake_list(table, formula="", fields=None, max_records=100):
    return list(ORDERS_ROWS)


@pytest.fixture(autouse=True)
def _kitchen(monkeypatch):
    db = SessionLocal()
    try:
        if not db.get(Partner, CODE):
            db.add(Partner(code=CODE, display_name="Undo Kitchen",
                           status="pilot", portal_token=TOKEN))
            db.commit()
        db.query(Event).filter(Event.entity_ref == "ORD-UNDO0001").delete()
        db.commit()
    finally:
        db.close()
    ORDERS_ROWS.clear()
    ORDERS_ROWS.append({"id": "recUNDO1", "fields": {
        "order_id": "ORD-UNDO0001", "partner_code": CODE, "status": "confirmed",
        "items_description": "1x Burger", "dropoff_address": "2 Demo St"}})
    monkeypatch.setattr(kitchen_mod.at, "list_records", fake_list)
    yield


def _events(order_id="ORD-UNDO0001"):
    db = SessionLocal()
    try:
        return [e.event_type for e in db.query(Event)
                .filter(Event.entity_ref == order_id)
                .order_by(Event.recorded_at).all()]
    finally:
        db.close()


# ---------------- undo ----------------

def test_a_cook_can_take_back_a_ticket_they_marked_ready_by_mistake():
    assert client.post(f"/api/kitchen/{TOKEN}/orders/recUNDO1/ready").status_code == 200
    r = client.post(f"/api/kitchen/{TOKEN}/orders/recUNDO1/unready")
    assert r.status_code == 200
    assert r.json()["undone"] is True
    assert _events() == ["order.kitchen_ready", "order.kitchen_ready_undone"]


def test_undo_is_an_event_not_a_deletion():
    """The log is append-only. An undo ADDS a fact; it never erases one — the
    record must still show that the cook once said ready."""
    client.post(f"/api/kitchen/{TOKEN}/orders/recUNDO1/ready")
    client.post(f"/api/kitchen/{TOKEN}/orders/recUNDO1/unready")
    assert "order.kitchen_ready" in _events()


def test_an_undone_ticket_goes_back_on_the_rail_as_still_cooking():
    client.post(f"/api/kitchen/{TOKEN}/orders/recUNDO1/ready")
    ready_now = client.get(f"/api/kitchen/{TOKEN}/orders").json()["orders"][0]["ready"]
    assert ready_now is True
    client.post(f"/api/kitchen/{TOKEN}/orders/recUNDO1/unready")
    after = client.get(f"/api/kitchen/{TOKEN}/orders").json()["orders"][0]["ready"]
    assert after is False, "undo did not put the ticket back on the rail"


def test_a_ticket_can_be_marked_ready_again_after_an_undo():
    """Ready -> undo -> ready must actually re-ready it. If the ready endpoint
    still thought it was idempotent, the cook would be stuck."""
    client.post(f"/api/kitchen/{TOKEN}/orders/recUNDO1/ready")
    client.post(f"/api/kitchen/{TOKEN}/orders/recUNDO1/unready")
    r = client.post(f"/api/kitchen/{TOKEN}/orders/recUNDO1/ready")
    assert r.status_code == 200
    assert r.json().get("idempotent") is not True
    assert client.get(f"/api/kitchen/{TOKEN}/orders").json()["orders"][0]["ready"] is True


def test_you_cannot_undo_a_ticket_that_was_never_ready():
    r = client.post(f"/api/kitchen/{TOKEN}/orders/recUNDO1/unready")
    assert r.status_code == 409
    assert "isn't marked ready" in r.json()["detail"]


def test_kitchen_cannot_undo_once_the_driver_has_the_food():
    """THE ONE THAT MATTERS. The driver is holding the bag. The kitchen does not
    get to rewrite where that food is — that truth belongs to the person carrying
    it. The cook is told to call dispatch, like a human."""
    client.post(f"/api/kitchen/{TOKEN}/orders/recUNDO1/ready")
    ORDERS_ROWS[0]["fields"]["status"] = "in_transit"
    r = client.post(f"/api/kitchen/{TOKEN}/orders/recUNDO1/unready")
    assert r.status_code == 409
    assert "driver already has this order" in r.json()["detail"]
    assert "order.kitchen_ready_undone" not in _events()


def test_undo_expires_so_a_driver_is_never_sent_back_for_nothing():
    """Past the grace window a driver may already be rolling. The button stops
    pretending and tells the cook to call."""
    client.post(f"/api/kitchen/{TOKEN}/orders/recUNDO1/ready")
    db = SessionLocal()
    try:
        e = (db.query(Event)
             .filter(Event.entity_ref == "ORD-UNDO0001",
                     Event.event_type == "order.kitchen_ready").first())
        e.recorded_at = datetime.now(timezone.utc) - timedelta(
            seconds=kitchen_mod.UNDO_WINDOW_SECONDS + 30)
        db.commit()
    finally:
        db.close()
    r = client.post(f"/api/kitchen/{TOKEN}/orders/recUNDO1/unready")
    assert r.status_code == 409
    assert "Too late to undo" in r.json()["detail"]


def test_a_stranger_cannot_undo_another_kitchens_ticket():
    db = SessionLocal()
    try:
        if not db.get(Partner, "otherkitchen"):
            db.add(Partner(code="otherkitchen", display_name="Someone Else",
                           status="pilot", portal_token="kt-other"))
            db.commit()
    finally:
        db.close()
    client.post(f"/api/kitchen/{TOKEN}/orders/recUNDO1/ready")
    r = client.post("/api/kitchen/kt-other/orders/recUNDO1/unready")
    assert r.status_code == 403


def test_kitchen_ui_offers_undo_with_an_honest_countdown():
    k = _page("kitchen.html")
    assert "undoReady" in k and "UNDO_WINDOW_MS" in k
    assert "Undo — not ready yet" in k


# ---------------- back ----------------

def test_every_consumer_surface_you_can_enter_you_can_leave():
    """Founder-reported: there were no back buttons anywhere. A deep link from a
    text message must never dead-end."""
    for name in ("order-form.html", "me.html", "support.html",
                 "lead-driver.html", "lead-merchant.html", "team.html"):
        html = _page(name)
        assert ("gw-back" in html or 'class="back"' in html), f"{name} has no way out"


def test_back_falls_back_to_home_when_there_is_no_history():
    form = _page("order-form.html")
    assert "history.back()" in form
    assert "location.href = '/'" in form


def test_tracking_page_can_get_back_to_gateway():
    src = open(os.path.join(ROOT, "app", "track.py")).read()
    assert "gwBack" in src and "Back to GateWay" in src
    # both render paths (order found, order missing) must carry it
    assert src.count("Back to GateWay") == 2


# ---------------- the founder's inbox ----------------

def test_board_surfaces_the_inbox_so_no_raised_hand_is_lost():
    b = _page("board.html")
    assert "showInbox" in b
    assert "/v0/leads?key=" in b and "/v0/support-tickets?key=" in b
    assert "Merchants who want in" in b and "Drivers who want to drive" in b
    assert "Neighbors who need help" in b


def test_the_inbox_gives_the_founder_a_phone_number_to_call():
    """A lead you can't call is a lead you lost."""
    b = _page("board.html")
    assert "tel:" in b
