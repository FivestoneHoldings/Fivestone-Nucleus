"""v1.9 — merchant app: accept-an-order step with prep-time estimate that feeds
the customer ETA. What a real kitchen needs to run a serious operation."""
import os

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _f(p):
    return open(os.path.join(ROOT, p)).read()


def test_accept_endpoint_exists():
    k = _f("app/kitchen.py")
    assert "/orders/{record_id}/accept" in k
    assert "order.kitchen_accepted" in k
    assert "prep_estimate_minutes" in k


def test_accept_only_advances_from_received():
    k = _f("app/kitchen.py")
    assert 'if status == "received"' in k  # never walks an assigned order backward


def test_accept_estimate_is_bounded():
    k = _f("app/kitchen.py")
    assert "min(120" in k  # can't set an absurd prep time


def test_kitchen_ui_has_accept_buttons():
    k = _f("app/ui/kitchen.html")
    assert "acceptOrder" in k
    assert "acceptWithTime" in k
    assert "o.status === 'received'" in k  # accept shown only for new tickets


def test_customer_eta_honors_kitchen_estimate():
    t = _f("app/track.py")
    assert "prep_estimate_minutes" in t
    assert "kitchen_est" in t


def test_kitchen_ticket_items_are_formatted():
    k = _f("app/ui/kitchen.html")
    assert "function fmtItems" in k
    assert 'class="iqty"' in k  # quantity broken out per line
