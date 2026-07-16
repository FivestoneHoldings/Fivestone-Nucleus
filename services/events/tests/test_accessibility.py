"""v1.8 — accessibility pass: every interactive control must be a real,
keyboard-focusable element with a discoverable label, not a bare <span onclick>.
"""
import os

UI = os.path.join(os.path.dirname(__file__), "..", "app", "ui")


def _f(n):
    return open(os.path.join(UI, n)).read()


def test_order_form_quantity_steppers_have_aria_labels():
    o = _f("order-form.html")
    assert 'aria-label="Remove one' in o
    assert 'aria-label="Add one' in o


def test_order_form_special_request_is_a_real_button():
    o = _f("order-form.html")
    assert '<button type="button" class="mnote empty"' in o
    assert '<span class="mnote empty"' not in o


def test_order_form_has_no_stale_duplicate_mnote_rule():
    """A dead first .mnote CSS rule was silently overridden by a second — the
    exact 'shipped 3 stacked rules' failure class the codebase guards against
    elsewhere. Consolidated to one."""
    o = _f("order-form.html")
    assert o.count(".mnote{") == 1


def test_home_search_clear_is_a_real_button():
    h = _f("home.html")
    assert '<button type="button" class="gsx"' in h
    assert 'aria-label="Clear search"' in h


def test_me_page_address_remove_is_a_real_button():
    m = _f("me.html")
    assert '<button type="button" class="x"' in m
    assert 'aria-label="Remove address"' in m


def test_avatar_pickers_are_focusable_buttons_not_spans():
    driver = _f("driver.html")
    me = _f("me.html")
    assert 'aria-label="Choose face' in driver
    assert 'aria-label="Choose avatar' in me
    # the old non-focusable pattern must be gone from the picker paint functions
    assert "onclick=\"pickAvatar" in driver and "<span" not in driver.split("pickAvatar('${a}')")[0][-80:]
