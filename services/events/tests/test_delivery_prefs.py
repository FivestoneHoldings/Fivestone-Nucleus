"""v1.5 — DELIVERY PREFERENCES + PROFILE AVATAR.

Founder: 'Special instructions for each customer profile that are attached to
their deliveries... Megan prefers no-contact delivery. Blue house with no
garage. Always knock on door.' The load-bearing test is
test_megans_exact_example_reaches_the_driver — it proves the founder's own
example works end to end, not just that the endpoints respond.
"""
import os

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import SessionLocal
from app.models import DeliveryPreference
import app.intake as intake_mod

client = TestClient(app)
ROOT = os.path.join(os.path.dirname(__file__), "..")

CREATED = []


async def fake_list(table, formula="", fields=None, max_records=100):
    return []


async def fake_create(table, fields):
    CREATED.append(fields)
    return {"id": "recPREF", "fields": fields}


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    monkeypatch.setattr(intake_mod.at, "list_records", fake_list)
    monkeypatch.setattr(intake_mod.at, "create_record", fake_create)
    intake_mod._HITS.clear()
    CREATED.clear()
    yield
    db = SessionLocal()
    try:
        db.query(DeliveryPreference).filter(
            DeliveryPreference.phone.in_(["8655550199", "8655550200"])).delete(
            synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _page(name):
    return open(os.path.join(ROOT, "app", "ui", name)).read()


# ---------------- the founder's own example, verbatim ----------------

def test_megans_exact_example_reaches_the_driver():
    """'Megan prefers no-contact delivery. Blue house with no garage. Always
    knock on door.' — saved once, must appear on every order she places after,
    without her retyping it."""
    r = client.post("/v0/delivery-prefs", json={
        "phone": "8655550199", "name": "Megan",
        "dropoff_style": "leave_at_door", "avoid_doorbell": True, "knock": True,
        "home_description": "Blue house with no garage",
    })
    assert r.status_code == 200

    order = client.post("/v0/intake", json={
        "dropoff_address": "1 Test St", "items_description": "1x Burger",
        "customer_phone": "8655550199", "partner": "burgerboys",
    })
    assert order.status_code in (200, 201)
    note = CREATED[-1]["special_instructions"]
    assert "Leave at the door" in note
    assert "Blue house with no garage" in note


def test_a_customer_with_no_saved_preferences_is_unaffected():
    """The feature must be invisible to someone who never opted in — no
    'Standing notes:' noise on a first-time order."""
    order = client.post("/v0/intake", json={
        "dropoff_address": "1 Test St", "items_description": "1x Burger",
        "customer_phone": "8655550200", "partner": "burgerboys",
    })
    assert order.status_code in (200, 201)
    assert "Standing notes" not in CREATED[-1]["special_instructions"]


def test_order_specific_notes_still_layer_on_top_of_standing_preferences():
    """A one-off note ('ring twice today, expecting a package too') must not
    get silently dropped just because standing preferences exist."""
    client.post("/v0/delivery-prefs", json={"phone": "8655550199",
                                            "home_description": "Blue house"})
    order = client.post("/v0/intake", json={
        "dropoff_address": "1 Test St", "items_description": "1x Burger",
        "customer_phone": "8655550199", "partner": "burgerboys",
        "special_instructions": "Ring twice today please",
    })
    note = CREATED[-1]["special_instructions"]
    assert "Blue house" in note
    assert "Ring twice today please" in note


def test_allergies_are_flagged_clearly_for_the_kitchen():
    client.post("/v0/delivery-prefs", json={"phone": "8655550199",
                                            "allergies": "Peanuts, shellfish"})
    order = client.post("/v0/intake", json={
        "dropoff_address": "1 Test St", "items_description": "1x Burger",
        "customer_phone": "8655550199", "partner": "burgerboys",
    })
    assert "ALLERGY: Peanuts, shellfish" in CREATED[-1]["special_instructions"]


# ---------------- API correctness ----------------

def test_get_prefs_for_a_phone_with_none_saved():
    d = client.get("/v0/delivery-prefs/8655550201").json()
    assert d["exists"] is False


def test_phone_numbers_are_normalized_so_formatting_doesnt_matter():
    """(865) 555-0199, 865-555-0199, and 8655550199 must all resolve to the
    same saved preferences — a customer shouldn't lose their notes because a
    device auto-formatted their phone number differently."""
    client.post("/v0/delivery-prefs", json={"phone": "(865) 555-0199",
                                            "home_description": "Test house"})
    d = client.get("/v0/delivery-prefs/865-555-0199").json()
    assert d["exists"] is True
    assert d["home_description"] == "Test house"


def test_an_invalid_dropoff_style_falls_back_safely():
    r = client.post("/v0/delivery-prefs", json={"phone": "8655550199",
                                                 "dropoff_style": "<script>evil"})
    assert r.status_code == 200
    d = client.get("/v0/delivery-prefs/8655550199").json()
    assert d["dropoff_style"] == "hand_to_me"


def test_an_avatar_outside_the_allowlist_is_rejected_outright():
    """Free-text 'avatar' is an XSS surface if it ever renders unescaped
    somewhere. A script-tag payload exceeds the 10-char field limit and is
    rejected at the door (422) — it never even reaches the allowlist check."""
    r = client.post("/v0/delivery-prefs", json={"phone": "8655550199",
                                                 "avatar": "<img src=x onerror=alert(1)>"})
    assert r.status_code == 422


def test_a_short_but_unvetted_string_still_falls_back_to_no_avatar():
    """Something that SNEAKS under the length limit but isn't a real emoji in
    the allowlist must still resolve to no avatar, not be stored verbatim."""
    r = client.post("/v0/delivery-prefs", json={"phone": "8655550199", "avatar": "hax<>"})
    assert r.status_code == 200
    d = client.get("/v0/delivery-prefs/8655550199").json()
    assert d["avatar"] == ""


def test_saving_prefs_without_a_phone_is_rejected():
    r = client.post("/v0/delivery-prefs", json={"phone": ""})
    assert r.status_code in (422,)


# ---------------- profile UI ----------------

def test_profile_page_has_an_avatar_picker():
    me = _page("me.html")
    assert "avatarPicker" in me and "pickAvatar" in me


def test_profile_page_has_the_full_delivery_preferences_form():
    me = _page("me.html")
    for field in ("dpHome", "dpAccess", "dpNotes", "dpAllergy", "dpDriver", "dropstyle"):
        assert field in me


def test_requesting_a_driver_by_name_carries_an_honest_disclaimer():
    """Founder: 'I'd like to see a request a driver feature with obvious
    disclaimers that they might not get them.'"""
    me = _page("me.html")
    idx = me.index("Request a driver by name")
    nearby = me[idx:idx + 500]
    assert "can't promise" in nearby or "preference, not a guarantee" in nearby


def test_prefs_load_automatically_once_a_phone_is_entered():
    me = _page("me.html")
    assert "loadPrefs" in me
    assert "addEventListener('blur', loadPrefs)" in me


# ---------------- request a driver: the full loop ----------------

def test_a_preferred_driver_creates_a_real_trackable_request():
    """A name saved to a profile is a wish, not a fact. It must become a real
    DriverRequest dispatch can see and act on — not just decorative text."""
    from app.models import DriverRequest
    client.post("/v0/delivery-prefs", json={"phone": "8655550199",
                                            "preferred_driver": "Jordan"})
    order = client.post("/v0/intake", json={
        "dropoff_address": "1 Test St", "items_description": "1x Burger",
        "customer_phone": "8655550199", "partner": "burgerboys",
    })
    assert order.status_code in (200, 201)
    db = SessionLocal()
    try:
        req = db.query(DriverRequest).filter(
            DriverRequest.customer_phone == "8655550199").order_by(
            DriverRequest.created_at.desc()).first()
        assert req is not None
        assert req.requested_driver == "Jordan"
        assert req.resolved is False
    finally:
        db.query(DriverRequest).filter(
            DriverRequest.customer_phone == "8655550199").delete(synchronize_session=False)
        db.commit()
        db.close()


def test_the_board_can_see_and_resolve_a_driver_request():
    import os as _os
    KEY = _os.environ.get("ADMIN_KEY", "test-key")
    from app.models import DriverRequest
    client.post("/v0/delivery-prefs", json={"phone": "8655550199",
                                            "preferred_driver": "Jordan"})
    client.post("/v0/intake", json={
        "dropoff_address": "1 Test St", "items_description": "1x Burger",
        "customer_phone": "8655550199", "partner": "burgerboys",
    })
    got = client.get(f"/api/board/{KEY}/driver-requests").json()
    assert got["requests"], "the board cannot see the driver request"
    req_id = got["requests"][0]["id"]
    r = client.patch(f"/api/board/{KEY}/driver-requests/{req_id}", json={"honored": True})
    assert r.status_code == 200
    still_open = client.get(f"/api/board/{KEY}/driver-requests").json()
    assert req_id not in [x["id"] for x in still_open["requests"]], \
        "resolved request still shows as open"
    db = SessionLocal()
    try:
        db.query(DriverRequest).filter(
            DriverRequest.customer_phone == "8655550199").delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_driver_requests_are_key_gated():
    assert client.get("/api/board/guess/driver-requests").status_code == 403


def test_board_surfaces_the_driver_requests_panel():
    b = _page("board.html")
    assert "showDriverRequests" in b and "resolveDriverReq" in b
    assert "driver-requests" in b
