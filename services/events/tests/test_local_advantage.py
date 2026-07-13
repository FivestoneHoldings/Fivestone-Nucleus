"""Features the chains structurally can't do: cook-posted specials, reopen alerts,
account-free post-delivery tipping."""
import datetime as _dt
import pytest
from fastapi.testclient import TestClient
import app.airtable_client as at
import app.dispatch as dp
import app.identity as identity_mod
import app.kitchen as kitchen_mod
import app.notify as notify
from app.db import SessionLocal
from app.models import Partner, ReopenAlert
from app.main import app
from tests.fake_airtable import FakeAirtable

client = TestClient(app)
K = "/api/board/test-key"
fake = FakeAirtable()
TODAY = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
SENT = []

DONE = fake.seed(at.ORDERS, {"order_id": "ORD-TIP-DONE", "status": "delivered",
                              "partner_code": "stephens", "tip_cents": 300,
                              "total_cents": 2498, "received_at": f"{TODAY}T12:00:00.000Z",
                              "delivered_at": f"{TODAY}T12:40:00.000Z"})
MOVING = fake.seed(at.ORDERS, {"order_id": "ORD-TIP-MOVING", "status": "in_transit",
                                "partner_code": "stephens", "tip_cents": 0,
                                "total_cents": 1000, "received_at": f"{TODAY}T12:00:00.000Z"})


async def fake_twilio(sid, token, from_, to, body):
    SENT.append((to, body))
    return True, "SM_1"


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    for m in (at, dp.at, kitchen_mod.at):
        monkeypatch.setattr(m, "list_records", fake.list_records)
        monkeypatch.setattr(m, "patch_record", fake.patch_record)
        monkeypatch.setattr(m, "create_record", fake.create_record)
    monkeypatch.setenv("TWILIO_SID", "AC_x")
    monkeypatch.setenv("TWILIO_TOKEN", "t")
    monkeypatch.setenv("TWILIO_FROM", "+15550001111")
    monkeypatch.setattr(notify, "_twilio_post", fake_twilio)
    SENT.clear()
    yield


def _ktok(code="stephens"):
    db = SessionLocal(); t = db.get(Partner, code).portal_token; db.close(); return t


def test_cook_posts_special_and_customers_see_it():
    r = client.post(f"/api/kitchen/{_ktok()}/special",
                    json={"text": "Brisket just came off the smoker"})
    assert r.status_code == 200
    # public payloads carry it same-day
    assert "Brisket" in client.get("/v0/partners/stephens").json()["special"]
    assert any("Brisket" in (p.get("special") or "")
               for p in client.get("/v0/partners").json()["partners"])
    # kitchen sees it on their own screen feed
    assert "Brisket" in client.get(f"/api/kitchen/{_ktok()}/orders").json()["special"]
    # owned event records who posted it
    ev = client.get(f"{K}/events").json()["events"]
    assert any(e["event_type"] == "partner.special_posted"
               and e["actor"] == "kitchen:stephens" for e in ev)
    # clearing works
    client.post(f"/api/kitchen/{_ktok()}/special", json={"text": ""})
    assert client.get("/v0/partners/stephens").json()["special"] == ""


def test_special_expires_with_the_day():
    db = SessionLocal()
    p = db.get(Partner, "stephens")
    p.special_text = "Yesterday's fish"
    p.special_date = "2020-01-01"
    db.commit(); db.close()
    assert client.get("/v0/partners/stephens").json()["special"] == ""


def test_reopen_alert_captures_demand_and_texts_on_resume():
    client.post(f"{K}/partners/burgerboys/accepting", json={"on": False})
    r = client.post("/v0/partners/burgerboys/notify-me", json={"phone": "865-555-0199"})
    assert r.status_code == 200
    # dupes don't stack
    client.post("/v0/partners/burgerboys/notify-me", json={"phone": "8655550199"})
    db = SessionLocal()
    waiting = db.query(ReopenAlert).filter(ReopenAlert.partner_code == "burgerboys",
                                           ReopenAlert.notified == False).count()  # noqa: E712
    db.close()
    assert waiting == 1
    assert client.post("/v0/partners/burgerboys/notify-me",
                       json={"phone": "123"}).status_code == 400
    # resume → the waiting neighbor gets exactly one text
    client.post(f"{K}/partners/burgerboys/accepting", json={"on": True})
    assert len(SENT) == 1
    to, body = SENT[0]
    assert "8655550199" in to.replace("+1", "")
    assert "Burger Boys" in body and "order?partner=burgerboys" in body
    # resuming again doesn't re-text
    SENT.clear()
    client.post(f"{K}/partners/burgerboys/accepting", json={"on": True})
    assert SENT == []


def test_post_delivery_tip_no_account_needed():
    r = client.post("/v0/track/ORD-TIP-DONE/tip", json={"cents": 500})
    assert r.status_code == 200
    assert r.json()["tip_cents"] == 800            # 300 existing + 500 added
    rec = fake.tables[at.ORDERS][DONE]
    assert rec["tip_cents"] == 800
    assert rec["total_cents"] == 2998              # total follows the tip
    ev = client.get(f"{K}/events").json()["events"]
    assert any(e["event_type"] == "order.tip_added" and e["actor"] == "customer" for e in ev)


def test_tip_guards():
    assert client.post("/v0/track/ORD-TIP-MOVING/tip",
                       json={"cents": 200}).status_code == 409   # not delivered yet
    assert client.post("/v0/track/ORD-TIP-DONE/tip",
                       json={"cents": 0}).status_code == 400
    assert client.post("/v0/track/ORD-TIP-DONE/tip",
                       json={"cents": 999999}).status_code == 400
    assert client.post("/v0/track/ORD-NOPE/tip",
                       json={"cents": 200}).status_code == 404


def test_surfaces_carry_the_new_features():
    home = client.get("/").text
    assert "notifyMe" in home and "Text me when they" in home
    kitchen = client.get(f"/kitchen/{_ktok()}").text
    assert "editSpecial" in kitchen and "Post today" in kitchen
    track = client.get("/track/ORD-TIP-DONE").text
    assert "addTip" in track and "100% goes to them" in track
