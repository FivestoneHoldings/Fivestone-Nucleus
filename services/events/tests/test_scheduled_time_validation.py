"""v1.9.22 — a scheduled order can't be set in the past.

Before: no client-side min= and no server-side check meant a customer could
schedule a delivery for yesterday. It would sit forever as neither "now" (it's
not ASAP) nor genuinely "today" to the kitchen once the clock passed it —
never cooked, never delivered, and the customer would never know why."""
import os
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
UI = os.path.join(os.path.dirname(__file__), "..", "app", "ui")


def test_picker_gets_a_live_min_when_scheduling_is_chosen():
    o = open(os.path.join(UI, "order-form.html")).read()
    assert "rf.min = localMin" in o
    assert "if(rf.value && rf.value < localMin) rf.value = ''" in o


def test_server_rejects_a_clearly_past_scheduled_time():
    past = "2020-01-01T12:00"
    r = client.post("/v0/intake", json={
        "dropoff_address": "1 Past St", "items_description": "item",
        "requested_for": past}, headers={"x-forwarded-for": "9.9.9.1"})
    assert r.status_code == 400
    assert r.json()["error"] == "requested_for_in_past"


def test_server_allows_a_genuine_near_future_schedule():
    future = (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")
    r = client.post("/v0/intake", json={
        "dropoff_address": "1 Future St", "items_description": "item",
        "requested_for": future}, headers={"x-forwarded-for": "9.9.9.2"})
    # not rejected for being in the past (503 here just means no Airtable in
    # this test's environment — the point is it's NOT a 400 requested_for_in_past)
    assert not (r.status_code == 400 and r.json().get("error") == "requested_for_in_past")


def test_server_tolerates_a_few_minutes_of_clock_skew():
    """Small clock skew between browser and server shouldn't hard-fail a real
    near-immediate order."""
    just_barely_past = (datetime.now() - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M")
    r = client.post("/v0/intake", json={
        "dropoff_address": "1 Skew St", "items_description": "item",
        "requested_for": just_barely_past}, headers={"x-forwarded-for": "9.9.9.3"})
    assert not (r.status_code == 400 and r.json().get("error") == "requested_for_in_past")


def test_unparseable_requested_for_does_not_500():
    r = client.post("/v0/intake", json={
        "dropoff_address": "1 Junk St", "items_description": "item",
        "requested_for": "not-a-real-date"}, headers={"x-forwarded-for": "9.9.9.4"})
    assert r.status_code != 500
