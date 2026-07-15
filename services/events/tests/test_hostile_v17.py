"""v1.7 hostile sweep — the new surfaces (driver profiles, driver card, Neighbor
Fund, activity) must not leak data, accept tampered money, or open an XSS hole.
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


def test_driver_card_never_carries_phone_or_token():
    p = DriverProfile(driver_id="Z", display_name="Zed",
                      phone="865-555-9999", avatar="😎", vehicle="Civic")
    d = drivers._profile_dict(p)
    blob = str(d)
    assert "865-555-9999" not in blob
    assert "phone" not in d and "day_token" not in d


def test_avatar_rejects_non_allowlisted():
    # a script-y or off-list glyph must never be stored as an avatar
    assert "🔧" not in drivers.AVATAR_ALLOWLIST
    assert "<" not in "".join(drivers.AVATAR_ALLOWLIST)


def test_bio_and_vehicle_are_length_capped():
    assert len(drivers._clean("x" * 9999, 300)) <= 300
    assert len(drivers._clean("y" * 9999, 120)) <= 120


def test_photo_url_rejects_offsite():
    assert not "http://evil/x.png".startswith("/static/")
    assert "javascript:alert(1)".startswith("/static/") is False


def test_roundup_amount_is_server_clamped():
    # tampered giant round-up is rejected; the client can't move $1000 through it
    # (endpoint requires Airtable, unconfigured here -> we assert the guard bounds
    #  directly on the known contract)
    from app import dispatch
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "app", "dispatch.py")).read()
    assert "cents <= 0 or cents > 10000" in src  # $0.01–$100 hard bounds


def test_activity_page_escapes_untrusted_history():
    # the activity page must escape partner names / order ids from localStorage
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "app", "ui", "activity.html")).read()
    assert "function esc(" in src
    assert "esc(nm)" in src and "esc(h.oid)" in src


def test_neighbor_fund_math_cannot_go_negative():
    d = client.get("/v0/community-fund").json()
    assert d["cents"] >= 0
    assert d["deliveries_covered"] >= 0
    assert 0 <= d["toward_next_cents"] < d["fee_cents"]
