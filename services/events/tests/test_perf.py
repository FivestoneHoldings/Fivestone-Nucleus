"""Round-trip budget tests: instrumented fake counts Airtable calls per screen load."""
import os, tempfile
os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")
os.environ["ADMIN_KEY"] = "test-key"
os.environ["AIRTABLE_PAT"] = "fake-pat"

import datetime as _dt
import pytest
from fastapi.testclient import TestClient
import app.airtable_client as at
import app.dispatch as dp
import app.track as track_mod
from app.main import app
from tests.fake_airtable import FakeAirtable

client = TestClient(app)
K = "/api/board/test-key"

fake = FakeAirtable()
TODAY = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
DRV = fake.seed(at.DRIVERS, {"driver_id": "DRV-PF", "day_token": "tokPF",
                              "display_name": "Perf", "status": "active"})
IT = fake.seed(at.ORDERS, {"order_id": "ORD-PF1", "status": "in_transit",
                            "driver": [DRV], "received_at": f"{TODAY}T15:00:00.000Z"})
fake.seed(at.ORDERS, {"order_id": "ORD-PF2", "status": "delivered", "driver": [DRV],
                       "tip_cents": 200, "received_at": f"{TODAY}T14:00:00.000Z",
                       "delivered_at": f"{TODAY}T14:30:00.000Z"})

CALLS = {"n": 0}


async def counting_list(table, formula="", fields=None, max_records=100):
    CALLS["n"] += 1
    return await fake.list_records(table, formula, fields, max_records)


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    for m in (at, dp.at, track_mod.at):
        monkeypatch.setattr(m, "list_records", counting_list)
        monkeypatch.setattr(m, "create_record", fake.create_record)
        monkeypatch.setattr(m, "patch_record", fake.patch_record)
    CALLS["n"] = 0
    yield


def test_driver_sheet_budget_cold_2_warm_1():
    d = client.get("/api/driver/tokPF/orders").json()
    assert d["done_today"] == 1 and d["tips_today_cents"] == 200
    assert len(d["orders"]) == 1  # active only
    assert CALLS["n"] == 3  # token + active + delivered-today (split v1.9.4:
    # the combined query capped at 100 records total, so delivered rows could
    # crowd a driver's LIVE order out of the window — it silently vanished
    # from their hub. The split runs concurrently (same wall-clock), and
    # active orders can never be truncated out by history. Correctness > 1 call.
    CALLS["n"] = 0
    client.get("/api/driver/tokPF/orders")
    assert CALLS["n"] == 2  # driver cached — active + delivered (split, concurrent)


def test_board_snapshot_budget_cold_3_warm_2():
    r = client.get(f"{K}/snapshot").json()
    assert "orders" in r and "drivers" in r and "stats" in r
    assert r["stats"]["orders_today"] == 2
    perf = [x for x in r["drivers"] if x["name"] == "Perf"][0]
    assert perf["active"] == 1
    assert CALLS["n"] == 3  # open + today + drivers
    CALLS["n"] = 0
    client.get(f"{K}/snapshot")
    assert CALLS["n"] == 2  # drivers cached — open + today only


def test_track_location_budget_warm_1():
    client.get("/v0/track/ORD-PF1/location")  # cold: order + driver-ref resolve = 2
    CALLS["n"] = 0
    live = client.get("/v0/track/ORD-PF1/location").json()
    assert live["live"] in (True, False)  # live depends on ping presence; budget is the point
    assert CALLS["n"] == 1  # driver-ref cached; only the live status query remains


def test_cache_busts_on_shift_mutation():
    client.get("/api/driver/tokPF/orders")  # warm the cache
    client.post("/api/driver/tokPF/shift", json={"on": True})  # mutation busts
    CALLS["n"] = 0
    client.get("/api/driver/tokPF/orders")
    assert CALLS["n"] == 3  # cold again — fresh truth after mutation (split budget)
