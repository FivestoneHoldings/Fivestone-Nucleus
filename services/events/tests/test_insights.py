"""v1.9.30 — history, trends and projections that refuse to lie.

The governing rule: thin data must never look like a trend. Three orders on a
Tuesday is not a pattern; one good Saturday is not growth. Every figure carries
the sample behind it and a confidence label, and anything below the bar comes
back as "not enough yet" with what's still needed — because a founder deciding
whether to hire, a kitchen deciding whether to add staff, and a driver deciding
which hours to work all deserve to know a signal from a coin flip.
"""
import os
from datetime import datetime, timedelta, timezone

from app import insights
from app.bizday import MARKET_TZ


def _order(days_ago, cents=2000, status="delivered", phone="8650000", hour=18):
    d = (datetime.now(MARKET_TZ) - timedelta(days=days_ago)).replace(hour=hour)
    return {"fields": {"status": status, "subtotal_cents": cents, "tip_cents": 300,
                       "received_at": d.astimezone(timezone.utc).isoformat(),
                       "delivered_at": d.astimezone(timezone.utc).isoformat(),
                       "customer_phone_raw": phone,
                       "items_description": "2× Pad Thai ($13.05), 1× Rangoons ($9.05)"}}


THIN = [_order(0), _order(1), _order(2)]
RICH = [_order(d, phone=f"865{(d * 7 + i) % 40}") for d in range(25) for i in range(3)]


# --- the core promise ---

def test_thin_data_refuses_to_produce_a_trend():
    assert insights.trend(insights.daily_series(THIN))["confidence"] == "insufficient"


def test_thin_data_refuses_to_project():
    assert insights.project(insights.daily_series(THIN))["confidence"] == "insufficient"


def test_thin_data_withholds_the_average_order():
    s = insights.summarize(THIN)
    assert s["avg_order_cents"] is None
    assert s["avg_order_confidence"] == "insufficient"
    assert s["avg_order_needs"] > 0          # and says how many more are needed


def test_thin_data_refuses_to_name_a_rush_hour():
    assert insights.busiest_hours(THIN)["confidence"] == "insufficient"


def test_real_history_does_produce_a_trend_and_projection():
    series = insights.daily_series(RICH)
    assert insights.trend(series)["confidence"] == "ok"
    p = insights.project(series)
    assert p["confidence"] in ("ok", "rough")
    assert p["projected_orders"] > 0
    assert p["basis_days"] > 0                # always states what it's based on


def test_volatile_history_is_marked_rough_not_confident():
    """0,0,30,0,1 a day is not a run rate you should bet staffing on."""
    pattern = [0, 0, 30, 0, 1, 0, 12, 0, 0, 20, 1, 0, 0, 15,
               0, 2, 0, 0, 25, 0, 1, 0, 8, 0, 3]
    vol = [_order(d, phone=f"865{d}{i}") for d, n in enumerate(pattern) for i in range(n)]
    assert insights.project(insights.daily_series(vol))["confidence"] == "rough"


# --- correctness of the underlying maths ---

def test_series_keeps_empty_days_visible():
    """A day with no orders must show as a zero, not silently vanish and make
    the week look busier than it was."""
    series = insights.daily_series([_order(0), _order(10)], days=30)
    assert len(series) == 30
    assert sum(1 for d in series if d["orders"] == 0) == 28


def test_growth_from_zero_is_not_reported_as_a_percentage():
    """'Up 100%' from one order is meaningless — the change reads as None."""
    series = [{"date": f"2026-07-{i:02d}", "orders": 0, "revenue_cents": 0} for i in range(1, 8)]
    series += [{"date": f"2026-07-{i:02d}", "orders": 4, "revenue_cents": 8000} for i in range(8, 15)]
    t = insights.trend(series)
    assert t["confidence"] == "ok"
    assert t["orders_change_pct"] is None


def test_revenue_only_counts_orders_that_actually_earned():
    mixed = [_order(1, status="delivered"), _order(1, status="cancelled"),
             _order(1, status="received")]
    s = insights.summarize(mixed)
    assert s["revenue_cents"] == 2000        # only the delivered one
    assert s["cancelled"] == 1


def test_top_items_counts_quantities_not_just_lines():
    items = insights.top_items(RICH)
    assert items[0]["name"] == "Pad Thai"
    assert items[0]["qty"] == 150            # 2 per order across 75 orders


def test_repeat_rate_needs_enough_customers_first():
    assert insights.repeat_rate(THIN)["confidence"] == "insufficient"
    assert insights.repeat_rate(RICH)["confidence"] == "ok"


# --- wiring ---

def test_all_three_apps_expose_insights():
    root = os.path.join(os.path.dirname(__file__), "..", "app")
    assert "/api/board/{key}/insights" in open(os.path.join(root, "dispatch.py")).read()
    assert "/api/driver/{day_token}/insights" in open(os.path.join(root, "dispatch.py")).read()
    assert "/api/kitchen/{token}/insights" in open(os.path.join(root, "kitchen.py")).read()


def test_all_three_apps_render_insights():
    ui = os.path.join(os.path.dirname(__file__), "..", "app", "ui")
    for page in ("board.html", "kitchen.html", "driver.html"):
        s = open(os.path.join(ui, page)).read()
        assert "gw-insights.js" in s, page
        assert "toggleInsights" in s, page
