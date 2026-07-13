"""Partner split migration + order detail tests."""
import os, tempfile
os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")
os.environ["ADMIN_KEY"] = "test-key"
os.environ["AIRTABLE_PAT"] = "fake-pat"

import pytest
from fastapi.testclient import TestClient
import app.airtable_client as at
import app.dispatch as dp
from app.db import SessionLocal
from app.models import Partner, MenuItem
from app.main import app
from app.menu import migrate_split_burgerboys, seed_menus

client = TestClient(app)
K = "/api/board/test-key"

ORDER = {"id": "recDET", "fields": {
    "order_id": "ORD-DETAIL01", "status": "delivered", "partner_code": "burgerboys",
    "pickup_address": "3000 N Broadway", "dropoff_address": "1 Test Way",
    "items_description": "1× Kobe Burger", "received_at": "2026-07-09T15:00:00.000Z",
    "delivered_at": "2026-07-09T15:30:00.000Z"}}


async def fake_list(table, formula="", fields=None, max_records=100):
    return [ORDER] if "ORD-DETAIL01" in formula else []


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    for m in (at, dp.at):
        monkeypatch.setattr(m, "list_records", fake_list)
    yield


def test_two_separate_restaurants():
    assert client.get("/v0/partners/burgerboys").json()["display_name"] == "Burger Boys"
    assert client.get("/v0/partners/friendsbbq").json()["display_name"] == "Friends BBQ"
    bb = client.get("/v0/partners/burgerboys/menu").json()
    fb = client.get("/v0/partners/friendsbbq/menu").json()
    bb_names = [i["name"] for c in bb["categories"] for i in c["items"]]
    fb_names = [i["name"] for c in fb["categories"] for i in c["items"]]
    assert "Kobe Burger" in bb_names and "Pulled Pork" not in bb_names
    assert "Pulled Pork" in fb_names and "Ribs Pack (serves 5)" in fb_names


def test_migration_repairs_combined_partner():
    # Simulate the production state: combined partner + a BBQ item under burgerboys
    db = SessionLocal()
    p = db.get(Partner, "burgerboys"); p.display_name = "Burger Boys & Friends BBQ"
    db.query(Partner).filter(Partner.code == "friendsbbq").delete()
    db.add(MenuItem(partner_code="burgerboys", category="BBQ",
                    name="Rib Plate OLD", price_cents=1399))
    db.commit(); db.close()
    migrate_split_burgerboys()
    db = SessionLocal()
    assert db.get(Partner, "burgerboys").display_name == "Burger Boys"
    assert db.get(Partner, "friendsbbq") is not None
    moved = db.query(MenuItem).filter(MenuItem.name == "Rib Plate OLD").one()
    assert moved.partner_code == "friendsbbq"
    assert db.query(MenuItem).filter(MenuItem.partner_code == "burgerboys",
                                     MenuItem.category == "BBQ").count() == 0
    db.close()
    seed_menus()  # idempotent re-run must not duplicate
    db = SessionLocal()
    assert db.query(MenuItem).filter(MenuItem.name == "Rib Plate OLD").count() == 1
    db.close()


def test_order_detail_full_history():
    dp._log_event("order.received", "ORD-DETAIL01", "system", {})
    dp._log_event("order.delivered", "ORD-DETAIL01", "driver:Test", {})
    r = client.get(f"{K}/order-detail/ord-detail01")
    assert r.status_code == 200
    d = r.json()
    assert d["fields"]["status"] == "delivered"
    assert d["fields"]["pickup_address"] == "3000 N Broadway"
    types = [e["event_type"] for e in d["events"]]
    assert types == ["order.received", "order.delivered"]  # chronological


def test_order_detail_404_and_key():
    assert client.get(f"{K}/order-detail/ORD-NOPE").status_code == 404
    assert client.get("/api/board/wrong/order-detail/ORD-DETAIL01").status_code == 403
