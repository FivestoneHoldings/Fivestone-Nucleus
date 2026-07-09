"""Driver tips-today, kitchen self-pause, customer proof on tracking."""
import os, tempfile, base64
os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")
os.environ["ADMIN_KEY"] = "test-key"
os.environ["AIRTABLE_PAT"] = "fake-pat"

import pytest
from fastapi.testclient import TestClient
import app.airtable_client as at
import app.dispatch as dp
import app.intake as intake_mod
import app.kitchen as kitchen_mod
import app.track as track_mod
from app.db import SessionLocal
from app.models import Partner, Proof
from app.main import app
from tests.fake_airtable import FakeAirtable

client = TestClient(app)
fake = FakeAirtable()

DRV = fake.seed(at.DRIVERS, {"driver_id": "DRV-TP", "day_token": "tokTP",
                             "display_name": "Tipped", "status": "active"})
import datetime as _dt
TODAY = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
for tip, n in ((300, "T1"), (500, "T2")):
    fake.seed(at.ORDERS, {"order_id": f"ORD-TIP{n}", "status": "delivered",
                          "driver": [DRV], "tip_cents": tip,
                          "received_at": f"{TODAY}T15:00:00.000Z",
                          "delivered_at": f"{TODAY}T15:30:00.000Z"})
DELIVERED = fake.seed(at.ORDERS, {"order_id": "ORD-PRF01", "status": "delivered",
                                  "items_description": "1× Thing ($5.00)",
                                  "received_at": f"{TODAY}T14:00:00.000Z",
                                  "delivered_at": f"{TODAY}T14:20:00.000Z"})


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    for m in (at, dp.at, intake_mod.at, kitchen_mod.at, track_mod.at):
        monkeypatch.setattr(m, "list_records", fake.list_records)
        monkeypatch.setattr(m, "create_record", fake.create_record)
        monkeypatch.setattr(m, "patch_record", fake.patch_record)
    intake_mod._HITS.clear()
    yield


def test_driver_tips_today():
    d = client.get("/api/driver/tokTP/orders").json()
    assert d["done_today"] == 2
    assert d["tips_today_cents"] == 800


def test_kitchen_self_pause_and_resume():
    db = SessionLocal()
    tok = db.get(Partner, "stephens").portal_token
    db.close()
    r = client.post(f"/api/kitchen/{tok}/accepting", json={"on": False})
    assert r.status_code == 200 and r.json()["accepting"] is False
    # customer intake now blocked
    blocked = client.post("/v0/intake", json={"dropoff_address": "1 Elm",
                                              "items_description": "x", "partner": "stephens"},
                          headers={"x-forwarded-for": "2.2.2.2"})
    assert blocked.status_code == 423
    # kitchen feed reflects it; owned event logged by kitchen actor
    kd = client.get(f"/api/kitchen/{tok}/orders").json()
    assert kd["accepting"] is False
    ev = client.get("/api/board/test-key/events").json()["events"]
    assert any(e["event_type"] == "partner.paused" and e["actor"] == "kitchen:stephens"
               for e in ev)
    client.post(f"/api/kitchen/{tok}/accepting", json={"on": True})
    ok = client.post("/v0/intake", json={"dropoff_address": "1 Elm",
                                         "items_description": "x", "partner": "stephens"},
                     headers={"x-forwarded-for": "2.2.2.2"})
    assert ok.status_code == 200


def test_tracking_shows_proof_when_delivered():
    db = SessionLocal()
    db.add(Proof(order_id="ORD-PRF01",
                 content_b64=base64.b64encode(b"\xff\xd8\xff pic").decode()))
    db.commit(); db.close()
    html = client.get("/track/ORD-PRF01").text
    assert '/proof/ORD-PRF01' in html and "Delivery photo" in html
