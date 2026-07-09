"""Board lifecycle, driver management, stats, and owned-log tests."""
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
K = "/api/board/test-key"

CREATED, PATCHES = [], []
FAKE_ORDER_FIELDS = {"order_id": "ORD-BB", "status": "delivered",
                     "received_at": "2026-07-08T20:00:00.000Z",
                     "delivered_at": "2026-07-08T20:25:00.000Z",
                     "partner_code": "asiacafe"}


async def fake_list(table, formula="", fields=None, max_records=100):
    if table == at.DRIVERS:
        return [{"id": "recD1", "fields": {"driver_id": "DRV-1", "display_name": "A",
                                            "status": "active", "day_token": "gw-aaaa"}}]
    return [{"id": "recO1", "fields": dict(FAKE_ORDER_FIELDS)}]


async def fake_patch(table, record_id, fields):
    PATCHES.append((table, record_id, fields))
    merged = dict(FAKE_ORDER_FIELDS); merged.update(fields)
    return {"id": record_id, "fields": merged}


async def fake_create(table, fields):
    CREATED.append((table, fields))
    return {"id": "recNEW", "fields": fields}


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    for m in (at, dp.at):
        monkeypatch.setattr(m, "list_records", fake_list)
        monkeypatch.setattr(m, "patch_record", fake_patch)
        monkeypatch.setattr(m, "create_record", fake_create)
    yield


def test_close_and_cancel():
    r = client.post(f"{K}/orders/recO1/close")
    assert r.status_code == 200
    assert PATCHES[-1][2]["status"] == "closed" and "closed_at" in PATCHES[-1][2]
    r = client.post(f"{K}/orders/recO1/cancel", json={"reason": "customer changed mind"})
    assert r.status_code == 200
    f = PATCHES[-1][2]
    assert f["status"] == "cancelled" and f["cancel_reason"] == "customer changed mind"


def test_driver_create_and_rotate():
    r = client.post(f"{K}/drivers", json={"name": "New Driver"})
    assert r.status_code == 200
    tok = r.json()["day_token"]
    assert tok.startswith("gw-") and len(tok) == 11
    assert CREATED[-1][1]["display_name"] == "New Driver"
    r2 = client.post(f"{K}/drivers/recD1/rotate")
    assert r2.status_code == 200
    assert r2.json()["day_token"] != tok  # fresh random token
    assert PATCHES[-1][2]["day_token"] == r2.json()["day_token"]


def test_driver_create_requires_name():
    assert client.post(f"{K}/drivers", json={}).status_code == 400


def test_stats_shape():
    r = client.get(f"{K}/stats")
    assert r.status_code == 200
    d = r.json()
    assert d["orders_today"] == 1
    assert d["by_partner"] == {"asiacafe": 1}
    assert d["avg_received_to_delivered_min"] == 25.0


def test_owned_events_feed():
    client.post(f"{K}/orders/recO1/close")  # generates an owned-log event
    r = client.get(f"{K}/events")
    assert r.status_code == 200
    assert any(e["event_type"] == "order.closed" for e in r.json()["events"])


def test_board_ops_require_key():
    assert client.get("/api/board/wrong/stats").status_code == 403
    assert client.post("/api/board/wrong/drivers", json={"name": "x"}).status_code == 403
