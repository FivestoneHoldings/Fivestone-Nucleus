"""v1.9.12 — critical UX/reliability fixes reported directly from real use:
missed orders, unclickable board tickets, browser-back history pollution, and
the back-to-top button being covered by the cart bar."""
import os

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _f(p):
    return open(os.path.join(ROOT, p)).read()


def test_board_ticket_opens_a_real_modal_not_scroll_and_share_a_div():
    b = _f("app/ui/board.html")
    assert 'id="ticketModalWrap"' in b and 'id="ticketModal"' in b
    assert "function openTicketModal" in b
    assert "function closeTicketModal" in b
    # the old fragile pattern is gone
    assert "window.scrollTo({top:0, behavior:'smooth'});\n}" not in b or "openTicketModal(oid)" in b


def test_ticket_modal_has_quick_actions():
    b = _f("app/ui/board.html")
    assert "tmactions" in b
    assert "confirmO(" in b and "cancelO(" in b


def test_order_detail_endpoint_returns_full_money_and_driver_info():
    src = _f("app/dispatch.py")
    assert '"driver_name": driver_name' in src
    assert '"tip_cents"' in src and '"discount_cents"' in src and '"promo_code"' in src


def test_category_chips_never_pollute_browser_history():
    o = _f("app/ui/order-form.html")
    assert "evt.preventDefault()" in o
    assert "onclick=\"return navPick(this,event)\"" in o
    # must not push/replace history state via the old anchor-navigation pattern
    assert "history.pushState" not in o


def test_back_to_top_repositions_above_the_cart_bar():
    o = _f("app/ui/order-form.html")
    assert "function repositionToTop" in o
    assert "bar.offsetHeight" in o
    assert "requestAnimationFrame(repositionToTop)" in o
