"""Owned intake + proof-of-delivery tests."""
import os, tempfile, base64
os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")
os.environ["ADMIN_KEY"] = "test-key"
os.environ["AIRTABLE_PAT"] = "fake-pat"

from fastapi.testclient import TestClient
import app.airtable_client as at
import app.intake as intake_mod
import app.dispatch as dp
from app.main import app

client = TestClient(app)

CREATED = []
EXISTING: list = []
FAKE_DRIVER = {"id": "recDRV1", "fields": {"display_name": "Test Driver", "day_token": "tok123"}}


async def fake_list(table, formula="", fields=None, max_records=100):
    if table == at.DRIVERS:
        return [FAKE_DRIVER] if "tok123" in formula else []
    if "fingerprint" in formula:
        return EXISTING
    return []


async def fake_create(table, fields):
    CREATED.append((table, fields))
    return {"id": "recNEW", "fields": fields}

import pytest


@pytest.fixture(autouse=True)
def _patched_airtable(monkeypatch):
    for mod in (intake_mod.at, dp.at):
        monkeypatch.setattr(mod, "list_records", fake_list)
        monkeypatch.setattr(mod, "create_record", fake_create)
    yield


def test_intake_creates_order_with_partner():
    r = client.get("/v0/intake", params={
        "customer_name": "Asia Cafe", "customer_phone": "865-555-0001",
        "pickup_address": "Asia Cafe Knoxville", "dropoff_address": "999 Demo Ln Knoxville TN",
        "items_description": "2 lunch specials", "partner": "asiacafe"})
    assert r.status_code == 200
    assert "Order received" in r.text
    table, fields = CREATED[-1]
    assert fields["partner_code"] == "asiacafe"
    assert fields["order_id"].startswith("ORD-")


def test_intake_json_response():
    r = client.post("/v0/intake", json={
        "dropoff_address": "123 J St", "items_description": "box"})
    assert r.status_code == 200
    assert r.json()["received"] is True


def test_intake_dedup_blocks_second():
    global EXISTING
    EXISTING = [{"id": "recX", "fields": {}}]
    n = len(CREATED)
    r = client.post("/v0/intake", json={
        "dropoff_address": "123 J St", "items_description": "box"})
    assert r.json()["duplicate"] is True
    assert len(CREATED) == n  # nothing new created
    EXISTING = []


def test_intake_rejects_empty():
    assert client.post("/v0/intake", json={}).status_code == 400


def test_proof_roundtrip():
    img = base64.b64encode(b"\xff\xd8\xff fakejpegbytes").decode()
    r = client.post("/api/driver/tok123/orders/recORD1/proof",
                    json={"image_b64": img, "order_id": "ORD-PROOF001", "lat": "35.9", "lng": "-83.9"})
    assert r.status_code == 200
    assert r.json()["proof_url"] == "/proof/ORD-PROOF001"
    g = client.get("/proof/ORD-PROOF001")
    assert g.status_code == 200
    assert g.content.startswith(b"\xff\xd8\xff")


def test_proof_404_when_missing():
    assert client.get("/proof/ORD-NOPE").status_code == 404
