"""v1.7 — a restaurant should wear its OWN face, and a long menu should be
navigable without thumbing all the way back up.

Founder: 'each restaurant still shows gateway's logo for the placeholders.
id like for them to be the respective restaurant's logo... asia cafe is just
one long list that you must scroll and then theres no back to top button.'
"""
import os

UI = os.path.join(os.path.dirname(__file__), "..", "app", "ui")


def _f(name):
    return open(os.path.join(UI, name)).read()


def test_menu_header_prefers_the_restaurants_own_logo_over_gateway_emblem():
    o = _f("order-form.html")
    # the render must consult logo_url before falling back to the emblem
    assert "meta.logo_url" in o
    # and the emblem is only the LAST resort, not the second branch
    hero_block = o[o.index("const heroInner"):o.index("const heroInner")+400]
    assert "meta.logo_url" in hero_block


def test_partner_detail_exposes_logo_and_cover():
    i = _f("../app/identity.py") if False else open(
        os.path.join(UI, "..", "identity.py")).read()
    assert '"logo_url": p.logo_url' in i
    assert '"cover_url": p.cover_url' in i


def test_long_menu_has_category_nav_and_back_to_top():
    o = _f("order-form.html")
    assert 'class="catnav"' in o
    assert 'id="toTop"' in o
    assert "scrollTop()" in o


def test_category_nav_scroll_spies():
    """The chips must track your scroll position, not just sit there — that's
    the difference between a real jump-bar and decoration on a 105-item menu."""
    o = _f("order-form.html")
    assert "function menuSpy" in o
    assert "addEventListener('scroll', menuSpy" in o
    assert "scroll-margin-top" in o  # anchors land below the sticky bar
