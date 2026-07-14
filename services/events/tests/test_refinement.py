"""v1.2 REFINEMENT — the founder walked the app on his phone and found these.

Each test here exists because something was actually wrong on a real screen, not
because it seemed like a good idea.
"""
import os
import re

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
ROOT = os.path.join(os.path.dirname(__file__), "..")
UI = os.path.join(ROOT, "app", "ui")


def _page(name):
    return open(os.path.join(UI, name)).read()


# ---------------- geography: we are a KNOXVILLE company ----------------

def test_nothing_claims_we_are_a_maryville_or_blount_company():
    """Founder: 'everything is a Knoxville company. I see you've put Blount county
    and Maryville a lot.' GateWay is based in KNOXVILLE and serves the surrounding
    areas. Getting a company's own hometown wrong on its own storefront is not a
    small thing."""
    bad = []
    for root, _dirs, files in os.walk(os.path.join(ROOT, "app")):
        if "__pycache__" in root:
            continue
        for f in files:
            if not f.endswith((".html", ".py", ".js", ".json", ".css")):
                continue
            src = open(os.path.join(root, f), encoding="utf-8", errors="ignore").read()
            for term in ("Blount", "Maryville"):
                if term in src:
                    bad.append(f"{f}: {term}")
    assert not bad, f"wrong hometown: {bad}"


def test_the_storefront_says_knoxville():
    assert "Knoxville" in client.get("/").text


# ---------------- the cart bar the founder photographed ----------------

def test_only_one_cartbar_rule_exists():
    """The screenshot showed 'Subtotal$9.00' — label and amount collided. Cause:
    THREE stacked .cartbar rules, one an old flex-ROW with align-items:center that
    crushed each line to content width. Same failure as the v0.51 triple .mitem."""
    form = _page("order-form.html")
    assert form.count(".cartbar{") == 1, "duplicate .cartbar rules are back"


def test_money_lines_can_never_collide_again():
    form = _page("order-form.html")
    assert ".cbline{display:flex;justify-content:space-between" in form
    assert "width:100%" in form
    assert "font-variant-numeric:tabular-nums" in form   # digits line up


def test_the_cartbar_is_on_the_css_sanity_watchlist():
    """The guard existed and still missed this, because .cartbar wasn't on its
    list. A guard that doesn't watch the thing that broke is decoration."""
    guard = open(os.path.join(ROOT, "tests", "test_css_sanity.py")).read()
    for sel in (".cartbar{", ".cbline{", ".cbtot{"):
        assert sel in guard


# ---------------- the menu and YOUR ORDER are different rooms ----------------

def test_the_order_form_is_two_steps_not_one_long_form():
    """Founder: 'I don't like how the menu and the your order part are in the same
    screen. That should be separate.' Shopping and checking out are different jobs."""
    form = _page("order-form.html")
    assert 'id="stepMenu"' in form and 'id="stepCheckout"' in form
    assert "function goCheckout()" in form and "function goMenu()" in form
    assert "paintReview" in form


def test_back_goes_back_one_room_not_out_of_the_building():
    """From checkout, Back must return to the MENU — not dump the customer out of
    the store and lose their cart."""
    form = _page("order-form.html")
    assert "function stepBack()" in form
    assert "STEP === 'checkout'" in form and "goMenu()" in form


def test_back_lives_inside_the_page_not_pinned_above_it():
    """Founder: 'the back button should go with the page somehow instead of being
    fixed at the very top.'"""
    form = _page("order-form.html")
    header = form[form.index("<header>"):form.index("</header>")]
    assert "gw-back" in header, "back button is not inside the page header"
    # and it must not be position:fixed
    css = form[form.index("<style>"):form.index("</style>")]
    m = re.search(r"\.gw-back\{[^}]*\}", css)
    assert m and "position:fixed" not in m.group(0)


