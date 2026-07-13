"""Private kitchen feedback (no public scoreboard), driver earnings, launch readiness."""
import datetime as _dt
import pytest
from fastapi.testclient import TestClient
import app.airtable_client as at
import app.dispatch as dp
import app.kitchen as kitchen_mod
from app.db import SessionLocal
from app.models import Partner
from app.main import app
from tests.fake_airtable import FakeAirtable

client = TestClient(app)
K = "/api/board/test-key"
fake = FakeAirtable()
NOW = _dt.datetime.now(_dt.timezone.utc)
TODAY = NOW.strftime("%Y-%m-%d")
D2 = (NOW - _dt.timedelta(days=2)).strftime("%Y-%m-%d")

DRV = fake.seed(at.DRIVERS, {"driver_id": "DRV-E1", "day_token": "tokE1",
                              "display_name": "Earner", "status": "active"})
fake.seed(at.ORDERS, {"order_id": "ORD-FB1", "status": "delivered", "partner_code": "stephens",
                       "driver": [DRV], "tip_cents": 500,
                       "received_at": f"{TODAY}T12:00:00.000Z",
                       "delivered_at": f"{TODAY}T12:40:00.000Z"})
fake.seed(at.ORDERS, {"order_id": "ORD-FB2", "status": "closed", "partner_code": "stephens",
                       "driver": [DRV], "tip_cents": 300,
                       "received_at": f"{D2}T12:00:00.000Z",
                       "delivered_at": f"{D2}T12:40:00.000Z"})
fake.seed(at.ORDERS, {"order_id": "ORD-FB3", "status": "in_transit", "partner_code": "stephens",
                       "received_at": f"{TODAY}T13:00:00.000Z"})


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    for m in (at, dp.at, kitchen_mod.at):
        monkeypatch.setattr(m, "list_records", fake.list_records)
        monkeypatch.setattr(m, "create_record", fake.create_record)
        monkeypatch.setattr(m, "patch_record", fake.patch_record)
    yield


def _tok():
    db = SessionLocal(); t = db.get(Partner, "stephens").portal_token; db.close(); return t


def test_feedback_is_private_and_reaches_the_kitchen():
    assert client.post("/v0/track/ORD-FB1/feedback",
                       json={"good": True, "note": "The crust was unreal"}).status_code == 200
    assert client.post("/v0/track/ORD-FB2/feedback",
                       json={"good": False, "note": "Arrived cold"}).status_code == 200
    d = client.get(f"/api/kitchen-feedback/{_tok()}").json()
    assert d["loved"] == 1 and d["issues"] == 1
    notes = {n["note"] for n in d["notes"]}
    assert "The crust was unreal" in notes and "Arrived cold" in notes
    # NO public rating anywhere: the public partner payload has no score
    pub = client.get("/v0/partners/stephens").json()
    assert not any(k in pub for k in ("rating", "stars", "score", "reviews"))


def test_feedback_requires_delivery():
    assert client.post("/v0/track/ORD-FB3/feedback",
                       json={"good": True}).status_code == 409
    assert client.post("/v0/track/ORD-NOPE/feedback",
                       json={"good": True}).status_code == 404


def test_kitchen_feedback_is_token_scoped():
    assert client.get("/api/kitchen-feedback/kt-bogus").status_code == 404
    bb = SessionLocal().get(Partner, "burgerboys").portal_token
    d = client.get(f"/api/kitchen-feedback/{bb}").json()
    assert d["loved"] == 0 and d["issues"] == 0   # another kitchen's notes never leak


def test_driver_earnings_ledger():
    d = client.get("/api/driver/tokE1/earnings").json()
    assert d["driver"] == "Earner"
    assert d["totals"]["deliveries"] == 2
    assert d["totals"]["tips_cents"] == 800
    days = {x["date"]: x for x in d["days"]}
    assert days[TODAY]["tips_cents"] == 500
    assert days[D2]["deliveries"] == 1


def test_launch_readiness_tells_the_truth():
    d = client.get(f"{K}/readiness").json()
    areas = {c["area"]: c for c in d["checks"]}
    assert "SMS (Twilio)" in areas and areas["SMS (Twilio)"]["ok"] is False
    assert "NOT SET" in areas["SMS (Twilio)"]["detail"]
    assert areas["Card payments (Stripe)"]["ok"] is False
    assert "CASH at the door" in areas["Card payments (Stripe)"]["detail"]
    assert any("Stephen" in a for a in areas)
    assert isinstance(d["ready_to_take_orders"], bool)
    assert client.get("/api/board/wrong/readiness").status_code == 403


def test_surfaces_carry_them():
    assert "feedback(" in client.get("/track/ORD-FB1").text
    assert "showFeedback" in client.get(f"/kitchen/{_tok()}").text
    assert "showEarnings" in client.get("/driver/tokE1").text
    assert "showReadiness" in client.get("/board/test-key").text
