"""CSS sanity: no duplicate rules for layout-critical selectors.
Three stacked .mitem blocks from three passes is exactly how a menu breaks."""
import os
import re
import pytest

UI = os.path.join(os.path.dirname(__file__), "..", "app", "ui")

# selectors that MUST be defined exactly once — layout depends on them
CRITICAL = {
    "order-form.html": [".mitem{", ".mphoto{", ".mbody{", ".step{", ".mact{", ".mcat{",
                       # v1.2: THREE stacked .cartbar rules collided the money labels
                       # with their amounts ("Subtotal$9.00"). Watch it forever.
                       ".cartbar{", ".cbline{", ".cbtot{", ".promo{"],
    "home.html": [".rrow{", ".rthumb{", ".rinfo{", ".tile{", ".gw-nav{", ".courier{", ".chip{"],
    "kitchen.html": [".card{"],
}


@pytest.mark.parametrize("page,selectors", CRITICAL.items())
def test_no_duplicate_layout_rules(page, selectors):
    src = open(os.path.join(UI, page)).read()
    css = "\n".join(re.findall(r"<style>(.*?)</style>", src, re.S))
    dupes = []
    for sel in selectors:
        n = css.count(sel)
        if n > 1:
            dupes.append(f"{sel} defined {n}×")
    assert not dupes, f"{page} has conflicting CSS: {dupes}"


def test_viewport_guard_present_everywhere():
    for page in ("home.html", "order-form.html", "me.html",
                 "driver.html", "kitchen.html", "board.html"):
        src = open(os.path.join(UI, page)).read()
        assert "overflow-x:hidden" in src, f"{page} can overflow the phone"


def test_menu_photo_is_bounded():
    """A dish photo must never blow out the row width."""
    css = open(os.path.join(UI, "order-form.html")).read()
    m = re.search(r"\.mphoto\{([^}]*)\}", css)
    assert m, "no .mphoto rule"
    rule = m.group(1)
    # the photo lane must be FIXED (never grows/shrinks) and the text lane must shrink
    assert "min-width:" in rule and "flex:0 0" in rule, rule
    assert re.search(r"\.mbody\{flex:1 1 auto;min-width:0", css), "text lane must shrink"
    assert re.search(r"\.mact\{flex:0 0 auto", css), "stepper lane must not wrap"


def test_no_flex_body_shells():
    """A flex <body> turns every appended element into a COLUMN beside the content.
    That's what put a dark bar down the side of the order form and squeezed the menu."""
    for page in ("home.html", "order-form.html", "me.html",
                 "driver.html", "kitchen.html", "board.html"):
        src = open(os.path.join(UI, page)).read()
        css = "\n".join(re.findall(r"<style>(.*?)</style>", src, re.S))
        body_rules = re.findall(r"body\s*\{([^}]*)\}", css)
        for rule in body_rules:
            flat = rule.replace(" ", "").replace("\n", "")
            assert "display:flex" not in flat, (
                f"{page}: <body> is a flex container — appended elements become side columns")


def test_pages_are_width_contained():
    """Every surface must center its content with a max-width, not rely on a flex shell."""
    for page in ("home.html", "order-form.html", "me.html"):
        src = open(os.path.join(UI, page)).read()
        css = "\n".join(re.findall(r"<style>(.*?)</style>", src, re.S))
        assert re.search(r"body\s*\{[^}]*max-width", css, re.S), f"{page} body lacks max-width"
        assert re.search(r"body\s*\{[^}]*margin:\s*0 auto", css, re.S), f"{page} body not centered"
