"""The full experience journey with the differentiation layer ON — one customer
relationship end to end, plus the kitchen's pride surface under the same data."""
import datetime as _dt
import pytest
from fastapi.testclient import TestClient
import app.airtable_client as at
import app.dispatch as dp
import app.kitchen as kitchen_mod
import app.intake as intake_mod
import app.track as track_mod
from app.db import SessionLocal
from app.models import Partner
from app.main import app
from tests.fake_airtable import FakeAirtable

client = TestClient(app)
K = "/api/board/test-key"
fake = FakeAirtable()
TODAY = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    for m in (at, dp.at, kitchen_mod.at, intake_mod.at, track_mod.at):
        monkeypatch.setattr(m, "list_records", fake.list_records)
        monkeypatch.setattr(m, "create_record", fake.create_record)
        monkeypatch.setattr(m, "patch_record", fake.patch_record)
    intake_mod._HITS.clear()
    yield


def test_kitchen_pride_surface():
    # seed a full day for burgerboys: 2 delivered, 1 in transit, 1 received
    for i, (st, hh) in enumerate([("delivered","12"),("delivered","12"),
                                   ("in_transit","13"),("received","18")]):
        f = {"order_id": f"ORD-PRIDE{i}", "status": st, "partner_code": "burgerboys",
             "items_description": "1× Halfpounder ($9.00)", "subtotal_cents": 900,
             "received_at": f"{TODAY}T{hh}:05:00.000Z"}
        if st in ("delivered",):
            f["delivered_at"] = f"{TODAY}T{hh}:40:00.000Z"
        fake.seed(at.ORDERS, f)
    db = SessionLocal(); tok = db.get(Partner, "burgerboys").portal_token; db.close()
    d = client.get(f"/api/kitchen/{tok}/orders").json()
    assert d["delivered_today"] == 2
    assert d["in_kitchen_now"] == 1        # only the 'received' is still in the kitchen
    assert d["picked_up_today"] == 3       # 2 delivered + 1 in_transit
    assert d["revenue_today_cents"] == 900 * 3
    assert d["peak_hour"] == "12"          # two orders that hour


def test_customer_journey_pages_serve_with_everything_on():
    # the surfaces a real customer touches, all 200 + carry the experience layer
    assert "YOUR USUAL" in client.get("/").text or "restaurants" in client.get("/").text
    assert "Place order ·" in client.get("/order?partner=stephens").text
    me = client.get("/me").text
    assert "kept in local kitchens" in me and "gw-profile.js" in me


def test_order_to_track_records_and_milestones_hook():
    r = client.post("/v0/intake", json={
        "dropoff_address": "5 Journey Rd", "items_description": "1× Pie ($4.00)",
        "partner": "stephens", "subtotal_cents": "400", "fee_cents": "399",
        "tip_cents": "300", "total_cents": "1099"},
        headers={"x-forwarded-for": "12.12.12.12"})
    oid = r.json()["order_id"]
    page = client.get(f"/track/{oid}").text
    assert "milestone" in page          # milestone logic present on the page
    assert "gw-profile.js" in page      # history capture wired
