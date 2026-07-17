"""v1.9.13 — desktop order alerts, bottom-nav spacing, DoorDash-sized cover photo."""
import os
UI = os.path.join(os.path.dirname(__file__), "..", "app", "ui")


def _f(n):
    return open(os.path.join(UI, n)).read()


def test_board_has_desktop_notification_alert():
    b = _f("board.html")
    assert "requestOrderAlerts" in b
    assert "new Notification(" in b
    assert "requireInteraction: true" in b


def test_board_poll_interval_tightened_to_20s():
    b = _f("board.html")
    assert "}, 20000);" in b


def test_kitchen_has_desktop_notification_alert():
    k = _f("kitchen.html")
    assert "requestOrderAlerts" in k
    assert "new Notification(" in k


def test_bottom_nav_tabs_have_clear_gaps_everywhere():
    for name in ("home.html", "activity.html", "courier.html", "me.html", "support.html"):
        s = _f(name)
        assert ".gw-navin{pointer-events:auto;display:flex;gap:5px" in s, name


def test_bottom_nav_never_touches_screen_edge():
    for name in ("home.html", "activity.html", "courier.html", "me.html", "support.html"):
        s = _f(name)
        assert "padding:0 12px max(10px" in s, name


def test_cover_photo_is_doordash_proportioned_not_16_9():
    o = _f("order-form.html")
    assert "aspect-ratio:2.75/1" in o
    assert "aspect-ratio:16/9" not in o
