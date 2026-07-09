"""Order editing, board kitchen-ready, instant GPS from actions."""
import os, tempfile
os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")
os.environ["ADMIN_KEY"] = "test-key"
os.environ["AIRTABLE_PAT"] = "fake-pat"

import json
import pytest
from fastapi.testclient import TestClient
import app.airtable_client as at
import app.dispatch as dp
from app.db import SessionLocal
from app.models import DriverLocation, Event
from app.main import app

client = TestClient(app)
K = "/api/board/test-key"

DRIVER = {"id": "recED", "fields": {"driver_id": "DRV-ED", "day_token": "tokED",
                                     "display_name": "Editor"}}
ORDER = {"id": "recEO", "fields": {"order_id": "ORD-EDIT01", "status": "assigned",
                                    "dropoff_address": "OLD ADDR", "driver": ["recED"],
                                    "customer_phone_raw": ""}}
PATCHES = []


async def fake_list(table, formula="", fields=None, max_records=100):
    if table == at.DRIVERS:
        return [DRIVER]
    return [ORDER]


async def fake_patch(table, record_id, fields):
    PATCHES.append(fields)
    merged = dict(ORDER["fields"]); merged.update(fields)
    return {"id": record_id, "fields": merged}


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    for m in (at, dp.at):
        monkeypatch.setattr(m, "list_records", fake_list)
        monkeypatch.setattr(m, "patch_record", fake_patch)
    yield


def test_edit_whitelisted_and_logged():
    r = client.post(f"{K}/orders/recEO/edit",
                    json={"dropoff_address": "NEW ADDR", "status": "delivered"})
    assert r.status_code == 200
    assert PATCHES[-1] == {"dropoff_address": "NEW ADDR"}  # status ignored (not whitelisted)
    db = SessionLocal()
    ev = (db.query(Event).filter(Event.event_type == "order.edited")
          .order_by(Event.occurred_at.desc()).first())
    payload = json.loads(ev.payload)
    assert payload["changed"]["dropoff_address"]["from"] == "OLD ADDR"
    assert payload["changed"]["dropoff_address"]["to"] == "NEW ADDR"
    db.close()


def test_edit_rejects_empty_and_bad_key():
    assert client.post(f"{K}/orders/recEO/edit", json={"status": "x"}).status_code == 400
    assert client.post("/api/board/wrong/orders/recEO/edit",
                       json={"dropoff_address": "x"}).status_code == 403


def test_board_orders_carry_kitchen_ready():
    dp._log_event("order.kitchen_ready", "ORD-EDIT01", "kitchen:test", {})
    d = client.get(f"{K}/orders").json()
    assert d["orders"][0]["kitchen_ready"] is True


def test_action_gps_updates_driver_location_instantly():
    r = client.post("/api/driver/tokED/orders/recEO/picked_up",
                    json={"lat": "36.01", "lng": "-83.90"})
    assert r.status_code == 200
    db = SessionLocal()
    loc = db.get(DriverLocation, "DRV-ED")
    assert loc is not None and loc.lat == "36.01"
    db.close()
