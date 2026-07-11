"""Kitchen rush: FIFO rail, picked-up tickets leave, scheduled-order date fix."""
import datetime as _dt
import pytest
from fastapi.testclient import TestClient
import app.airtable_client as at
import app.kitchen as kitchen_mod
from app.db import SessionLocal
from app.models import Partner
from app.main import app
from tests.fake_airtable import FakeAirtable

client = TestClient(app)
fake = FakeAirtable()
NOW = _dt.datetime.now(_dt.timezone.utc)
TODAY = NOW.strftime("%Y-%m-%d")
YESTERDAY = (NOW - _dt.timedelta(days=1)).strftime("%Y-%m-%d")

SEED = [
    # (order_id, status, received, requested_for)
    ("ORD-KR-LATE",  "received",   f"{TODAY}T12:20:00.000Z", ""),
    ("ORD-KR-EARLY", "confirmed",  f"{TODAY}T12:05:00.000Z", ""),
    ("ORD-KR-ASGN",  "assigned",   f"{TODAY}T12:12:00.000Z", ""),
    ("ORD-KR-GONE1", "in_transit", f"{TODAY}T11:40:00.000Z", ""),
    ("ORD-KR-GONE2", "delivered",  f"{TODAY}T11:20:00.000Z", ""),
    # the scheduled-order bug case: placed YESTERDAY for TODAY 17:00
    ("ORD-KR-SCHED", "confirmed",  f"{YESTERDAY}T18:00:00.000Z", f"{TODAY}T17:00"),
]
for oid, status, recv, sched in SEED:
    f = {"order_id": oid, "status": status, "partner_code": "burgerboys",
         "items_description": oid, "received_at": recv}
    if sched:
        f["requested_for"] = sched
    fake.seed(at.ORDERS, f)


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    for m in (at, kitchen_mod.at):
        monkeypatch.setattr(m, "list_records", fake.list_records)
    yield


def _tok():
    db = SessionLocal()
    tok = db.get(Partner, "burgerboys").portal_token
    db.close()
    return tok


def test_rail_is_fifo_and_active_only():
    d = client.get(f"/api/kitchen/{_tok()}/orders").json()
    ids = [o["order_id"] for o in d["orders"]]
    # picked-up + delivered are OFF the rail
    assert "ORD-KR-GONE1" not in ids and "ORD-KR-GONE2" not in ids
    # FIFO by (requested_for or received_at): 12:05, 12:12, 12:20, then 17:00 scheduled
    assert ids == ["ORD-KR-EARLY", "ORD-KR-ASGN", "ORD-KR-LATE", "ORD-KR-SCHED"]


def test_scheduled_for_today_appears_despite_old_received_date():
    d = client.get(f"/api/kitchen/{_tok()}/orders").json()
    assert any(o["order_id"] == "ORD-KR-SCHED" for o in d["orders"])


def test_picked_up_counter():
    d = client.get(f"/api/kitchen/{_tok()}/orders").json()
    assert d["picked_up_today"] == 2
