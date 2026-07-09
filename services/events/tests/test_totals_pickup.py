"""Partner address/fee, totals carried through intake, tracking total, redirect."""
import os, tempfile
os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")
os.environ["ADMIN_KEY"] = "test-key"
os.environ["AIRTABLE_PAT"] = "fake-pat"

import pytest
from fastapi.testclient import TestClient
import app.airtable_client as at
import app.intake as intake_mod
import app.track as track_mod
from app.main import app

client = TestClient(app)
K = "/api/board/test-key"
CREATED = []


async def fake_list_intake(table, formula="", fields=None, max_records=100):
    return []  # no dedup hit


async def fake_create(table, fields):
    CREATED.append(fields)
    return {"id": "recX", "fields": fields}


TRACK_ORDER = {"id": "recTt", "fields": {
    "order_id": "ORD-TOT01", "status": "in_transit", "items_description": "1x Pizza",
    "total_cents": 2198, "received_at": "2026-07-09T15:00:00.000Z",
    "in_transit_at": "2026-07-09T15:20:00.000Z"}}


async def fake_list_track(table, formula="", fields=None, max_records=100):
    return [TRACK_ORDER] if "ORD-TOT01" in formula else []


def test_seeded_partner_has_address_and_fee():
    d = client.get("/v0/partners/stephens").json()
    assert "Gray, TN" in d["address"]
    assert d["delivery_fee_cents"] == 399


def test_partner_meta_settable():
    client.post(f"{K}/partners", json={"code": "stephens", "display_name": "Stephen's Pizzeria",
                                       "address": "New Addr", "delivery_fee_cents": 599})
    d = client.get("/v0/partners/stephens").json()
    assert d["address"] == "New Addr" and d["delivery_fee_cents"] == 599


def test_intake_carries_totals(monkeypatch):
    monkeypatch.setattr(intake_mod.at, "list_records", fake_list_intake)
    monkeypatch.setattr(intake_mod.at, "create_record", fake_create)
    r = client.post("/v0/intake", json={
        "dropoff_address": "1 Elm St", "items_description": "1x Pizza",
        "partner": "stephens", "subtotal_cents": "1799", "fee_cents": "399",
        "total_cents": "2198"})
    assert r.status_code == 200
    f = CREATED[-1]
    assert f["subtotal_cents"] == 1799 and f["fee_cents"] == 399 and f["total_cents"] == 2198


def test_track_shows_total(monkeypatch):
    monkeypatch.setattr(track_mod.at, "list_records", fake_list_track)
    r = client.get("/track/ORD-TOT01")
    assert r.status_code == 200
    assert "$21.98" in r.text


def test_intake_html_redirects_to_tracking(monkeypatch):
    monkeypatch.setattr(intake_mod.at, "list_records", fake_list_intake)
    monkeypatch.setattr(intake_mod.at, "create_record", fake_create)
    r = client.get("/v0/intake", params={"dropoff_address": "2 Oak St",
                   "items_description": "burger", "partner": "burgerboys"},
                   follow_redirects=False)
    assert r.status_code == 200
    assert "/track/ORD-" in r.text  # meta-refresh + JS redirect to tracking
