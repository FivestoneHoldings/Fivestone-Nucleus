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


def test_home_storefront_first_and_no_team_gate():
    html = client.get("/").text
    # restaurants section precedes the custom-order tile
    # v1.2: the "custom delivery" tile grew up into GateWay Courier, its own surface.
    assert html.index('id="restaurants"') < html.index("/courier")
    # v1.1: a food court does NOT ask its customers for a work badge at the door.
    # Team entry lives at /team; the home shows growth CTAs instead.
    assert "GateWay team" not in html
    assert "Driver day code" not in html and "Dispatch key" not in html
    assert "/drive-with-us" in html and "/partner-with-us" in html
    assert "Local kitchens, delivered by your neighbors" in html
    assert "rrow paused" in html and "notifyMe" in html  # paused kitchens keep the customer


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
