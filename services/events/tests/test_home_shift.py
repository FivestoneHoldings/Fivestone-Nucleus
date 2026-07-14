"""Unified home + driver shift toggle tests."""
import os, tempfile
os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")
os.environ["ADMIN_KEY"] = "test-key"
os.environ["AIRTABLE_PAT"] = "fake-pat"

import pytest
from fastapi.testclient import TestClient
import app.airtable_client as at
import app.dispatch as dp
from app.main import app

client = TestClient(app)

FAKE_DRIVER = {"id": "recD", "fields": {"driver_id": "DRV-9", "display_name": "Shifty",
                                          "day_token": "tokS", "status": "active"}}
PATCHES = []


async def fake_list(table, formula="", fields=None, max_records=100):
    if table == at.DRIVERS:
        return [FAKE_DRIVER] if "tokS" in formula else []
    return []


async def fake_patch(table, record_id, fields):
    PATCHES.append((table, record_id, fields))
    return {"id": record_id, "fields": fields}


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    for m in (at, dp.at):
        monkeypatch.setattr(m, "list_records", fake_list)
        monkeypatch.setattr(m, "patch_record", fake_patch)
    yield


def test_home_serves_launcher():
    r = client.get("/")
    assert r.status_code == 200
    for needle in ("Place an order", "Track an order", "manifest.json"):
        assert needle in r.text
    # team entry relocated to /team (v1.1)
    t = client.get("/team")
    assert t.status_code == 200
    for needle in ("Driver day code", "Dispatch key", "Kitchen code"):
        assert needle in t.text


def test_shift_toggle_on_off():
    r = client.post("/api/driver/tokS/shift", json={"on": True})
    assert r.status_code == 200 and r.json()["shift"] is True
    assert PATCHES[-1][2] == {"status": "on_shift"}
    r2 = client.post("/api/driver/tokS/shift", json={"on": False})
    assert r2.json()["shift"] is False
    assert PATCHES[-1][2] == {"status": "active"}
    # owned log has both events
    ev = client.get("/api/board/test-key/events").json()["events"]
    types = [e["event_type"] for e in ev[:2]]
    assert "driver.shift_ended" in types and "driver.shift_started" in types


def test_shift_bad_token_404():
    assert client.post("/api/driver/nope/shift", json={"on": True}).status_code == 404


def test_sheet_reports_shift_state():
    d = client.get("/api/driver/tokS/orders").json()
    assert d["shift"] is False and d["driver"] == "Shifty"
