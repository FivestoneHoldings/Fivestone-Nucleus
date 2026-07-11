"""Dinner-rush simulation: 12 simultaneous orders, 3 kitchens, 4 drivers.
Asserts urgency ordering, payload completeness, stats math under load."""
import datetime as _dt
import pytest
from fastapi.testclient import TestClient
import app.airtable_client as at
import app.dispatch as dp
from app.main import app
from tests.fake_airtable import FakeAirtable

client = TestClient(app)
K = "/api/board/test-key"
fake = FakeAirtable()
TODAY = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")

DRIVERS = [fake.seed(at.DRIVERS, {"driver_id": f"DRV-R{i}", "day_token": f"tokR{i}",
                                   "display_name": f"Rush {i}", "status": "active"})
           for i in range(4)]

# the rush: statuses deliberately shuffled, timestamps interleaved
RUSH = [
    ("in_transit", "stephens",  "12:10", 0), ("received",  "burgerboys", "12:26", None),
    ("confirmed",  "friendsbbq","12:15", None), ("failed",   "stephens",  "12:05", 1),
    ("assigned",   "burgerboys","12:18", 2), ("received",  "stephens",  "12:22", None),
    ("delivered",  "friendsbbq","11:50", 3), ("confirmed", "burgerboys", "12:20", None),
    ("in_transit", "friendsbbq","12:08", 3), ("received",  "friendsbbq", "12:28", None),
    ("assigned",   "stephens",  "12:12", 0), ("failed",    "burgerboys", "12:01", 2),
]
for i, (status, partner, hm, drv) in enumerate(RUSH):
    fields = {"order_id": f"ORD-RUSH{i:02d}", "status": status, "partner_code": partner,
              "items_description": f"item {i}", "received_at": f"{TODAY}T{hm}:00.000Z"}
    if status in ("delivered",):
        fields["delivered_at"] = f"{TODAY}T12:40:00.000Z"
    if drv is not None:
        fields["driver"] = [DRIVERS[drv]]
    fake.seed(at.ORDERS, fields)


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    for m in (at, dp.at):
        monkeypatch.setattr(m, "list_records", fake.list_records)
    yield


def test_rush_snapshot_urgency_order():
    d = client.get(f"{K}/snapshot").json()
    statuses = [o["status"] for o in d["orders"]]
    # failed first, then received, confirmed, assigned, in_transit, delivered
    prio = {"failed": 0, "received": 1, "confirmed": 2, "assigned": 3,
            "in_transit": 4, "delivered": 5}
    assert statuses == sorted(statuses, key=lambda s: prio[s])
    # oldest-first within the failed group
    failed = [o for o in d["orders"] if o["status"] == "failed"]
    assert failed[0]["order_id"] == "ORD-RUSH11"  # 12:01 before 12:05


def test_rush_payload_complete_for_ui():
    d = client.get(f"{K}/snapshot").json()
    assert len(d["orders"]) == 12
    for o in d["orders"]:
        assert o["partner"] in ("stephens", "burgerboys", "friendsbbq")
        assert o["received_at"].startswith(TODAY)


def test_rush_driver_loads():
    d = client.get(f"{K}/snapshot").json()
    loads = {x["name"]: x["active"] for x in d["drivers"] if x["name"].startswith("Rush")}
    assert loads["Rush 0"] == 2   # in_transit + assigned
    assert loads["Rush 1"] == 0   # only a failed order — not active load
    assert loads["Rush 2"] == 1   # assigned (failed one doesn't count)
    assert loads["Rush 3"] == 1   # in_transit (delivered done)


def test_rush_stats_math():
    d = client.get(f"{K}/snapshot").json()
    st = d["stats"]
    assert st["orders_today"] == 12
    assert st["by_status"]["received"] == 3
    assert st["by_status"]["failed"] == 2
    assert st["by_partner"]["friendsbbq"] == 4
    assert st["delivered_today"] == 1


def test_rush_driver_run_payload():
    """Driver 0 carries in_transit + assigned: run must be sorted, complete, and navigable."""
    d = client.get("/api/driver/tokR0/orders").json()
    assert len(d["orders"]) == 2
    # server sort: FIFO by received_at (no scheduled here) — 12:10 in_transit before 12:12 assigned
    assert [o["order_id"] for o in d["orders"]] == ["ORD-RUSH00", "ORD-RUSH10"]
    for o in d["orders"]:
        # everything the card needs to render the run experience
        for k in ("pickup", "dropoff", "status", "kitchen_ready", "requested_for"):
            assert k in o


def test_summary_honors_explicit_past_date():
    """Day-open fetches yesterday's scorecard via /summary?date= — pin the param."""
    y = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=1)).strftime("%Y-%m-%d")
    d = client.get(f"{K}/summary", params={"date": y}).json()
    assert d["date"] == y            # not silently coerced to today
