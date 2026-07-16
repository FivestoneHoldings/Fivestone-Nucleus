"""v1.7 — GateWay Courier promoted to a first-class, independent service.

Founder: 'in the courier section, firstly, id like for it to be a much more
prominent and independent feature/function... the details button on courier
page total element does nothing.'
"""
import os

UI = os.path.join(os.path.dirname(__file__), "..", "app", "ui")


def _f(n):
    return open(os.path.join(UI, n)).read()


def test_courier_is_in_the_bottom_nav_on_consumer_surfaces():
    for page in ("home.html", "me.html", "activity.html", "courier.html"):
        s = _f(page)
        assert 'href="/courier"' in s and "<span>Courier</span>" in s, page


def test_courier_card_sits_above_the_fold_not_in_a_footnote_section():
    home = _f("home.html")
    # the courier card should appear before the "Your account" section, i.e.
    # promoted up near the food, not buried at the bottom
    assert 'class="courier"' in home
    assert home.index('class="courier"') < home.index("Your account")


def test_courier_quote_bar_can_scroll_so_details_are_visible():
    """The details breakdown lives inside a fixed floating bar; without a height
    cap it expanded off the top of the screen and looked dead. Capped + scroll."""
    c = _f("courier.html")
    assert "toggleQuoteDetails" in c
    assert "max-height:min(72vh" in c and "overflow-y:auto" in c


def test_courier_tip_base_is_five_dollars_with_custom():
    c = _f("courier.html")
    assert "const TIPS = [500, 700, 1000, 1500]" in c
    assert "tipCustom" in c


def test_courier_captures_recipient_phone_when_different():
    """A real gap: the driver only had the SENDER's phone, not the person
    actually at the destination (sending groceries to a parent, a gift to a
    friend, etc). Optional field, folded into special_instructions so the
    driver can see and call it."""
    c = _f("courier.html")
    assert 'id="recipPhone"' in c
    assert "special_instructions" in c
    assert "Recipient (call on arrival)" in c
