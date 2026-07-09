"""THE FULL LOOP — one order walked through every surface in sequence against a
stateful fake Airtable with real formula evaluation. Contract drift dies here."""
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
from app.models import Partner
from app.main import app
from tests.fake_airtable import FakeAirtable, evaluate

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


def test_formula_engine_selfcheck():
    rec = {"id": "recX", "fields": {"status": "assigned", "order_id": "ORD-1",
                                     "received_at": "2026-07-09T15:00:00.000Z"}}
    assert evaluate("{order_id}='ORD-1'", rec)
    assert evaluate("RECORD_ID()='recX'", rec)
    assert evaluate("OR({status}='assigned',{status}='in_transit')", rec)
    assert not evaluate("NOT(OR({status}='assigned',{status}='x'))", rec)
    assert evaluate("DATETIME_FORMAT({received_at},'YYYY-MM-DD')='2026-07-09'", rec)
    assert evaluate("DATETIME_FORMAT({received_at},'YYYY-MM-DD')>='2026-07-01'", rec)
    assert evaluate("AND({status}='assigned',{order_id}='ORD-1')", rec)


def test_the_full_loop():
    # 0) Founder creates a driver on the board
    r = client.post(f"{K}/drivers", json={"name": "Loop Driver"})
    day_token = r.json()["day_token"]

    # 1) Customer orders from Stephen's with totals + tip (menu-partner flow)
    r = client.post("/v0/intake", json={
        "customer_name": "Loop Customer", "customer_phone": "865-555-0177",
        "dropoff_address": "77 Integration Way, Knoxville TN",
        "items_description": '1× Pepperoni Pizza 16" ($17.99) — subtotal $17.99',
        "partner": "stephens", "subtotal_cents": "1799", "fee_cents": "399",
        "tip_cents": "300", "total_cents": "2498"},
        headers={"x-forwarded-for": "3.3.3.3"})
    assert r.status_code == 200 and r.json()["received"] is True
    oid = r.json()["order_id"]

    # duplicate submission is blocked
    r2 = client.post("/v0/intake", json={
        "dropoff_address": "77 Integration Way, Knoxville TN",
        "items_description": '1× Pepperoni Pizza 16" ($17.99) — subtotal $17.99',
        "partner": "stephens"}, headers={"x-forwarded-for": "3.3.3.3"})
    assert r2.json()["duplicate"] is True

    # 2) Board sees it; confirm + assign
    board = client.get(f"{K}/orders").json()
    rec_id = [o["id"] for o in board["orders"] if o["order_id"] == oid][0]
    drv_id = [d["id"] for d in board["drivers"] if d["name"] == "Loop Driver"][0]
    assert client.post(f"{K}/orders/{rec_id}/confirm").status_code == 200
    assert client.post(f"{K}/orders/{rec_id}/assign",
                       json={"driver_id": drv_id}).status_code == 200

    # 3) Kitchen sees it and marks READY
    db = SessionLocal()
    ktok = db.get(Partner, "stephens").portal_token
    db.close()
    kd = client.get(f"/api/kitchen/{ktok}/orders").json()
    assert any(o["order_id"] == oid for o in kd["orders"])
    assert client.post(f"/api/kitchen/{ktok}/orders/{rec_id}/ready",
                       json={}).status_code == 200

    # 4) Driver sheet shows it, kitchen-ready flagged; picked up with GPS
    sheet = client.get(f"/api/driver/{day_token}/orders").json()
    mine = [o for o in sheet["orders"] if o["order_id"] == oid][0]
    assert mine["kitchen_ready"] is True
    assert client.post(f"/api/driver/{day_token}/orders/{rec_id}/picked_up",
                       json={"lat": "35.955", "lng": "-83.929"}).status_code == 200

    # 5) Customer's live map is ON while in transit
    live = client.get(f"/v0/track/{oid}/location").json()
    assert live["live"] is True and live["lat"] == "35.955"

    # 6) Proof photo, then delivered
    img = base64.b64encode(b"\xff\xd8\xff loopproof").decode()
    assert client.post(f"/api/driver/{day_token}/orders/{rec_id}/proof",
                       json={"image_b64": img, "order_id": oid}).status_code == 200
    assert client.post(f"/api/driver/{day_token}/orders/{rec_id}/delivered",
                       json={"lat": "35.956", "lng": "-83.930"}).status_code == 200

    # 7) Map goes dark after delivery; tracking page shows delivered + total
    assert client.get(f"/v0/track/{oid}/location").json()["live"] is False
    page = client.get(f"/track/{oid}").text
    assert "Delivered" in page and "$24.98" in page
    assert "77 Integration Way" not in page  # privacy holds

    # 8) Proof is servable; board detail has the full story
    assert client.get(f"/proof/{oid}").content.startswith(b"\xff\xd8\xff")
    detail = client.get(f"{K}/order-detail/{oid}").json()
    types = [e["event_type"] for e in detail["events"]]
    for expected in ("order.received", "order.kitchen_ready",
                     "order.picked_up", "order.proof_captured", "order.delivered"):
        assert expected in types, f"missing {expected} in trail"
    assert detail["has_proof"] is True
    assert detail["fields"]["total_cents"] == 2498

    # 9) Close it; reporting reflects one delivered order with revenue
    assert client.post(f"{K}/orders/{rec_id}/close").status_code == 200
    summary = client.get(f"{K}/summary").json()
    assert summary["delivered"] >= 1 and summary["revenue_cents"] >= 2498
    digest = client.get(f"{K}/digest", params={"partner": "stephens"}).json()
    assert digest["totals"]["revenue_cents"] >= 2498
    csv_out = client.get(f"{K}/export.csv").text
    assert oid in csv_out

    # 10) Driver's day: 1 delivered today
    assert client.get(f"/api/driver/{day_token}/orders").json()["done_today"] == 1
