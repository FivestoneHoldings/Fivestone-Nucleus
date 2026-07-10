"""Notification engine tests — outbox always records, flow never breaks."""
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

FAKE_DRIVER = {"id": "recDRV1", "fields": {"display_name": "T", "day_token": "tok123"}}
ORDER_FIELDS = {"order_id": "ORD-NOTIF1", "status": "assigned",
                "customer_phone_raw": "865-555-0123"}
SENT = []


async def fake_list(table, formula="", fields=None, max_records=100):
    if table == at.DRIVERS:
        return [FAKE_DRIVER] if "tok123" in formula else []
    if "RECORD_ID()" in formula:
        return [{"id": "recO", "fields": dict(ORDER_FIELDS, driver=["recDRV1"])}]
    return []


async def fake_patch(table, record_id, fields):
    ORDER_FIELDS.update(fields)  # stateful: transitions persist like production
    return {"id": record_id, "fields": dict(ORDER_FIELDS)}


async def fake_create(table, fields):
    return {"id": "recNEW", "fields": fields}


async def fake_twilio(sid, token, from_, to, body):
    SENT.append((to, body))
    return True, "SM_fake"


@pytest.fixture(autouse=True)
def _reset_status():
    ORDER_FIELDS["status"] = "assigned"
    yield


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    for m in (at, dp.at):
        monkeypatch.setattr(m, "list_records", fake_list)
        monkeypatch.setattr(m, "patch_record", fake_patch)
        monkeypatch.setattr(m, "create_record", fake_create)
    yield


def test_phone_normalization():
    assert notify.normalize_phone("865-555-0100") == "+18655550100"
    assert notify.normalize_phone("(865) 555-0100") == "+18655550100"
    assert notify.normalize_phone("1 865 555 0100") == "+18655550100"
    assert notify.normalize_phone("+448081570192") == "+448081570192"
    assert notify.normalize_phone("55") == ""


def test_unconfigured_records_skip_and_flow_survives(monkeypatch):
    for v in ("TWILIO_SID", "TWILIO_TOKEN", "TWILIO_FROM"):
        monkeypatch.delenv(v, raising=False)
    r = client.post("/api/driver/tok123/orders/recO/picked_up")
    assert r.status_code == 200  # order flow unbroken
    notifs = client.get("/api/board/test-key/notifications").json()["notifications"]
    assert notifs[0]["status"] == "skipped_unconfigured"
    assert "on the way" in notifs[0]["body"]
    assert "/track/ORD-NOTIF1" in notifs[0]["body"]


def test_configured_sends_on_pickup_and_delivered(monkeypatch):
    monkeypatch.setenv("TWILIO_SID", "AC_test")
    monkeypatch.setenv("TWILIO_TOKEN", "tok")
    monkeypatch.setenv("TWILIO_FROM", "+15550001111")
    monkeypatch.setattr(notify, "_twilio_post", fake_twilio)
    client.post("/api/driver/tok123/orders/recO/picked_up")
    client.post("/api/driver/tok123/orders/recO/delivered")
    assert len(SENT) == 2
    assert SENT[0][0] == "+18655550123" and "on the way" in SENT[0][1]
    assert "delivered" in SENT[1][1]
    notifs = client.get("/api/board/test-key/notifications").json()["notifications"]
    assert notifs[0]["status"] == "sent" and notifs[1]["status"] == "sent"


def test_bad_phone_skipped_not_crashed(monkeypatch):
    monkeypatch.setenv("TWILIO_SID", "AC_test")
    monkeypatch.setenv("TWILIO_TOKEN", "tok")
    monkeypatch.setenv("TWILIO_FROM", "+15550001111")
    import asyncio
    st = asyncio.get_event_loop().run_until_complete(
        notify.send_sms("ORD-X", "not a phone", "hi"))
    assert st == "skipped_no_phone"


def test_pwa_assets_served():
    assert client.get("/static/manifest.json").status_code == 200
    assert client.get("/static/icon-192.png").status_code == 200
    assert client.get("/static/sw.js").status_code == 200
    assert "manifest.json" in client.get("/order").text
