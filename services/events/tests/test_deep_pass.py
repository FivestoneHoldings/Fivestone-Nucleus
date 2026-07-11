"""Deep-pass tests: retry/backoff, throttle, caps, tips, notes, summary, CSV, directory."""
import os, tempfile
os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")
os.environ["ADMIN_KEY"] = "test-key"
os.environ["AIRTABLE_PAT"] = "fake-pat"

import asyncio
import httpx
import pytest
from fastapi.testclient import TestClient
import app.airtable_client as at
import app.dispatch as dp
import app.intake as intake_mod
from app.main import app

client = TestClient(app)
K = "/api/board/test-key"

DRIVER = {"id": "recDP", "fields": {"driver_id": "DRV-DP", "day_token": "tokDP",
                                     "display_name": "Deep"}}
DAY_ORDERS = [
    {"id": "r1", "fields": {"order_id": "ORD-A", "status": "delivered", "partner_code": "stephens",
                             "total_cents": 2198, "received_at": "2026-07-09T15:00:00.000Z",
                             "delivered_at": "2026-07-09T15:30:00.000Z", "driver": ["recDP"]}},
    {"id": "r2", "fields": {"order_id": "ORD-B", "status": "cancelled", "partner_code": "stephens",
                             "received_at": "2026-07-09T16:00:00.000Z"}},
    {"id": "r3", "fields": {"order_id": "ORD-C", "status": "failed",
                             "received_at": "2026-07-09T17:00:00.000Z"}},
]
CREATED = []


async def fake_list(table, formula="", fields=None, max_records=100):
    if table == at.DRIVERS:
        return [DRIVER] if ("tokDP" in formula or "recDP" in formula) else []
    if "RECORD_ID()" in formula:
        return [DAY_ORDERS[0]]
    if "partner_code" in formula:
        return [r for r in DAY_ORDERS if r["fields"].get("partner_code") == "stephens"]
    if "YYYY-MM-DD" in formula or "received_at" in formula or "delivered_at" in formula:
        return DAY_ORDERS
    return []


async def fake_create(table, fields):
    CREATED.append(fields)
    return {"id": "recNEW", "fields": fields}


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    for m in (at, dp.at, intake_mod.at):
        monkeypatch.setattr(m, "list_records", fake_list)
        monkeypatch.setattr(m, "create_record", fake_create)
    intake_mod._HITS.clear()
    yield


def test_retry_backoff_on_429(monkeypatch):
    calls = {"n": 0}

    class FakeResp:
        def __init__(self, code): self.status_code = code
        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("x", request=None, response=None)
        def json(self): return {"records": []}

    class FakeClient:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def request(self, method, url, **kw):
            calls["n"] += 1
            return FakeResp(429 if calls["n"] < 3 else 200)

    monkeypatch.setattr(at.httpx, "AsyncClient", FakeClient)
    _orig_sleep = asyncio.sleep
    monkeypatch.setattr(at.asyncio, "sleep", lambda s: _orig_sleep(0))
    r = asyncio.get_event_loop().run_until_complete(at._request("GET", "http://x"))
    assert r.status_code == 200 and calls["n"] == 3  # two retries then success


def test_intake_throttle_429():
    ok = 0
    for i in range(31):
        r = client.post("/v0/intake", json={"dropoff_address": f"{i} Elm",
                                            "items_description": "x"},
                        headers={"x-forwarded-for": "9.9.9.9"})
        if r.status_code == 200:
            ok += 1
    assert ok == 30
    r = client.post("/v0/intake", json={"dropoff_address": "z", "items_description": "x"},
                    headers={"x-forwarded-for": "9.9.9.9"})
    assert r.status_code == 429


def test_intake_caps_and_tip():
    r = client.post("/v0/intake", json={
        "dropoff_address": "1 Elm", "items_description": "y" * 5000,
        "tip_cents": "300", "total_cents": "2498"},
        headers={"x-forwarded-for": "8.8.8.8"})
    assert r.status_code == 200
    f = CREATED[-1]
    assert len(f["items_description"]) == 1000  # capped
    assert f["tip_cents"] == 300 and f["total_cents"] == 2498


def test_driver_note_logged():
    r = client.post("/api/driver/tokDP/orders/r1/note", json={"text": "gate code 4412"})
    assert r.status_code == 200
    ev = client.get(f"{K}/events").json()["events"]
    assert any(e["event_type"] == "order.driver_note" and "4412" in e["payload"] for e in ev)
    assert client.post("/api/driver/tokDP/orders/r1/note", json={}).status_code == 400


def test_day_summary_math():
    d = client.get(f"{K}/summary").json()
    assert d["orders"] == 3 and d["delivered"] == 1
    assert d["cancelled"] == 1 and d["failed_open"] == 1
    assert d["revenue_cents"] == 2198 and d["avg_minutes"] == 30.0
    dp_ = client.get(f"{K}/summary", params={"partner": "stephens"}).json()
    assert dp_["orders"] == 2


def test_csv_export():
    r = client.get(f"{K}/export.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "ORD-A" in r.text and "total_usd" in r.text.splitlines()[0]


def test_public_partner_directory():
    d = client.get("/v0/partners").json()
    codes = [p["code"] for p in d["partners"]]
    assert "burgerboys" in codes and "friendsbbq" in codes and "stephens" in codes
    # asiacafe has no menu → not in the directory
    assert "asiacafe" not in codes


def test_driver_sheet_reports_done_today():
    d = client.get("/api/driver/tokDP/orders").json()
    assert d["done_today"] == 1


def test_healthz_deep():
    d = client.get("/healthz").json()
    assert d["ok"] is True and d["db"] == "up" and d["version"]
