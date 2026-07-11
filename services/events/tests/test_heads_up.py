"""Driver heads-up: ownership-gated write, in-transit-only public read, first-order welcome."""
import pytest
from fastapi.testclient import TestClient
import app.airtable_client as at
import app.dispatch as dp
from app.main import app
from tests.fake_airtable import FakeAirtable

client = TestClient(app)
fake = FakeAirtable()

DRV_A = fake.seed(at.DRIVERS, {"driver_id": "DRV-HA", "day_token": "tokHA",
                                "display_name": "Ada", "status": "active"})
DRV_B = fake.seed(at.DRIVERS, {"driver_id": "DRV-HB", "day_token": "tokHB",
                                "display_name": "Ben", "status": "active"})
ORD = fake.seed(at.ORDERS, {"order_id": "ORD-HU01", "status": "in_transit",
                             "driver": [DRV_A], "items_description": "1x thing",
                             "received_at": "2026-07-11T12:00:00.000Z"})
ASSIGNED = fake.seed(at.ORDERS, {"order_id": "ORD-HU02", "status": "assigned",
                                  "driver": [DRV_A],
                                  "received_at": "2026-07-11T12:00:00.000Z"})


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    for m in (at, dp.at):
        monkeypatch.setattr(m, "list_records", fake.list_records)
        monkeypatch.setattr(m, "create_record", fake.create_record)
        monkeypatch.setattr(m, "patch_record", fake.patch_record)
    yield


def test_heads_up_owner_only():
    assert client.post(f"/api/driver/tokHB/orders/{ORD}/heads-up",
                       json={"note": "hi"}).status_code == 403
    assert client.post(f"/api/driver/tokHA/orders/{ORD}/heads-up",
                       json={"note": "On my way now"}).status_code == 200


def test_heads_up_visible_in_transit_only():
    client.post(f"/api/driver/tokHA/orders/{ORD}/heads-up",
                json={"note": "5 minutes out"})
    d = client.get("/v0/track/ORD-HU01/heads-up").json()
    assert d["note"] == "5 minutes out"
    # assigned (not in transit) never exposes a note
    client.post(f"/api/driver/tokHA/orders/{ASSIGNED}/heads-up", json={"note": "secret"})
    assert client.get("/v0/track/ORD-HU02/heads-up").json()["note"] == ""


def test_heads_up_latest_wins():
    client.post(f"/api/driver/tokHA/orders/{ORD}/heads-up", json={"note": "first"})
    client.post(f"/api/driver/tokHA/orders/{ORD}/heads-up", json={"note": "second"})
    assert client.get("/v0/track/ORD-HU01/heads-up").json()["note"] == "second"


def test_track_page_polls_heads_up_and_form_welcomes():
    assert "pollHeadsUp" in client.get("/track/ORD-HU01").text
    assert "Welcome to GateWay" in client.get("/order").text
