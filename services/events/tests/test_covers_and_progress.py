"""v1.8 — storefront cover photos + tracking progress bar."""
import os
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
UI = os.path.join(os.path.dirname(__file__), "..", "app", "ui")
APP = os.path.join(os.path.dirname(__file__), "..", "app")


def _f(p, base=UI):
    return open(os.path.join(base, p)).read()


def test_cover_endpoint_exists_and_validates_scheme():
    src = _f("identity.py", APP)
    assert "/partners/{code}/cover" in src
    assert 'Cover must be an https:// URL' in src


def test_cover_flows_through_update_and_serializers():
    src = _f("identity.py", APP)
    assert '("cover_url", 500)' in src
    assert '"cover_url": p.cover_url' in src


def test_thumb_prefers_cover_in_wide_contexts():
    home = _f("home.html")
    assert "cls === 'fhero'" in home and "p.cover_url" in home


def test_order_header_uses_cover_before_hero():
    o = _f("order-form.html")
    assert "meta.cover_url || meta.hero_url" in o


def test_board_has_cover_editor():
    b = _f("board.html")
    assert "editCover" in b and "/cover" in b


def test_tracking_progress_bar_present():
    t = _f("track.py", APP)
    assert 'class="prog"' in t
    assert "_PROG" in t and '"in_transit": 3' in t


def test_kitchen_has_urgency_age_badge():
    """A busy kitchen line must never lose track of an old ticket."""
    k = _f("kitchen.html")
    assert "function ageBadge" in k
    assert "age-hot" in k and "age-warm" in k and "age-ok" in k
    assert "mins >= 20" in k  # escalation threshold exists


def test_driver_hub_shows_profile_completeness_badge():
    d = _f("driver.html")
    assert 'id="profBadge"' in d
    assert "function profComplete" in d
    assert "paintProfBadge" in d
