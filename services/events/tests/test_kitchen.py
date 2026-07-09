"""Kitchen Screen + pause/resume + scheduled orders."""
import os, tempfile
os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")
os.environ["ADMIN_KEY"] = "test-key"
os.environ["AIRTABLE_PAT"] = "fake-pat"

import pytest
from fastapi.testclient import TestClient
import app.airtable_client as at
import app.dispatch as dp
import app.intake as intake_mod
import app.kitchen as kitchen_mod
from app.db import SessionLocal
from app.models import Partner
from app.main import app

client = TestClient(app)
K = "/api/board/test-key"

KORDER = {"id": "recK1", "fields": {"order_id": "ORD-KIT01", "status": "confirmed",
                                     "partner_code": "stephens",
                                     "items_description": "1× Pepperoni 16\"",
                                     "received_at": "2026-07-09T15:00:00.000Z"}}
CREATED = []


async def fake_list(table, formula="", fields=None, max_records=100):
    if "partner_code" in formula and "stephens" in formula:
        return [KORDER]
    if "RECORD_ID()" in formula:
        return [KORDER]
    return []


async def fake_create(table, fields):
    CREATED.append(fields)
    return {"id": "recN", "fields": fields}


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    for m in (at, dp.at, intake_mod.at, kitchen_mod.at):
        monkeypatch.setattr(m, "list_records", fake_list)
        monkeypatch.setattr(m, "create_record", fake_create)
    intake_mod._HITS.clear()
    yield


def _token(code="stephens"):
    db = SessionLocal()
    tok = db.get(Partner, code).portal_token
    db.close()
    return tok


def test_portal_tokens_backfilled():
    assert _token().startswith("kt-")


def test_kitchen_orders_and_ready_flow():
    tok = _token()
    d = client.get(f"/api/kitchen/{tok}/orders").json()
    assert d["kitchen"] == "Stephen's Pizzeria"
    assert d["orders"][0]["order_id"] == "ORD-KIT01"
    assert d["orders"][0]["ready"] is False
    r = client.post(f"/api/kitchen/{tok}/orders/recK1/ready", json={})
    assert r.status_code == 200
    d2 = client.get(f"/api/kitchen/{tok}/orders").json()
    assert d2["orders"][0]["ready"] is True
    ev = client.get(f"{K}/events").json()["events"]
    assert any(e["event_type"] == "order.kitchen_ready" and
               e["actor"] == "kitchen:stephens" for e in ev)


def test_kitchen_bad_token_404():
    assert client.get("/api/kitchen/kt-nope/orders").status_code == 404
    assert client.get("/kitchen/kt-whatever").status_code == 200  # page always serves; API gates


def test_pause_blocks_intake_and_resume_restores():
    r = client.post(f"{K}/partners/stephens/accepting", json={"on": False})
    assert r.status_code == 200
    r2 = client.post("/v0/intake", json={"dropoff_address": "1 Elm",
                                         "items_description": "pizza", "partner": "stephens"},
                     headers={"x-forwarded-for": "7.7.7.7"})
    assert r2.status_code == 423
    assert client.get("/v0/partners/stephens").json()["accepting_orders"] is False
    client.post(f"{K}/partners/stephens/accepting", json={"on": True})
    r3 = client.post("/v0/intake", json={"dropoff_address": "1 Elm",
                                         "items_description": "pizza", "partner": "stephens"},
                     headers={"x-forwarded-for": "7.7.7.7"})
    assert r3.status_code == 200


def test_scheduled_order_carried():
    r = client.post("/v0/intake", json={
        "dropoff_address": "2 Oak", "items_description": "calzone",
        "partner": "stephens", "requested_for": "2026-07-10T18:30"},
        headers={"x-forwarded-for": "6.6.6.6"})
    assert r.status_code == 200
    assert CREATED[-1]["requested_for"] == "2026-07-10T18:30"


def test_driver_sheet_shows_kitchen_ready(monkeypatch):
    DRIVER = {"id": "recDX", "fields": {"driver_id": "DRV-X", "day_token": "tokX",
                                          "display_name": "X"}}
    MINE = {"id": "recM", "fields": {"order_id": "ORD-KIT01", "status": "assigned",
                                      "driver": ["recDX"]}}

    async def fl(table, formula="", fields=None, max_records=100):
        if table == at.DRIVERS:
            return [DRIVER] if "tokX" in formula else []
        if "assigned" in formula:
            return [MINE]
        return []
    for m in (at, dp.at):
        monkeypatch.setattr(m, "list_records", fl)
    d = client.get("/api/driver/tokX/orders").json()
    assert d["orders"][0]["kitchen_ready"] is True  # ready event logged earlier
