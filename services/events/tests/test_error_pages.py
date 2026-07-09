"""Branded error experience: 404/500 pages, throttle page, offline assets."""
import os, tempfile
os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")
os.environ["ADMIN_KEY"] = "test-key"
os.environ["AIRTABLE_PAT"] = "fake-pat"

import pytest
from fastapi.testclient import TestClient
import app.dispatch as dp
import app.intake as intake_mod
from app.main import app

client = TestClient(app, raise_server_exceptions=False)
HTML = {"accept": "text/html,application/xhtml+xml"}


def test_404_branded_for_browsers_json_for_api():
    r = client.get("/no-such-page", headers=HTML)
    assert r.status_code == 404
    assert "GateWay" in r.text and "Back to GateWay" in r.text
    r2 = client.get("/api/board/wrong/orders", headers=HTML)  # api path stays JSON
    assert r2.headers["content-type"].startswith("application/json")
    r3 = client.get("/no-such-page")  # no html accept -> JSON
    assert r3.json()["detail"] == "Not Found"


def test_proof_404_branded_in_browser():
    r = client.get("/proof/ORD-NOPE", headers=HTML)
    assert r.status_code == 404 and "GateWay" in r.text


def test_500_branded_and_logged(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(dp.at, "list_records", boom)
    r = client.get("/track/ORD-X" , headers=HTML)  # goes through track_mod? patch that too
    import app.track as track_mod
    monkeypatch.setattr(track_mod.at, "list_records", boom)
    r = client.get("/track/ORD-X", headers=HTML)
    assert r.status_code == 500
    assert "NOT completed" in r.text
    # API path returns JSON 500
    r2 = client.get("/api/board/test-key/orders")
    assert r2.status_code == 500 and r2.json()["detail"] == "internal_error"
    ev = client.get("/api/board/test-key/events")
    # events endpoint itself doesn't touch airtable; should list system.error rows
    assert any(e["event_type"] == "system.error" for e in ev.json()["events"])


def test_throttle_branded_html(monkeypatch):
    async def empty(*a, **k):
        return []
    async def create(*a, **k):
        return {"id": "r", "fields": {}}
    monkeypatch.setattr(intake_mod.at, "list_records", empty)
    monkeypatch.setattr(intake_mod.at, "create_record", create)
    intake_mod._HITS.clear()
    for i in range(30):
        client.get("/v0/intake", params={"dropoff_address": f"{i} St", "items_description": "x"},
                   headers={"x-forwarded-for": "1.1.1.1"})
    r = client.get("/v0/intake", params={"dropoff_address": "z", "items_description": "x"},
                   headers={"x-forwarded-for": "1.1.1.1"})
    assert r.status_code == 429 and "slow down" in r.text


def test_offline_assets_served():
    assert client.get("/static/offline.html").status_code == 200
    sw = client.get("/static/sw.js").text
    assert "offline.html" in sw and "gw-v2" in sw
