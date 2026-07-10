"""Hostile-stranger suite: cross-tenant access, injection, stored-XSS vectors."""
import base64
import pytest
from fastapi.testclient import TestClient
import app.airtable_client as at
import app.dispatch as dp
import app.kitchen as kitchen_mod
import app.track as track_mod
import app.intake as intake_mod
from app.db import SessionLocal
from app.models import Partner
from app.main import app
from tests.fake_airtable import FakeAirtable

client = TestClient(app)
K = "/api/board/test-key"
fake = FakeAirtable()

DRV_A = fake.seed(at.DRIVERS, {"driver_id": "DRV-A", "day_token": "tok-A",
                                "display_name": "Alice", "status": "active"})
DRV_B = fake.seed(at.DRIVERS, {"driver_id": "DRV-B", "day_token": "tok-B",
                                "display_name": "Bob", "status": "active"})
ORD_A = fake.seed(at.ORDERS, {"order_id": "ORD-SECA01", "status": "assigned",
                               "driver": [DRV_A], "partner_code": "stephens",
                               "items_description": "TOPSECRET ITEMS",
                               "received_at": "2026-07-09T15:00:00.000Z"})


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    for m in (at, dp.at, kitchen_mod.at, track_mod.at, intake_mod.at):
        monkeypatch.setattr(m, "list_records", fake.list_records)
        monkeypatch.setattr(m, "create_record", fake.create_record)
        monkeypatch.setattr(m, "patch_record", fake.patch_record)
    intake_mod._HITS.clear()
    yield


def test_driver_cannot_touch_anothers_order():
    r = client.post(f"/api/driver/tok-B/orders/{ORD_A}/picked_up", json={})
    assert r.status_code == 403
    r2 = client.post(f"/api/driver/tok-B/orders/{ORD_A}/proof",
                     json={"image_b64": base64.b64encode(b"x").decode(),
                           "order_id": "ORD-SECA01"})
    assert r2.status_code == 403
    # the rightful driver still can
    assert client.post(f"/api/driver/tok-A/orders/{ORD_A}/picked_up",
                       json={}).status_code == 200


def test_action_on_unknown_order_404():
    assert client.post("/api/driver/tok-A/orders/recNOPE/picked_up",
                       json={}).status_code == 404


def test_kitchen_cannot_ready_another_kitchens_order():
    db = SessionLocal()
    stephens_tok = db.get(Partner, "stephens").portal_token
    bb_tok = db.get(Partner, "burgerboys").portal_token
    db.close()
    r = client.post(f"/api/kitchen/{bb_tok}/orders/{ORD_A}/ready", json={})
    assert r.status_code == 403
    assert client.post(f"/api/kitchen/{stephens_tok}/orders/{ORD_A}/ready",
                       json={}).status_code == 200


def test_formula_injection_neutralized():
    # A quote-smuggling order id must NOT match-all and leak another order
    evil = "ORD-X'!=''"
    r = client.get(f"/track/{evil}")
    assert r.status_code == 404
    assert "TOPSECRET" not in r.text
    r2 = client.get(f"/v0/track/{evil}/location")
    assert r2.json()["live"] is False
    r3 = client.get(f"{K}/order-detail/{evil}")
    assert r3.status_code == 404


def test_proof_content_type_whitelisted():
    payload = base64.b64encode(b"<script>alert(1)</script>").decode()
    r = client.post(f"/api/driver/tok-A/orders/{ORD_A}/proof",
                    json={"image_b64": payload, "order_id": "ORD-SECA01",
                          "content_type": "text/html"})
    assert r.status_code == 200
    g = client.get("/proof/ORD-SECA01")
    assert g.headers["content-type"].startswith("image/")  # never text/html


def test_proof_rejects_invalid_base64():
    r = client.post(f"/api/driver/tok-A/orders/{ORD_A}/proof",
                    json={"image_b64": "!!!not-base64!!!", "order_id": "ORD-SECA01"})
    assert r.status_code == 400


def test_partner_code_charset_enforced():
    r = client.post(f"{K}/partners",
                    json={"code": "evil'code", "display_name": "Evil"})
    assert r.status_code == 200
    assert r.json()["code"] == "evilcode"  # quote stripped
