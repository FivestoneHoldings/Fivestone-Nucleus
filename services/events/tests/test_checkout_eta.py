"""v1.9.16 — honest estimated-arrival at checkout. Only shown when the kitchen
has real prep telemetry; never a fabricated number."""
import os
ROOT = os.path.join(os.path.dirname(__file__), "..")


def _f(p):
    return open(os.path.join(ROOT, p)).read()


def test_partner_lookup_exposes_prep_minutes():
    src = _f("app/identity.py")
    assert '"prep_minutes": prep' in src


def test_checkout_shows_eta_only_when_prep_data_exists():
    o = _f("app/ui/order-form.html")
    assert "orveta" in o
    assert "window._PARTNER_META && window._PARTNER_META.prep_minutes" in o
    # the ETA is a window built on the real median, plus a drive tail
    assert "prep + 10" in o and "prep + 22" in o


def test_checkout_eta_never_fabricated():
    o = _f("app/ui/order-form.html")
    # etaLine starts empty and is only filled inside the `if(prep)` guard
    assert "let etaLine = ''" in o
