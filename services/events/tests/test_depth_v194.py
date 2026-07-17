"""v1.9.5 — depth pass: home highlights, driver My-day history, kitchen
Today-in-review. Plus regression locks on the presentation-critical fixes."""
import os
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
ROOT = os.path.join(os.path.dirname(__file__), "..")


def _f(p):
    return open(os.path.join(ROOT, p)).read()


# ---- highlights ----

def test_highlights_endpoint_serves_and_never_invents_news():
    r = client.get("/v0/highlights")
    assert r.status_code == 200
    d = r.json()
    assert "highlights" in d
    # with no specials posted and no fresh partners, real news may be empty —
    # and that's correct: we never pad it with filler
    for h in d["highlights"]:
        assert h["kind"] in ("special", "new_partner", "fund")


def test_home_renders_highlights_rail():
    h = _f("app/ui/home.html")
    assert 'id="highlights"' in h
    assert "/v0/highlights" in h
    assert "Happening now" in h


# ---- driver depth ----

def test_day_sheet_returns_done_list_for_history():
    src = _f("app/dispatch.py")
    assert '"done_list"' in src
    assert "my_done[:30]" in src


def test_driver_hub_has_my_day_panel():
    d = _f("app/ui/driver.html")
    assert "toggleMyDay" in d and "paintMyDay" in d
    assert 'id="myDayPanel"' in d


# ---- kitchen depth ----

def test_kitchen_history_endpoint_exists():
    k = _f("app/kitchen.py")
    assert "/api/kitchen/{token}/history" in k
    assert "top_sellers" in k


def test_kitchen_ui_has_today_in_review():
    k = _f("app/ui/kitchen.html")
    assert "toggleHistory" in k
    assert "Today in review" in k


# ---- regression locks on the presentation criticals ----

def test_no_page_uses_the_safari_scroll_breaking_pattern():
    import glob
    bad = []
    for p in glob.glob(os.path.join(ROOT, "app", "ui", "*.html")) + [
            os.path.join(ROOT, "app", "track.py")]:
        if "html,body{max-width:100%;overflow-x:hidden}" in open(p).read():
            bad.append(os.path.basename(p))
    assert not bad, f"Safari scroll-breaker pattern returned in: {bad}"


def test_splash_gates_are_time_based_not_forever():
    o = _f("app/ui/order-form.html")
    s = _f("app/ui/static/gw-splash.js")
    assert "10*60*1000" in o        # per-merchant door: 10 min
    assert "30 * 60 * 1000" in s    # global splash: 30 min


def test_board_tickets_are_tappable():
    b = _f("app/ui/board.html")
    assert 'role="button"' in b and "jumpTo('${esc(o.order_id)}')" in b
    assert "event.stopPropagation()" in b  # action buttons don't also open it


def test_driver_sheet_uses_split_queries():
    src = _f("app/dispatch.py")
    assert "OR({status}='assigned',{status}='in_transit')" in src
    assert "_aio.gather" in src
