"""Anticipation window: kitchen story on the waiting page, board editor, privacy."""
import datetime as _dt
import pytest
from fastapi.testclient import TestClient
import app.airtable_client as at
import app.dispatch as dp
import app.track as track_mod
from app.db import SessionLocal
from app.models import Partner
from app.main import app
from tests.fake_airtable import FakeAirtable

client = TestClient(app)
K = "/api/board/test-key"
fake = FakeAirtable()
TODAY = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")

fake.seed(at.ORDERS, {"order_id": "ORD-ANT-WAIT", "status": "received",
                       "partner_code": "stephens", "items_description": "1× Pie",
                       "dropoff_address": "SECRET 9", "received_at": f"{TODAY}T12:00:00.000Z"})
fake.seed(at.ORDERS, {"order_id": "ORD-ANT-MOVE", "status": "in_transit",
                       "partner_code": "stephens", "items_description": "1× Pie",
                       "received_at": f"{TODAY}T12:00:00.000Z"})


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    for m in (at, dp.at, track_mod.at):
        monkeypatch.setattr(m, "list_records", fake.list_records)
    yield


def test_story_editor_saves_and_shows_while_waiting():
    r = client.post(f"{K}/partners/stephens/about",
                    json={"blurb": "Family-owned since 1998. Nonna's sauce."})
    assert r.status_code == 200
    html = client.get("/track/ORD-ANT-WAIT").text
    assert "From Stephen" in html and "Nonna's sauce" in html
    assert "assign a neighbor to drive it" in html
    assert "SECRET 9" not in html                     # address never leaks


def test_story_absent_once_moving():
    client.post(f"{K}/partners/stephens/about", json={"blurb": "We exist."})
    html = client.get("/track/ORD-ANT-MOVE").text
    assert "We exist." not in html                    # anticipation card is waiting-only
