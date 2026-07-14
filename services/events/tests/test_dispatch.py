"""Dispatch surface tests — driver actions and board auth, with Airtable faked."""
import os, tempfile
os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")
os.environ["ADMIN_KEY"] = "test-key"
os.environ["AIRTABLE_PAT"] = "fake-pat"

from fastapi.testclient import TestClient
import app.airtable_client as at
from app.main import app

client = TestClient(app)

FAKE_DRIVER = {"id": "recDRV1", "fields": {"display_name": "Test Driver", "day_token": "tok123"}}
FAKE_ORDER = {"id": "recORD1", "fields": {
    "order_id": "ORD-AAAA1111", "status": "assigned", "driver": ["recDRV1"],
    "pickup_address": "A", "dropoff_address": "B", "items_description": "box"}}
PATCHES = []


async def fake_list(table, formula="", fields=None, max_records=100):
    if table == at.DRIVERS:
        return [FAKE_DRIVER] if "tok123" in formula else []
    if table == at.ORDERS:
        return [FAKE_ORDER]
    return []


async def fake_patch(table, record_id, fields):
    PATCHES.append((table, record_id, fields))
    merged = dict(FAKE_ORDER["fields"]); merged.update(fields)
    return {"id": record_id, "fields": merged}


async def fake_create(table, fields):
    return {"id": "recNEW", "fields": fields}


import pytest
import app.dispatch as dp


@pytest.fixture(autouse=True)
def _reset_state():
    FAKE_ORDER["fields"]["status"] = "assigned"
    yield


@pytest.fixture(autouse=True)
def _patched_airtable(monkeypatch):
    for mod in (at, dp.at):
        monkeypatch.setattr(mod, "list_records", fake_list)
        monkeypatch.setattr(mod, "patch_record", fake_patch)
        monkeypatch.setattr(mod, "create_record", fake_create)
    yield


def test_driver_sheet_lists_their_orders():
    r = client.get("/api/driver/tok123/orders")
    assert r.status_code == 200
    d = r.json()
    assert d["driver"] == "Test Driver"
    assert d["orders"][0]["order_id"] == "ORD-AAAA1111"


def test_unknown_token_404():
    assert client.get("/api/driver/nope/orders").status_code == 404


def test_driver_action_stamps_and_events():
    r = client.post("/api/driver/tok123/orders/recORD1/picked_up")
    assert r.status_code == 200
    assert r.json()["new_status"] == "in_transit"
    table, rec, fields = PATCHES[-1]
    assert fields["status"] == "in_transit" and "in_transit_at" in fields
    ev = client.get("/v0/events", params={"entity_ref": "ORD-AAAA1111"}).json()
    assert any(e["event_type"] == "order.picked_up" for e in ev)


def test_invalid_action_rejected():
    assert client.post("/api/driver/tok123/orders/recORD1/exploded").status_code == 400


def test_board_requires_key():
    assert client.get("/api/board/wrong/orders").status_code == 403
    assert client.get("/api/board/test-key/orders").status_code == 200


def test_assign_flow():
    FAKE_ORDER["fields"]["status"] = "confirmed"  # assign requires received/confirmed
    r = client.post("/api/board/test-key/orders/recORD1/assign",
                    json={"driver_id": "recDRV1"})
    assert r.status_code == 200
    _, _, fields = PATCHES[-1]
    assert fields["status"] == "assigned" and fields["driver"] == ["recDRV1"]


def test_ui_pages_serve():
    assert client.get("/driver/tok123").status_code == 200
    assert "Driver Hub" in client.get("/driver/tok123").text
    assert client.get("/board/anything").status_code == 200
    assert client.get("/order").status_code == 200
