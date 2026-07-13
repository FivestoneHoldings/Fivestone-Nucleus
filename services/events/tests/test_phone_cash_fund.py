"""Phone-in orders, cash-on-delivery, and the community fund — three things a
platform built on app-only, card-only, extract-everything cannot do."""
import datetime as _dt
import pytest
from fastapi.testclient import TestClient
import app.airtable_client as at
import app.dispatch as dp
import app.intake as intake_mod
from app.main import app
from tests.fake_airtable import FakeAirtable

client = TestClient(app)
K = "/api/board/test-key"
fake = FakeAirtable()
TODAY = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")

DRV = fake.seed(at.DRIVERS, {"driver_id": "DRV-CASH", "day_token": "tokCASH",
                              "display_name": "Cash Carrier", "status": "active"})


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    for m in (at, dp.at, intake_mod.at):
        monkeypatch.setattr(m, "list_records", fake.list_records)
        monkeypatch.setattr(m, "create_record", fake.create_record)
        monkeypatch.setattr(m, "patch_record", fake.patch_record)
    yield


def test_phone_order_enters_the_same_record_path():
    r = client.post(f"{K}/phone-order", json={
        "partner": "burgerboys", "items": "1× Kobe Burger, 1× Mac & Cheese",
        "address": "12 Rural Route, Maryville TN", "name": "Ruth",
        "phone": "865-555-0144", "subtotal_cents": 1275, "tip_cents": 300,
        "notes": "Ring the bell twice, she's hard of hearing"})
    assert r.status_code == 200
    d = r.json()
    rec = fake.tables[at.ORDERS][d["record_id"]]
    assert rec["source_channel"] == "phone"
    assert rec["status"] == "received"                    # lands on the board like any order
    assert rec["partner_code"] == "burgerboys"
    assert rec["pickup_address"]                          # kitchen address auto-filled
    assert rec["total_cents"] == 1275 + rec["fee_cents"] + 300
    assert "hard of hearing" in rec["special_instructions"]
    ev = client.get(f"{K}/events").json()["events"]
    assert any(e["event_type"] == "order.received"
               and e["actor"] == "founder:phone"
               and e["entity_ref"] == d["order_id"] for e in ev)
    # it's trackable by the customer, exactly like an app order
    assert client.get(f"/track/{d['order_id']}").status_code == 200


def test_phone_order_validates():
    assert client.post(f"{K}/phone-order", json={"items": "x"}).status_code == 400
    assert client.post("/api/board/wrong/phone-order",
                       json={"items": "x", "address": "y"}).status_code == 403


def test_driver_sees_cash_to_collect_and_prepaid():
    cod = fake.seed(at.ORDERS, {"order_id": "ORD-COD1", "status": "assigned",
                                 "driver": [DRV], "total_cents": 2498,
                                 "received_at": f"{TODAY}T12:00:00.000Z"})
    dp._log_event("order.payment_method", "ORD-COD1", "customer", {"method": "cod"})
    card = fake.seed(at.ORDERS, {"order_id": "ORD-CARD1", "status": "assigned",
                                  "driver": [DRV], "total_cents": 1599,
                                  "received_at": f"{TODAY}T12:05:00.000Z"})
    dp._log_event("order.payment_method", "ORD-CARD1", "customer", {"method": "card"})
    sheet = client.get("/api/driver/tokCASH/orders").json()
    by_id = {o["order_id"]: o for o in sheet["orders"]}
    assert by_id["ORD-COD1"]["collect_cash_cents"] == 2498      # collect at the door
    assert by_id["ORD-CARD1"]["collect_cash_cents"] == 0        # prepaid, collect nothing


def test_community_fund_accumulates_and_counts_meals():
    oid = "ORD-FUND1"
    fake.seed(at.ORDERS, {"order_id": oid, "status": "delivered",
                           "received_at": f"{TODAY}T12:00:00.000Z"})
    before = client.get("/v0/community-fund").json()["cents"]
    assert client.post(f"/v0/track/{oid}/round-up", json={"cents": 500}).status_code == 200
    assert client.post(f"/v0/track/{oid}/round-up", json={"cents": 1000}).status_code == 200
    d = client.get("/v0/community-fund").json()
    assert d["cents"] == before + 1500
    assert d["gifts"] >= 2
    assert d["meals_covered"] == d["cents"] // 1200
    # guards
    assert client.post(f"/v0/track/{oid}/round-up", json={"cents": 0}).status_code == 400
    assert client.post("/v0/track/ORD-NOPE/round-up", json={"cents": 100}).status_code == 404


def test_surfaces_carry_the_three_features():
    assert "phoneOrder" in client.get("/board/test-key").text
    assert "COLLECT" in client.get("/driver/tokCASH").text
    assert "roundUp" in client.get("/track/ORD-FUND1").text
    assert "community-fund" in client.get("/").text
