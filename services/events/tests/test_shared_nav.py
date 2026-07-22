"""v1.9.29 — one shared bottom nav across every consumer page.

Four pages had NO navigation at all: the storefront (a customer browsing a
273-item menu had no way out but the back button), tracking, Neighbor Fund and
the roadmap. Meanwhile the nav markup and CSS was copy-pasted across seven
other pages — and three of those copies highlighted the WRONG tab.
"""
import os

ROOT = os.path.join(os.path.dirname(__file__), "..")
UI = os.path.join(ROOT, "app", "ui")
NAV = os.path.join(UI, "static", "gw-nav.js")


def _f(p):
    return open(p).read()


CONSUMER_PAGES = ["home.html", "activity.html", "courier.html", "me.html",
                  "support.html", "lead-driver.html", "lead-merchant.html",
                  "order-form.html", "neighbor-fund.html", "roadmap.html"]


def test_every_consumer_page_includes_the_nav():
    for name in CONSUMER_PAGES:
        assert "gw-nav.js" in _f(os.path.join(UI, name)), name


def test_tracking_page_includes_the_nav():
    """Including its 404 path — a bad order link is exactly when someone needs
    a way back."""
    t = _f(os.path.join(ROOT, "app", "track.py"))
    assert t.count("gw-nav.js") >= 2


def test_no_page_still_carries_a_duplicated_nav_block():
    for name in CONSUMER_PAGES:
        assert '<nav class="gw-nav">' not in _f(os.path.join(UI, name)), name


def test_active_tab_is_derived_from_the_url_not_hardcoded():
    """Three pages used to hardcode Home as active while not being Home."""
    nav = _f(NAV)
    assert "function activeKey" in nav
    assert "location.pathname" in nav


def test_operator_tools_do_not_get_the_consumer_nav():
    """The board, kitchen screen and driver hub are separate tools — a
    'Courier' tab in the middle of a dispatcher's shift would be noise."""
    for name in ("board.html", "kitchen.html", "driver.html"):
        assert "gw-nav.js" not in _f(os.path.join(UI, name)), name


def test_nav_never_double_renders():
    nav = _f(NAV)
    assert "__gwNavLoaded" in nav
    assert "document.querySelector('.gw-nav')" in nav


def test_nav_leaves_room_so_it_never_covers_content():
    assert "body.gw-has-nav{padding-bottom:96px}" in _f(NAV)


def test_order_form_hides_nav_when_the_cart_bar_is_up():
    """Both live at the bottom of the screen; stacking them would bury one."""
    o = _f(os.path.join(UI, "order-form.html"))
    assert "nav.style.display = barUp ? 'none' : ''" in o
