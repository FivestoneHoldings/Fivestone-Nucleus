"""Partner registry + public tracking tests."""
import os, tempfile
os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")
os.environ["ADMIN_KEY"] = "test-key"
os.environ["AIRTABLE_PAT"] = "fake-pat"

import pytest
from fastapi.testclient import TestClient
import app.track as track_mod
from app.main import app

client = TestClient(app)
K = "/api/board/test-key"

ORDER = {"id": "recT", "fields": {
    "order_id": "ORD-TRACK01", "status": "in_transit", "items_description": "2 boxes",
    "received_at": "2026-07-08T20:00:00.000Z", "assigned_at": "2026-07-08T20:05:00.000Z",
    "in_transit_at": "2026-07-08T20:10:00.000Z",
    "dropoff_address": "SECRET LANE", "customer_phone_raw": "865-000-0000"}}


async def fake_list(table, formula="", fields=None, max_records=100):
    return [ORDER] if "ORD-TRACK01" in formula else []


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    monkeypatch.setattr(track_mod.at, "list_records", fake_list)
    yield


def test_seed_and_public_lookup():
    r = client.get("/v0/partners/asiacafe")
    assert r.status_code == 200
    assert r.json()["display_name"] == "Asia Cafe"
    assert client.get("/v0/partners/nobody").status_code == 404


def test_partner_upsert_and_list():
    r = client.post(f"{K}/partners", json={"code": "Friends BBQ", "display_name": "Friends BBQ"})
    assert r.status_code == 200
    assert r.json()["code"] == "friendsbbq"  # normalized
    codes = [p["code"] for p in client.get(f"{K}/partners").json()["partners"]]
    assert "friendsbbq" in codes and "asiacafe" in codes
    # update path
    r2 = client.post(f"{K}/partners", json={"code": "friendsbbq",
                                            "display_name": "Friends BBQ Maryville", "status": "active"})
    assert r2.status_code == 200
    got = client.get("/v0/partners/friendsbbq").json()
    assert got["display_name"] == "Friends BBQ Maryville" and got["status"] == "active"


def test_partner_requires_key_and_fields():
    assert client.get("/api/board/wrong/partners").status_code == 403
    assert client.post(f"{K}/partners", json={"code": "x"}).status_code == 400


def test_track_shows_timeline_hides_private():
    r = client.get("/track/ord-track01")  # case-insensitive
    assert r.status_code == 200
    assert "On the way to you" in r.text
    assert "Picked up" in r.text and "2 boxes" in r.text
    assert "SECRET LANE" not in r.text and "865-000-0000" not in r.text


def test_track_404():
    assert client.get("/track/ORD-NOPE").status_code == 404
