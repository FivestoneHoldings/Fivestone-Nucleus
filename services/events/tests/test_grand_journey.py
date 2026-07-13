"""THE GRAND JOURNEY — one order through every differentiation layer, end to end,
against the stateful fake. If the experience ever stops cohering, this fails."""
import base64
import datetime as _dt
import pytest
from fastapi.testclient import TestClient
import app.airtable_client as at
import app.dispatch as dp
import app.identity as identity_mod
import app.intake as intake_mod
import app.kitchen as kitchen_mod
import app.track as track_mod
from app.db import SessionLocal
from app.models import Partner
from app.main import app
from tests.fake_airtable import FakeAirtable

client = TestClient(app)
K = "/api/board/test-key"
fake = FakeAirtable()


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    for m in (at, dp.at, intake_mod.at, kitchen_mod.at, track_mod.at):
        monkeypatch.setattr(m, "list_records", fake.list_records)
        monkeypatch.setattr(m, "create_record", fake.create_record)
        monkeypatch.setattr(m, "patch_record", fake.patch_record)
    intake_mod._HITS.clear()
    yield


def test_grand_journey():
    # Founder prep: kitchen story + thank-you, a driver, a demo order to prove the button
    assert client.post(f"{K}/partners/stephens/about",
                       json={"blurb": "Family-owned since 1998."}).status_code == 200
    assert client.post(f"{K}/partners/stephens/thanks",
                       json={"note": "Grazie — the Stephen's family"}).status_code == 200
    day_token = client.post(f"{K}/drivers", json={"name": "Marcus Webb"}).json()["day_token"]
    assert client.post(f"{K}/partners/stephens/demo-order").status_code == 200

    # 1) Customer orders (menu flow, tip, totals)
    r = client.post("/v0/intake", json={
        "customer_name": "Jordan", "customer_phone": "865-555-0143",
        "dropoff_address": "88 Journey Blvd, Maryville TN",
        "items_description": '1× Pepperoni ($17.99) — subtotal $17.99',
        "partner": "stephens", "subtotal_cents": "1799", "fee_cents": "399",
        "tip_cents": "300", "total_cents": "2498"},
        headers={"x-forwarded-for": "20.20.20.1"})
    oid = r.json()["order_id"]

    # 2) ANTICIPATION: waiting page shows the kitchen's story, hides the address
    wait = client.get(f"/track/{oid}").text
    assert "Family-owned since 1998." in wait and "88 Journey Blvd" not in wait

    # 3) Board confirms + assigns; kitchen readies
    board = client.get(f"{K}/snapshot").json()
    rec = [o["id"] for o in board["orders"] if o["order_id"] == oid][0]
    drv = [d["id"] for d in board["drivers"] if d["name"] == "Marcus Webb"][0]
    client.post(f"{K}/orders/{rec}/confirm")
    client.post(f"{K}/orders/{rec}/assign", json={"driver_id": drv})
    ktok = SessionLocal().get(Partner, "stephens").portal_token
    client.post(f"/api/kitchen/{ktok}/orders/{rec}/ready", json={})

    # 4) NEIGHBOR NAME: assigned tracking calls the driver by first name
    assigned = client.get(f"/track/{oid}").text
    assert "Marcus" in assigned and "Webb" not in assigned

    # 5) Driver picks up, sends a HEADS-UP, customer sees it live
    client.post(f"/api/driver/{day_token}/orders/{rec}/picked_up",
                json={"lat": "35.75", "lng": "-83.99"})
    client.post(f"/api/driver/{day_token}/orders/{rec}/heads-up",
                json={"note": "5 minutes out!"})
    assert client.get(f"/v0/track/{oid}/heads-up").json()["note"] == "5 minutes out!"
    assert client.get(f"/v0/track/{oid}/location").json()["live"] is True

    # 6) Proof + delivered → THANK-YOU note + celebration surface
    img = base64.b64encode(b"\xff\xd8\xff pic").decode()
    client.post(f"/api/driver/{day_token}/orders/{rec}/proof",
                json={"image_b64": img, "order_id": oid})
    client.post(f"/api/driver/{day_token}/orders/{rec}/delivered",
                json={"lat": "35.76", "lng": "-83.98"})
    done = client.get(f"/track/{oid}").text
    assert "Grazie" in done and "celebrate" in done and "milestone" in done
    assert "5 minutes out!" not in done  # heads-up clears once delivered (not in_transit)

    # 7) Money: statement + local impact reflect the delivered order
    stmt = client.get(f"{K}/statement/stephens").text
    assert oid in stmt and "$17.99" in stmt
    impact = client.get("/v0/local-impact").json()
    assert impact["delivered"] >= 1 and impact["food_cents"] >= 1799

    # 8) Close it; day-open scorecard source reflects revenue
    client.post(f"{K}/orders/{rec}/close")
    summary = client.get(f"{K}/summary").json()
    assert summary["delivered"] >= 1 and summary["revenue_cents"] >= 2498


