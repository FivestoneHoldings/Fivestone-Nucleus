"""v1.9.9 — photo-less menu items get a branded monogram tile, not 273 identical
GateWay emblems. Premium apps never repeat a generic logo down a whole menu."""
import os
UI = os.path.join(os.path.dirname(__file__), "..", "app", "ui")


def _f(n):
    return open(os.path.join(UI, n)).read()


def test_menu_uses_monogram_not_emblem_for_photoless_items():
    o = _f("order-form.html")
    assert 'class="ph mono"' in o
    # the old repeated-emblem placeholder is gone from the item render
    assert '<div class="ph"><img src="/static/gwd-emblem.png"' not in o


def test_monogram_uses_brand_color_and_item_initial():
    o = _f("order-form.html")
    assert "var(--brand,#16337a)" in o  # tile picks up the kitchen's brand color
    assert "toUpperCase()" in o          # shows the item's initial


def test_monogram_initial_is_html_safe():
    o = _f("order-form.html")
    # the initial is escaped before it goes into markup
    assert "initial.replace(/</g,'&lt;')" in o


def test_home_thumbs_fall_back_to_monogram_not_emblem():
    h = open(os.path.join(UI, "home.html")).read()
    assert "monotile" in h and "monoletter" in h
    # the repeated-emblem final fallback is gone from thumb()
    assert '<img class="emb" src="/static/gwd-emblem.png" alt=""></div>' not in h


def test_home_image_error_fallback_is_monogram():
    h = open(os.path.join(UI, "home.html")).read()
    # even when a logo fails to load, we show the letter, not the emblem
    assert "className:'monoletter'" in h
