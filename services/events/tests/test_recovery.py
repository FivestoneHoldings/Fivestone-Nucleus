"""Failed-order recovery + manual notify tests."""
import os, tempfile
os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")
os.environ["ADMIN_KEY"] = "test-key"
os.environ["AIRTABLE_PAT"] = "fake-pat"

import pytest
from fastapi.testclient import TestClient
import app.airtable_client as at
import app.dispatch as dp
import app.notify as notify
from app.main import app

client = TestClient(app)
K = "/api/board/test-key"
PATCHES = []
ORDER = {"id": "recF", "fields": {"order_id": "ORD-FAIL01", "status": "failed",
                                   "customer_phone_raw": "865-555-0150"}}


async def fake_list(table, formula="", fields=None, max_records=100):
    if "RECORD_ID()" in formula:
        return [ORDER]
    return []


async def fake_patch(table, record_id, fields):
    PATCHES.append(fields)
    merged = dict(ORDER["fields"]); merged.update(fields)
    return {"id": record_id, "fields": merged}


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    for m in (at, dp.at):
        monkeypatch.setattr(m, "list_records", fake_list)
        monkeypatch.setattr(m, "patch_record", fake_patch)
    yield


def test_requeue_failed_to_confirmed():
    r = client.post(f"{K}/orders/recF/requeue")
    assert r.status_code == 200
    assert PATCHES[-1]["status"] == "confirmed" and PATCHES[-1]["failed_at"] == ""
    ev = client.get(f"{K}/events").json()["events"]
    assert any(e["event_type"] == "order.requeued" for e in ev)


def test_manual_notify_records(monkeypatch):
    for v in ("TWILIO_SID", "TWILIO_TOKEN", "TWILIO_FROM"):
        monkeypatch.delenv(v, raising=False)
    r = client.post(f"{K}/orders/recF/notify", json={"message": "Running 10 min late, sorry!"})
    assert r.status_code == 200
    assert r.json()["sms_status"] == "skipped_unconfigured"
    notifs = client.get(f"{K}/notifications").json()["notifications"]
    assert notifs[0]["body"] == "Running 10 min late, sorry!"


def test_notify_requires_message():
    assert client.post(f"{K}/orders/recF/notify", json={}).status_code == 400


def test_recovery_requires_key():
    assert client.post("/api/board/wrong/orders/recF/requeue").status_code == 403