def test_the_courier_form_has_no_fake_menu_step():
    """The generic courier form has no menu to browse — it must not pretend to be
    a two-step storefront."""
    form = _page("order-form.html")
    assert "if(!HAS_MENU){" in form


# ---------------- the app opens like a door ----------------

def test_the_splash_has_a_real_progress_bar():
    """Founder: 'the ones you've made are really fast and seem glitchy. I'd like
    them smoother, show a loading circle or bar... make them feel like they're
    diving in and the app is big/heavy/deep.'"""
    js = open(os.path.join(UI, "static", "gw-splash.js")).read()
    assert "gws-fill" in js and "gws-track" in js


def test_the_splash_waits_for_the_page_instead_of_ripping_the_curtain_down():
    js = open(os.path.join(UI, "static", "gw-splash.js")).read()
    assert "readyState" in js and "load" in js
    assert "bar && page" in js


def test_the_splash_can_never_trap_anyone_behind_it():
    """A loading screen that doesn't leave is a broken app. There is a hard ceiling."""
    js = open(os.path.join(UI, "static", "gw-splash.js")).read()
    assert re.search(r"setTimeout\(done, hold \+ \d+\)", js)


def test_the_splash_shows_once_per_session_not_on_every_tap():
    js = open(os.path.join(UI, "static", "gw-splash.js")).read()
    assert "sessionStorage" in js


def test_the_splash_respects_reduced_motion():
    js = open(os.path.join(UI, "static", "gw-splash.js")).read()
    assert "prefers-reduced-motion" in js


def test_the_app_and_the_storefront_both_open_with_a_splash():
    assert "gwSplash(" in _page("home.html")
    assert "gwSplash(" in _page("order-form.html")
    assert "gwSplash(" in _page("courier.html")


# ---------------- GateWay Courier: its own service ----------------

def test_courier_is_a_real_surface():
    """Founder: 'the custom delivery submission part... that can become its own
    thing because that really is a huge part of our model.'"""
    r = client.get("/courier")
    assert r.status_code == 200
    assert "GateWay" in r.text and "Courier" in r.text


def test_the_home_links_to_courier_and_it_is_not_a_dead_link():
    home = client.get("/")
    assert "/courier" in home.text
    assert client.get("/courier").status_code == 200


def test_courier_offers_the_jobs_people_actually_need():
    c = _page("courier.html")
    for job in ("Forgot an item", "Prescription", "Send a gift",
                "Vendor supplies", "Documents"):
        assert job in c


def test_courier_says_the_price_out_loud_before_anyone_drives():
    """We quote from a base and let dispatch confirm. Nobody is surprised at the
    door — that is the whole promise."""
    c = _page("courier.html")
    assert "BASE_CENTS" in c
    assert "confirms the final price" in c


def test_courier_keeps_the_tip_promise():
    c = _page("courier.html")
    assert "100% of it goes to your driver" in c


def test_courier_posts_a_real_order_to_dispatch():
    c = _page("courier.html")
    assert "/v0/intake" in c
    assert "[COURIER" in c        # tagged so the board knows what it is


def test_courier_takes_cash_like_the_rest_of_gateway():
    c = _page("courier.html")
    assert "Cash at the door" in c


# ---------------- the guards that should have caught all this ----------------

def test_the_js_guard_watches_every_page_not_a_hand_written_list():
    """courier.html shipped with a double-escaped apostrophe — the exact bug that
    froze the dispatch board in v0.8 — because it wasn't on the guard's list. The
    list is now discovered, not maintained."""
    guard = open(os.path.join(ROOT, "tests", "test_js_syntax.py")).read()
    assert "os.listdir" in guard


def test_every_ui_page_is_actually_reachable_or_deliberate():
    """A page nobody can reach is dead code; a link to a page that doesn't exist is
    a 404 in a customer's face."""
    for path in ("/", "/order", "/courier", "/support", "/team",
                 "/drive-with-us", "/partner-with-us", "/me"):
        assert client.get(path).status_code == 200, path
