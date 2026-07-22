"""v1.9.32 — a customer can see a kitchen is closed BEFORE tapping into it.

Hours were being enforced at checkout, but nothing upstream showed it: the home
list looked identical for an open and a closed kitchen, and a customer could
browse a 273-item menu before finding out. Closed-by-hours is deliberately
presented differently from a manual pause — the kitchen is fine, just shut for
now, and a scheduled order is still welcome, so it stays a working link rather
than a dead row.
"""
import os

UI = os.path.join(os.path.dirname(__file__), "..", "app", "ui")
APP = os.path.join(os.path.dirname(__file__), "..", "app")


def _f(base, n):
    return open(os.path.join(base, n)).read()


def test_directory_exposes_open_closed_status():
    assert '"hours_status": hours.status(p)' in _f(APP, "identity.py")


def test_home_list_shows_closed_state():
    h = _f(UI, "home.html")
    assert "hs.open === false" in h
    assert "Tap to schedule for later" in h


def test_closed_kitchen_stays_tappable_for_scheduling():
    """A manual pause renders a dead <div>; closed-by-hours must stay an <a>
    so the customer can still schedule for when they reopen."""
    h = _f(UI, "home.html")
    closed_block = h.split("hs.open === false")[1][:400]
    assert '<a class="rrow"' in closed_block


def test_closed_kitchens_are_not_spotlighted():
    """Recommending somewhere you can't order from wastes the tap."""
    h = _f(UI, "home.html")
    assert "!(p.hours_status && p.hours_status.open === false)" in h


def test_storefront_shows_weekly_hours():
    o = _f(UI, "order-form.html")
    assert "meta.hours && meta.hours.length" in o
    assert 'class="rhours"' in o


def test_storefront_closed_banner_points_at_scheduling():
    o = _f(UI, "order-form.html")
    assert "You can still schedule an order for when they reopen" in o
    assert "Closed — schedule instead" in o
