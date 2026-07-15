"""v1.8 — one-tap reorder loop + per-partner storefront theming."""
import os
UI = os.path.join(os.path.dirname(__file__), "..", "app", "ui")
APP = os.path.join(os.path.dirname(__file__), "..", "app")


def _f(p, base=UI):
    return open(os.path.join(base, p)).read()


def test_activity_reorder_triggers_cart_restore():
    a = _f("activity.html")
    assert "reorder=1" in a  # not just a link to the menu — restores the cart


def test_order_form_restores_stashed_cart():
    o = _f("order-form.html")
    assert "gw_cart_" in o and "maybeReorder" in o
    # only re-adds items still live on the menu
    assert "live[line.id]" in o


def test_track_reorder_carries_flag_when_cart_exists():
    t = _f("track.py", APP)
    assert "gw_cart_" in t and "reorder=1" in t


def test_partner_theming_is_applied_and_contrast_guarded():
    o = _f("order-form.html")
    assert "function applyBrand" in o
    assert "--brand" in o
    assert "lum > 0.72" in o  # rejects too-light colors for white text
    # the cart bar + active chip actually consume the variable
    assert "var(--brand)" in o
