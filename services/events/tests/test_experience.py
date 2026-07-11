"""Differentiation layer: retention, demo orders, thank-you notes, profile surfaces."""
import datetime as _dt
import pytest
from fastapi.testclient import TestClient
import app.airtable_client as at
import app.dispatch as dp
import app.track as track_mod
from app.db import SessionLocal
from app.models import DriverLocation, Partner, Proof
from app.main import app
from tests.fake_airtable import FakeAirtable

client = TestClient(app)
K = "/api/board/test-key"
fake = FakeAirtable()
TODAY = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")

DRV = fake.seed(at.DRIVERS, {"driver_id": "DRV-XP", "day_token": "tokXP",
                              "display_name": "Marcus Webb", "status": "active"})
fake.seed(at.ORDERS, {"order_id": "ORD-XP-RUN", "status": "in_transit", "driver": [DRV],
                       "partner_code": "stephens", "items_description": "1× Pie ($4.00)",
                       "received_at": f"{TODAY}T12:00:00.000Z"})
fake.seed(at.ORDERS, {"order_id": "ORD-XP-DONE", "status": "delivered",
                       "partner_code": "stephens", "items_description": "1× Pie ($4.00)",
                       "total_cents": 400, "received_at": f"{TODAY}T11:00:00.000Z",
                       "delivered_at": f"{TODAY}T11:30:00.000Z"})


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    for m in (at, dp.at, track_mod.at):
        monkeypatch.setattr(m, "list_records", fake.list_records)
        monkeypatch.setattr(m, "create_record", fake.create_record)
        monkeypatch.setattr(m, "patch_record", fake.patch_record)
    yield


def test_retention_sweep_purges_stale():
    db = SessionLocal()
    old = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None) - _dt.timedelta(days=90)
    db.add(DriverLocation(driver_ref="DRV-OLD", lat="1", lng="1", updated_at=old))
    db.add(Proof(order_id="ORD-ANCIENT", content_b64="eA==", created_at=old))
    db.add(DriverLocation(driver_ref="DRV-FRESH", lat="2", lng="2"))
    db.commit(); db.close()
    r = dp.retention_sweep(force=True)
    assert r["swept"] and r["locations_purged"] >= 1 and r["proofs_purged"] >= 1
    db = SessionLocal()
    assert db.get(DriverLocation, "DRV-OLD") is None
    assert db.get(DriverLocation, "DRV-FRESH") is not None
    db.close()


def test_demo_order_priced_from_menu():
    r = client.post(f"{K}/partners/stephens/demo-order")
    assert r.status_code == 200
    d = r.json()
    assert d["order_id"].startswith("ORD-")
    rec = fake.tables[at.ORDERS][d["record_id"]]
    assert rec["partner_code"] == "stephens"
    assert rec["total_cents"] == rec["subtotal_cents"] + rec["fee_cents"] + rec["tip_cents"]
    assert rec["source_channel"] == "demo"
    ev = client.get(f"{K}/events").json()["events"]
    assert any(e["actor"] == "founder:demo" and e["entity_ref"] == d["order_id"] for e in ev)


def test_thanks_note_flow_to_delivered_page():
    r = client.post(f"{K}/partners/stephens/thanks",
                    json={"note": "Grazie! — the Stephen's family"})
    assert r.status_code == 200
    html = client.get("/track/ORD-XP-DONE").text
    assert "A note from Stephen" in html and "Grazie!" in html
    # active order does NOT show the note
    assert "Grazie!" not in client.get("/track/ORD-XP-RUN").text


def test_neighbor_name_on_active_tracking():
    html = client.get("/track/ORD-XP-RUN").text
    assert "Marcus is on the way" in html
    assert "Webb" not in html  # first name only


def test_me_page_serves_profile_experience():
    html = client.get("/me").text
    for needle in ("only on this device", "kept in local kitchens", "Erase my profile",
                   "gw-profile.js", "Saved addresses"):
        assert needle in html
