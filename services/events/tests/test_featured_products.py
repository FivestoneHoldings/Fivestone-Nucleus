"""v1.9.27 — a kitchen can spotlight products at the top of its menu.

Phillip (Asia Cafe) sells a coffee brand alongside the restaurant menu and
wanted it featured. Starred items surface as a virtual category pinned above
everything else, with a per-kitchen title ("☕ Phillip's Coffee"), while still
living in their real category below so normal browsing isn't disrupted."""
import os
UI = os.path.join(os.path.dirname(__file__), "..", "app", "ui")
APP = os.path.join(os.path.dirname(__file__), "..", "app")


def _f(base, n):
    return open(os.path.join(base, n)).read()


def test_board_can_toggle_featured():
    b = _f(UI, "board.html")
    assert "menuFeature" in b
    assert "featured:on" in b.replace(" ", "")


def test_storefront_pins_featured_items_to_the_top():
    o = _f(UI, "order-form.html")
    assert "cats.unshift(" in o
    assert "i.featured && i.available" in o


def test_featured_section_hidden_when_nothing_is_starred():
    o = _f(UI, "order-form.html")
    # the unshift is guarded — an empty spotlight would just be noise
    assert "if(featured.length){" in o


def test_kitchen_can_title_its_own_spotlight():
    o = _f(UI, "order-form.html")
    assert "meta.featured_label" in o
    m = _f(APP, "models.py")
    assert "featured_label" in m


def test_duplicated_items_keep_quantities_in_sync():
    """A featured item appears twice on the page. getElementById returns only
    the first, so the second copy would silently freeze at 0."""
    o = _f(UI, "order-form.html")
    assert "document.getElementById('q-'+id)" not in o
    assert "querySelectorAll('.qty-'+CSS.escape(id))" in o
    assert 'class="qty-${i2.id}"' in o


def test_only_available_items_are_featured():
    """An 86'd item must not sit starred at the top of the menu."""
    o = _f(UI, "order-form.html")
    assert "i.featured && i.available" in o
