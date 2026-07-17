"""v1.9.6 — driver universal maps, richer menu search, itemized receipt."""
import os
ROOT = os.path.join(os.path.dirname(__file__), "..")


def _f(p):
    return open(os.path.join(ROOT, p)).read()


def test_driver_nav_is_cross_platform():
    d = _f("app/ui/driver.html")
    # must not be Apple-only — Android drivers need Google Maps
    assert "google.com/maps/dir" in d
    assert "maps.apple.com" in d  # still used on Apple devices
    assert "iPhone|iPad|iPod|Macintosh" in d


def test_menu_search_hides_nav_and_shows_result_count():
    o = _f("app/ui/order-form.html")
    assert "msearchMsg" in o
    assert "dishes match" in o or "dish" in o
    # jump-bar hidden while searching a filtered menu
    assert "nav.style.display = q ? 'none'" in o


def test_tracking_receipt_itemizes_and_breaks_down_money():
    t = _f("app/track.py")
    assert 'class="receipt"' in t
    assert "Subtotal" in t and "Delivery fee" in t and "Driver tip" in t
    assert "rctot" in t  # a real total row
    assert "Discount" in t  # promo discounts shown when present


def test_driver_delivery_items_are_formatted():
    d = _f("app/ui/driver.html")
    assert "function fmtItems" in d
    assert "fmtItems(o.items)" in d
