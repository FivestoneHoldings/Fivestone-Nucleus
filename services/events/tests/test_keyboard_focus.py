"""v1.9.20 — keyboard focus must stay visible. input:focus{outline:none} has
higher specificity than :focus-visible, so it was silently stripping the focus
ring for keyboard/screen-reader users on every text input across the app —
while looking fine to a mouse user, who'd never notice. Verified with a real
keyboard Tab press in a headless browser: the focused element gets a 3px
outline."""
import os
UI = os.path.join(os.path.dirname(__file__), "..", "app", "ui")


def _f(n):
    return open(os.path.join(UI, n)).read()


def test_order_form_restores_focus_visible_on_every_suppressed_input():
    o = _f("order-form.html")
    # each outline:none on an input must have a matching :focus-visible rule
    assert "input:focus-visible,textarea:focus-visible,select:focus-visible{" in o
    assert ".msearch:focus-visible{" in o
    assert ".promo-row input:focus-visible{" in o


def test_me_page_restores_focus_visible():
    m = _f("me.html")
    assert ":focus-visible{outline:3px solid #2f6fe0" in m
    assert "input:focus-visible{outline:3px solid #2f6fe0 !important" in m


def test_scheduled_time_input_has_accessible_label():
    o = _f("order-form.html")
    assert 'id="reqFor" aria-label=' in o
