"""Tracking-experience contract: status endpoint privacy, pulse, microcopy, celebration."""
import datetime as _dt
import pytest
from fastapi.testclient import TestClient
import app.airtable_client as at
import app.dispatch as dp
import app.track as track_mod
from app.main import app
from tests.fake_airtable import FakeAirtable

client = TestClient(app)
fake = FakeAirtable()
TODAY = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")

fake.seed(at.ORDERS, {"order_id": "ORD-TRX01", "status": "assigned",
                       "items_description": "1× Thing ($5.00)",
                       "dropoff_address": "HIDDEN LANE",
                       "received_at": f"{TODAY}T12:00:00.000Z",
                       "confirmed_at": f"{TODAY}T12:02:00.000Z",
                       "assigned_at": f"{TODAY}T12:05:00.000Z"})
fake.seed(at.ORDERS, {"order_id": "ORD-TRX02", "status": "delivered",
                       "items_description": "1× Pie ($4.00)", "total_cents": 400,
                       "received_at": f"{TODAY}T11:00:00.000Z",
                       "delivered_at": f"{TODAY}T11:30:00.000Z"})


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    for m in (at, dp.at, track_mod.at):
        monkeypatch.setattr(m, "list_records", fake.list_records)
    yield


def test_status_endpoint_minimal_and_private():
    d = client.get("/v0/track/ORD-TRX01/status").json()
    assert d == {"status": "assigned"}  # nothing but status
    assert client.get("/v0/track/ORD-NOPE/status").json()["status"] == "unknown"


def test_active_page_has_pulse_micro_elapsed():
    html = client.get("/track/ORD-TRX01").text
    assert 'class="step now"' in html            # pulsing current step
    assert "driver is heading to pick it up" in html  # microcopy
    assert 'id="elapsed"' in html and "pollStatus" in html
    assert "HIDDEN LANE" not in html             # privacy holds


def test_delivered_page_celebrates_with_reorder():
    html = client.get("/track/ORD-TRX02").text
    assert 'class="celebrate"' in html
    assert "Photo from your driver" in html
    assert 'id="againBtn"' in html
    assert 'class="step now"' not in html        # nothing pulses when done
