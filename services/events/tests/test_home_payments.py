"""New-customer home flow + payments seam contracts."""
import pytest
from fastapi.testclient import TestClient
import app.airtable_client as at
import app.intake as intake_mod
from app.main import app

client = TestClient(app)
CREATED = []


async def fake_list(table, formula="", fields=None, max_records=100):
    return []


async def fake_create(table, fields):
    CREATED.append(fields)
    return {"id": "recP", "fields": fields}


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    monkeypatch.setattr(intake_mod.at, "list_records", fake_list)
    monkeypatch.setattr(intake_mod.at, "create_record", fake_create)
    intake_mod._HITS.clear()
    yield


def test_home_storefront_first_and_gate_collapsed():
    html = client.get("/").text
    # restaurants section precedes the custom-order tile; team gate is a disclosure
    assert html.index('id="restaurants"') < html.index("custom delivery")
    assert "<details" in html and "GateWay team" in html
    assert "Local kitchens, delivered by your neighbors" in html
    assert "Paused right now" in html  # renderer handles paused partners


def test_form_has_payment_section():
    html = client.get("/order").text
    assert 'name="payment_method"' in html and "Pay at the door" in html
    assert "COMING SOON" in html
    assert html.index('id="payFs"') < html.index('id="pickupFs"')


def test_intake_records_method_but_never_writes_it_to_airtable():
    r = client.post("/v0/intake", json={"dropoff_address": "9 Pine",
                                        "items_description": "box",
                                        "payment_method": "card"},  # invalid until Stripe -> cod
                    headers={"x-forwarded-for": "8.8.8.8"})
    assert r.status_code == 200
    assert "payment_method" not in CREATED[-1]          # Airtable schema untouched
    ev = client.get("/api/board/test-key/events").json()["events"]
    pm = [e for e in ev if e["event_type"] == "order.payment_method"][0]
    assert '"cod"' in pm["payload"]                      # normalized + owned-logged


def test_diag_reports_stripe_unconfigured():
    d = client.get("/api/diag").json()
    assert d["stripe_configured"] is False
