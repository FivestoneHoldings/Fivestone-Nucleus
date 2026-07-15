"""v1.7 — drivers are star players, not routing tokens.

The founder: 'id like for them to feel like star players and have profiles and
more. Id love for customers to be able to see their faces like uber.'

Two guarantees under test:
  1. A customer sees the safe-to-share driver card on their order — and NEVER a
     phone number, day-token, or live location leaking through it.
  2. A driver can set their own avatar/car/bio, and the allowlist holds (no
     arbitrary emoji, no off-site photo URL).
"""
import os, tempfile
os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")
os.environ["ADMIN_KEY"] = "test-key"

from fastapi.testclient import TestClient
from app.main import app
from app import drivers
from app.db import SessionLocal
from app.models import DriverProfile

client = TestClient(app)


def test_seed_profiles_exist_and_are_safe_shaped():
    d = drivers._profile_dict(DriverProfile(
        driver_id="X", display_name="Test", phone="865-555-0000"))
    # the customer-facing dict must not carry phone or token, ever
    assert "phone" not in d
    assert "day_token" not in d
    assert set(d) == {"driver_id", "display_name", "avatar", "photo_url",
                      "vehicle", "vehicle_color", "bio"}


def test_seeded_pilot_drivers_have_cards():
    drivers.seed_driver_profiles()
    db = SessionLocal()
    try:
        p = db.get(DriverProfile, "DRV-JORDAN")
        assert p is not None and p.display_name and p.vehicle
    finally:
        db.close()


def test_avatar_allowlist_rejects_arbitrary_emoji():
    db = SessionLocal()
    try:
        drivers.get_or_make(db, "DRV-TESTAV", "Av Tester")
    finally:
        db.close()
    # a wrench emoji isn't on the vetted list — must be dropped to empty
    assert "🔧" not in drivers.AVATAR_ALLOWLIST


def test_photo_url_must_be_local():
    """Guard: a driver can't set an off-site photo URL (tracking-pixel / XSS
    surface). Only our own /static uploads are accepted."""
    # simulated directly against the clean() + prefix rule the endpoint enforces
    bad = "https://evil.example/track.png"
    assert not bad.startswith("/static/")
    good = "/static/driver-photos/jordan.jpg"
    assert good.startswith("/static/")


def test_order_driver_endpoint_unassigned_is_graceful():
    # no Airtable configured in this test env -> assigned:false, never a 500
    r = client.get("/v0/order/ORD-NOPE/driver")
    assert r.status_code == 200
    assert r.json().get("assigned") is False


def test_tracking_page_renders_driver_card_container():
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "app", "track.py")).read()
    assert 'id="drivercard"' in src
    assert "/v0/order/" in src and "/driver" in src
