"""v1.9.11 — an in-progress cart survives an accidental back-tap or refresh.
Losing a half-built cart is a silent conversion killer for a live business."""
import os
UI = os.path.join(os.path.dirname(__file__), "..", "app", "ui")


def _f(n):
    return open(os.path.join(UI, n)).read()


def test_cart_draft_saved_on_every_compose():
    o = _f("order-form.html")
    assert "gw_draft_" in o
    assert "localStorage.setItem('gw_draft_'" in o


def test_cart_draft_restored_when_returning():
    o = _f("order-form.html")
    assert "Picked up where you left off" in o
    # only restores a fresh draft, not a stale one
    assert "6*3600*1000" in o


def test_cart_draft_cleared_on_submit():
    o = _f("order-form.html")
    assert "localStorage.removeItem('gw_draft_' + p)" in o


def test_cart_draft_cleared_when_emptied():
    o = _f("order-form.html")
    # emptying the cart removes the draft (no ghost cart on next visit)
    assert "localStorage.removeItem('gw_draft_' + pcode)" in o
