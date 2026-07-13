"""CSS sanity: no duplicate rules for layout-critical selectors.
Three stacked .mitem blocks from three passes is exactly how a menu breaks."""
import os
import re
import pytest

UI = os.path.join(os.path.dirname(__file__), "..", "app", "ui")

# selectors that MUST be defined exactly once — layout depends on them
CRITICAL = {
    "order-form.html": [".mitem{", ".mphoto{", ".mbody{", ".step{", ".mact{", ".mcat{"],
    "home.html": [".rrow{", ".rthumb{", ".rinfo{", ".tile{"],
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
    assert m and "min-width:92px" in m.group(1) and "width:92px" in m.group(1)
    assert ".mbody{flex:1;min-width:0" in css   # body must be allowed to shrink
