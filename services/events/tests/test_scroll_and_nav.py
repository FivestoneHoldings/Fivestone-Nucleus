"""v1.5 continued — SCROLL RESTORATION AND THE 'MESSED UP' ACTIVITY BUTTON.

Both are founder-reported bugs with a real, findable root cause rather than
vague polish.
"""
import os

ROOT = os.path.join(os.path.dirname(__file__), "..")
UI = os.path.join(ROOT, "app", "ui")


def _page(name):
    return open(os.path.join(UI, name)).read()


def _gwui():
    return open(os.path.join(UI, "static", "gw-ui.js")).read()


# ---------------- scroll restoration ----------------

def test_scroll_restoration_is_taken_over_manually():
    """Founder: 'when I go back to a page, it goes straight to the top... I'd
    love to be exactly where I was.' Root cause: content loads async, so the
    browser's native restore fires against a page that's still too short and
    silently snaps to top. We take manual control instead of trusting it."""
    js = _gwui()
    assert "history.scrollRestoration = 'manual'" in js


def test_scroll_position_is_saved_per_path():
    js = _gwui()
    assert "gw_scroll:" in js
    assert "sessionStorage.setItem(KEY" in js


def test_restore_waits_for_async_content_to_settle_before_scrolling():
    """The core fix: don't restore against a page that hasn't finished
    rendering its fetched content yet."""
    js = _gwui()
    assert "stableFrames" in js
    assert "requestAnimationFrame(tryRestore)" in js


def test_restore_has_a_hard_ceiling_so_it_can_never_hang():
    js = _gwui()
    assert "MAX_FRAMES" in js
    assert "frames >= MAX_FRAMES" in js


def test_scroll_restore_respects_reduced_motion_posture():
    """Uses 'instant' scroll, never an animated scroll that would fight a
    customer's reduced-motion preference."""
    js = _gwui()
    assert "behavior: 'instant'" in js


# ---------------- nav active state ----------------

def test_nav_active_tab_is_computed_not_hardcoded():
    """Founder: 'the activity button is messed up.' Root cause: home.html
    always showed Home as active, and that markup was copy-pasted onto every
    other page (support, courier, lead pages) WITHOUT updating which tab
    should really be lit — so Home showed active even on the Support page."""
    js = _gwui()
    assert "gw-nav .gw-navin > a" in js
    assert "classList.remove('on')" in js
    assert "classList.add('on')" in js


def test_nav_maps_every_real_path_to_the_right_tab():
    js = _gwui()
    for path_check in ("path === '/'", "path.startsWith('/order')",
                       "path.startsWith('/track/')", "path.startsWith('/me')"):
        assert path_check in js


def test_courier_page_has_the_same_nav_as_every_other_consumer_surface():
    """Courier was missing the bottom nav entirely — a dead end with no way to
    get to Home/Order/Activity/Account short of the back button."""
    c = _page("courier.html")
    assert "gw-nav.js" in c
    assert "gwActivity" in c


def test_every_consumer_surface_loads_the_shared_ui_script():
    """The nav-fix and scroll-fix both live in gw-ui.js — a page that doesn't
    load it silently keeps the old broken behavior."""
    for name in ("home.html", "me.html", "courier.html", "order-form.html",
                "support.html", "team.html"):
        assert "gw-ui.js" in _page(name), f"{name} is missing the shared UI script"
