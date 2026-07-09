"""Live driver location: ping, privacy-scoped resolver, track map render."""
import os, tempfile
os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")
os.environ["ADMIN_KEY"] = "test-key"
os.environ["AIRTABLE_PAT"] = "fake-pat"

import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
import app.airtable_client as at
import app.dispatch as dp
import app.track as track_mod
from app.db import SessionLocal
from app.models import DriverLocation
from app.main import app

client = TestClient(app)

DRIVER = {"id": "recDL", "fields": {"driver_id": "DRV-LOC", "day_token": "tokL",
                                     "display_name": "Mover"}}
ORDER_IT = {"id": "recIT", "fields": {"order_id": "ORD-LIVE01", "status": "in_transit",
                                       "driver": ["recDL"], "dropoff_address": "9 Elm"}}
ORDER_DONE = {"id": "recDN", "fields": {"order_id": "ORD-DONE01", "status": "delivered",
                                         "driver": ["recDL"]}}


async def fake_list(table, formula="", fields=None, max_records=100):
    if table == at.DRIVERS:
        if "tokL" in formula or "recDL" in formula:
            return [DRIVER]
        return []
    if "ORD-LIVE01" in formula:
        return [ORDER_IT]
    if "ORD-DONE01" in formula:
        return [ORDER_DONE]
    return []


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    for m in (at, dp.at, track_mod.at):
        monkeypatch.setattr(m, "list_records", fake_list)
    yield


def test_ping_stores_location():
    r = client.post("/api/driver/tokL/ping", json={"lat": "35.96", "lng": "-83.92"})
    assert r.status_code == 200 and r.json()["ok"] is True
    db = SessionLocal()
    loc = db.get(DriverLocation, "DRV-LOC")
    assert loc.lat == "35.96" and loc.lng == "-83.92"
    db.close()


def test_ping_ignores_empty():
    assert client.post("/api/driver/tokL/ping", json={}).json()["ok"] is False


def test_location_live_only_when_in_transit():
    client.post("/api/driver/tokL/ping", json={"lat": "35.96", "lng": "-83.92"})
    live = client.get("/v0/track/ORD-LIVE01/location").json()
    assert live["live"] is True and live["lat"] == "35.96"
    # delivered order → never live
    done = client.get("/v0/track/ORD-DONE01/location").json()
    assert done["live"] is False


def test_location_staleness_guard():
    client.post("/api/driver/tokL/ping", json={"lat": "1", "lng": "2"})
    db = SessionLocal()
    loc = db.get(DriverLocation, "DRV-LOC")
    loc.updated_at = datetime.now(timezone.utc) - timedelta(minutes=15)
    db.commit(); db.close()
    assert client.get("/v0/track/ORD-LIVE01/location").json()["live"] is False


def test_track_page_renders_map_scaffold():
    html = client.get("/track/ORD-LIVE01").text
    assert "leaflet" in html and "pollLoc" in html
    assert 'data-oid="ORD-LIVE01"' in html
    assert "tile.openstreetmap.org/{z}/{x}/{y}" in html  # single braces in final HTML


def test_track_hides_private_fields():
    html = client.get("/track/ORD-LIVE01").text
    assert "9 Elm" not in html  # dropoff never exposed on page body
