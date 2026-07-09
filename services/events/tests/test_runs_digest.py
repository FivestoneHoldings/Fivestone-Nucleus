"""Multi-stop sorting, load counts, digest math, honest intake failures."""
import os, tempfile
os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")
os.environ["ADMIN_KEY"] = "test-key"
os.environ["AIRTABLE_PAT"] = "fake-pat"

import pytest
from fastapi.testclient import TestClient
import app.airtable_client as at
import app.dispatch as dp
import app.intake as intake_mod
from app.main import app

client = TestClient(app)
K = "/api/board/test-key"

DRIVER = {"id": "recRD", "fields": {"driver_id": "DRV-RD", "day_token": "tokRD",
                                     "display_name": "Runner"}}
STOPS = [
    {"id": "s1", "fields": {"order_id": "ORD-LATE", "status": "assigned", "driver": ["recRD"],
                             "received_at": "2026-07-09T18:00:00.000Z"}},
    {"id": "s2", "fields": {"order_id": "ORD-EARLY", "status": "assigned", "driver": ["recRD"],
                             "received_at": "2026-07-09T15:00:00.000Z"}},
    {"id": "s3", "fields": {"order_id": "ORD-SCHED", "status": "in_transit", "driver": ["recRD"],
                             "received_at": "2026-07-09T17:00:00.000Z",
                             "requested_for": "2026-07-09T12:00"}},
]
WEEK = [
    {"id": "w1", "fields": {"order_id": "ORD-D1", "status": "delivered", "partner_code": "stephens",
                             "received_at": "2026-07-08T15:00:00.000Z", "total_cents": 1000}},
    {"id": "w2", "fields": {"order_id": "ORD-D2", "status": "closed", "partner_code": "stephens",
                             "received_at": "2026-07-09T15:00:00.000Z", "total_cents": 2500}},
    {"id": "w3", "fields": {"order_id": "ORD-D3", "status": "cancelled", "partner_code": "stephens",
                             "received_at": "2026-07-09T16:00:00.000Z", "total_cents": 900}},
]


async def fake_list(table, formula="", fields=None, max_records=100):
    if table == at.DRIVERS:
        return [DRIVER] if "tokRD" in formula else [DRIVER]
    if ">='" in formula:
        return WEEK
    if "assigned" in formula or "closed" in formula:
        return STOPS
    return []


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    for m in (at, dp.at, intake_mod.at):
        monkeypatch.setattr(m, "list_records", fake_list)
    intake_mod._HITS.clear()
    yield


def test_run_sorted_scheduled_then_fifo():
    d = client.get("/api/driver/tokRD/orders").json()
    ids = [o["order_id"] for o in d["orders"]]
    assert ids == ["ORD-SCHED", "ORD-EARLY", "ORD-LATE"]


def test_board_driver_load_counts():
    d = client.get(f"{K}/orders").json()
    runner = [x for x in d["drivers"] if x["name"] == "Runner"][0]
    assert runner["active"] == 3


def test_digest_math():
    d = client.get(f"{K}/digest", params={"partner": "stephens"}).json()
    assert d["totals"]["orders"] == 3
    assert d["totals"]["delivered"] == 2
    assert d["totals"]["revenue_cents"] == 3500  # cancelled excluded
    day9 = [x for x in d["days"] if x["date"] == "2026-07-09"][0]
    assert day9["orders"] == 2 and day9["delivered"] == 1


def test_intake_unconfigured_is_honest(monkeypatch):
    monkeypatch.setattr(intake_mod.at, "configured", lambda: False)
    r = client.post("/v0/intake", json={"dropoff_address": "1 Elm", "items_description": "x"},
                    headers={"x-forwarded-for": "5.5.5.5"})
    assert r.status_code == 503
    assert r.json()["received"] is False


def test_intake_write_failure_is_honest(monkeypatch):
    async def boom(table, fields):
        raise RuntimeError("airtable down")
    monkeypatch.setattr(intake_mod.at, "create_record", boom)
    r = client.get("/v0/intake", params={"dropoff_address": "2 Oak", "items_description": "y"},
                   headers={"x-forwarded-for": "4.4.4.4"})
    assert r.status_code == 503
    assert "NOT placed" in r.text
    ev = client.get(f"{K}/events").json()["events"]
    assert any(e["event_type"] == "order.intake_error" for e in ev)