def test_grand_journey_v2_every_feature():
    """The full MVP, end to end: phone order → cash → special → heads-up → delivered →
    tip → round-up → private feedback → earnings → statement → readiness."""
    import json as _json
    # Kitchen posts today's special from their own screen
    ktok = SessionLocal().get(Partner, "burgerboys").portal_token
    assert client.post(f"/api/kitchen/{ktok}/special",
                       json={"text": "Collards just came off"}).status_code == 200
    assert "Collards" in client.get("/v0/partners/burgerboys").json()["special"]

    # A neighbor CALLS. Dispatch types it in (no app, no card).
    r = client.post(f"{K}/phone-order", json={
        "partner": "burgerboys", "items": "1× Kobe Burger", "subtotal_cents": 875,
        "address": "9 Ridge Rd, Maryville TN", "name": "Ruth", "phone": "865-555-0121",
        "tip_cents": 200, "notes": "Ring twice"})
    assert r.status_code == 200
    oid, rec = r.json()["order_id"], r.json()["record_id"]

    # Driver assigned; cash-due is visible to them
    tok = client.post(f"{K}/drivers", json={"name": "Ada Neighbor"}).json()["day_token"]
    snap = client.get(f"{K}/snapshot").json()
    drv = [d["id"] for d in snap["drivers"] if d["name"] == "Ada Neighbor"][0]
    client.post(f"{K}/orders/{rec}/confirm")
    client.post(f"{K}/orders/{rec}/assign", json={"driver_id": drv})
    sheet = client.get(f"/api/driver/{tok}/orders").json()
    mine = [o for o in sheet["orders"] if o["order_id"] == oid][0]
    assert mine["collect_cash_cents"] == mine["total_cents"] > 0     # cash at the door

    # Kitchen ready → driver picks up → sends a heads-up the customer sees
    client.post(f"/api/kitchen/{ktok}/orders/{rec}/ready", json={})
    client.post(f"/api/driver/{tok}/orders/{rec}/picked_up", json={"lat": "35.7", "lng": "-83.9"})
    client.post(f"/api/driver/{tok}/orders/{rec}/heads-up", json={"note": "Two minutes out"})
    assert client.get(f"/v0/track/{oid}/heads-up").json()["note"] == "Two minutes out"

    # Delivered → customer tips MORE, rounds up for a neighbor, and speaks privately
    client.post(f"/api/driver/{tok}/orders/{rec}/delivered", json={})
    assert client.post(f"/v0/track/{oid}/tip", json={"cents": 300}).json()["tip_cents"] == 500
    assert client.post(f"/v0/track/{oid}/round-up", json={"cents": 200}).status_code == 200
    assert client.post(f"/v0/track/{oid}/feedback",
                       json={"good": True, "note": "Ruth says thank you"}).status_code == 200

    # The kitchen reads her words; the fund grew; the driver sees their pay
    fb = client.get(f"/api/kitchen-feedback/{ktok}").json()
    assert any("Ruth says thank you" in n["note"] for n in fb["notes"])
    assert client.get("/v0/community-fund").json()["cents"] >= 200
    earn = client.get(f"/api/driver/{tok}/earnings").json()
    assert earn["totals"]["deliveries"] >= 1 and earn["totals"]["tips_cents"] >= 500

    # The money lands: statement + readiness both reflect reality
    stmt = client.get(f"{K}/statement/burgerboys").text
    assert oid in stmt
    ready = client.get(f"{K}/readiness").json()
    assert isinstance(ready["ready_to_take_orders"], bool)
    assert any(c["area"] == "Drivers" and c["ok"] for c in ready["checks"])
