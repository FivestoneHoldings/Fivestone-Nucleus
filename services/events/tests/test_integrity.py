"""State-machine integrity: double-taps idempotent, illegal transitions 409,
exactly-one event and exactly-one SMS per real transition."""
import pytest
from fastapi.testclient import TestClient
import app.airtable_client as at
import app.dispatch as dp
import app.kitchen as kitchen_mod
import app.notify as notify
from app.db import SessionLocal
from app.models import Event, Partner
from app.main import app
from tests.fake_airtable import FakeAirtable

client = TestClient(app)
K = "/api/board/test-key"
fake = FakeAirtable()

DRV = fake.seed(at.DRIVERS, {"driver_id": "DRV-SM", "day_token": "tokSM",
                              "display_name": "Stately", "status": "active"})
SENT = []


async def fake_twilio(sid, token, from_, to, body):
    SENT.append(body)
    return True, "SM_x"


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    for m in (at, dp.at, kitchen_mod.at):
        monkeypatch.setattr(m, "list_records", fake.list_records)
        monkeypatch.setattr(m, "create_record", fake.create_record)
        monkeypatch.setattr(m, "patch_record", fake.patch_record)
    monkeypatch.setenv("TWILIO_SID", "AC_t")
    monkeypatch.setenv("TWILIO_TOKEN", "t")
    monkeypatch.setenv("TWILIO_FROM", "+15550000000")
    monkeypatch.setattr(notify, "_twilio_post", fake_twilio)
    yield


def _new_order(status="received", **extra):
    fields = {"order_id": f"ORD-SM{len(fake.tables.get(at.ORDERS, {})):04d}",
              "status": status, "customer_phone_raw": "865-555-0101",
              "received_at": "2026-07-10T01:00:00.000Z"}
    fields.update(extra)
    return fake.seed(at.ORDERS, fields), fields["order_id"]


def _events_of(oid, etype):
    db = SessionLocal()
    n = (db.query(Event).filter(Event.entity_ref == oid,
                                Event.event_type == etype).count())
    db.close()
    return n


def test_driver_double_delivered_is_idempotent_one_event_one_sms():
    rec, oid = _new_order("in_transit", driver=[DRV])
    SENT.clear()
    r1 = client.post(f"/api/driver/tokSM/orders/{rec}/delivered", json={})
    r2 = client.post(f"/api/driver/tokSM/orders/{rec}/delivered", json={})
    assert r1.status_code == 200 and r2.status_code == 200
    assert r2.json().get("idempotent") is True
    assert _events_of(oid, "order.delivered") == 1
    assert len(SENT) == 1  # exactly one "delivered" text


def test_skipping_pickup_is_409():
    rec, oid = _new_order("assigned", driver=[DRV])
    r = client.post(f"/api/driver/tokSM/orders/{rec}/delivered", json={})
    assert r.status_code == 409
    assert "refresh" in r.json()["detail"]


def test_double_assign_conflicts():
    rec, oid = _new_order("confirmed")
    assert client.post(f"{K}/orders/{rec}/assign",
                       json={"driver_id": DRV}).status_code == 200
    r2 = client.post(f"{K}/orders/{rec}/assign", json={"driver_id": DRV})
    assert r2.status_code == 409  # stale second dispatcher tab loses


def test_confirm_and_close_idempotent():
    rec, oid = _new_order("received")
    client.post(f"{K}/orders/{rec}/confirm")
    r = client.post(f"{K}/orders/{rec}/confirm")
    assert r.json().get("idempotent") is True
    assert _events_of(oid, "order.confirmed") == 1
    # walk to delivered then double-close
    fake.tables[at.ORDERS][rec]["status"] = "delivered"
    client.post(f"{K}/orders/{rec}/close")
    r2 = client.post(f"{K}/orders/{rec}/close")
    assert r2.json().get("idempotent") is True
    assert _events_of(oid, "order.closed") == 1


def test_cancel_delivered_is_409_requeue_needs_failed():
    rec, oid = _new_order("delivered")
    assert client.post(f"{K}/orders/{rec}/cancel", json={}).status_code == 409
    assert client.post(f"{K}/orders/{rec}/requeue").status_code == 409


def test_kitchen_double_ready_single_event():
    rec, oid = _new_order("confirmed", partner_code="stephens")
    db = SessionLocal()
    tok = db.get(Partner, "stephens").portal_token
    db.close()
    client.post(f"/api/kitchen/{tok}/orders/{rec}/ready", json={})
    r2 = client.post(f"/api/kitchen/{tok}/orders/{rec}/ready", json={})
    assert r2.json().get("idempotent") is True
    assert _events_of(oid, "order.kitchen_ready") == 1
