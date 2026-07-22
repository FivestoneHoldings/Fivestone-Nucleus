"""Insights: history, trends, and projections.

Data is only worth something if you can act on it, and you can only act on it if
you trust it. The whole design of this module is built around one rule:

    NEVER LET THIN DATA LOOK LIKE A TREND.

Three orders on a Tuesday is not a pattern. A single good Saturday is not
growth. Every number that comes out of here carries the sample it was computed
from and a confidence label, and anything below the bar comes back as
"not enough data yet" with a plain statement of what's still needed. A founder
making a hiring decision, a kitchen deciding whether to add staff, and a driver
deciding which hours to work all deserve to know the difference between a signal
and a coin flip.

Projections here are deliberately simple — a recent-average run rate, with the
basis stated. No fitted curve, no seasonality model, no machine learning. Those
need far more history than a young business has, and a sophisticated-looking
number is more dangerous than an honest rough one, because people believe it.
"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from .bizday import business_day, business_day_of

# --- Confidence gates -------------------------------------------------------
# Each threshold is a judgement call about when a number stops being noise.
MIN_ORDERS_FOR_AVERAGE = 10      # below this, one big order swings the mean
MIN_DAYS_FOR_TREND = 7           # a week, so weekday/weekend cycles cancel out
MIN_ORDERS_FOR_TREND = 20        # and enough volume inside those days
MIN_ORDERS_FOR_PEAK = 15         # before claiming a "busiest hour"

REVENUE_STATUSES = ("in_transit", "delivered", "closed")
COMPLETED_STATUSES = ("delivered", "closed")


def _cents(rec, field="subtotal_cents"):
    try:
        return int(rec.get("fields", {}).get(field) or 0)
    except (TypeError, ValueError):
        return 0


def _status(rec):
    return rec.get("fields", {}).get("status", "")


def _day_of(rec):
    f = rec.get("fields", {})
    return business_day_of(f.get("delivered_at") or f.get("received_at") or "")


def daily_series(records, days=30):
    """Orders and revenue per business day, oldest first, with empty days kept.

    Gaps matter: a kitchen that did nothing on Monday should SEE the zero, not
    have Monday quietly vanish and make the week look busier than it was."""
    today = datetime.strptime(business_day(), "%Y-%m-%d")
    window = [(today - timedelta(days=i)).strftime("%Y-%m-%d")
              for i in range(days - 1, -1, -1)]
    orders = Counter()
    revenue = Counter()
    for r in records:
        d = _day_of(r)
        if not d:
            continue
        orders[d] += 1
        if _status(r) in REVENUE_STATUSES:
            revenue[d] += _cents(r)
    return [{"date": d, "orders": orders.get(d, 0),
             "revenue_cents": revenue.get(d, 0)} for d in window]


def summarize(records):
    """Headline totals. Averages are withheld until the sample supports them."""
    completed = [r for r in records if _status(r) in COMPLETED_STATUSES]
    earning = [r for r in records if _status(r) in REVENUE_STATUSES]
    revenue = sum(_cents(r) for r in earning)
    tips = sum(_cents(r, "tip_cents") for r in earning)
    n = len(completed)
    out = {
        "orders_total": len(records),
        "orders_completed": n,
        "revenue_cents": revenue,
        "tips_cents": tips,
        "cancelled": sum(1 for r in records if _status(r) == "cancelled"),
    }
    if len(earning) >= MIN_ORDERS_FOR_AVERAGE:
        out["avg_order_cents"] = round(revenue / len(earning))
        out["avg_order_confidence"] = "ok"
    else:
        out["avg_order_cents"] = None
        out["avg_order_confidence"] = "insufficient"
        out["avg_order_needs"] = MIN_ORDERS_FOR_AVERAGE - len(earning)
    return out


def busiest_hours(records, top=3):
    """When the rush actually is — withheld until there's enough to mean it."""
    hours = Counter()
    for r in records:
        stamp = r.get("fields", {}).get("received_at") or ""
        if len(stamp) >= 13:
            try:
                dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                from .bizday import MARKET_TZ
                hours[dt.astimezone(MARKET_TZ).hour] += 1
            except (ValueError, TypeError):
                continue
    total = sum(hours.values())
    if total < MIN_ORDERS_FOR_PEAK:
        return {"confidence": "insufficient",
                "needs": MIN_ORDERS_FOR_PEAK - total, "hours": []}
    return {"confidence": "ok",
            "hours": [{"hour": h, "orders": c} for h, c in hours.most_common(top)]}


def busiest_days(records):
    """Which weekdays carry the business."""
    names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday"]
    days = Counter()
    for r in records:
        d = _day_of(r)
        if d:
            try:
                days[datetime.strptime(d, "%Y-%m-%d").weekday()] += 1
            except ValueError:
                continue
    total = sum(days.values())
    if total < MIN_ORDERS_FOR_PEAK:
        return {"confidence": "insufficient",
                "needs": MIN_ORDERS_FOR_PEAK - total, "days": []}
    return {"confidence": "ok",
            "days": [{"day": names[d], "orders": c}
                     for d, c in days.most_common(3)]}


def trend(series):
    """Compare the most recent 7 days against the 7 before them.

    Returns a direction only when there's a real week-on-week comparison to
    make AND enough volume in it. A 40% jump on four orders is noise wearing a
    percentage sign."""
    if len(series) < MIN_DAYS_FOR_TREND * 2:
        return {"confidence": "insufficient",
                "reason": f"needs {MIN_DAYS_FOR_TREND * 2} days of history"}
    recent = series[-MIN_DAYS_FOR_TREND:]
    prior = series[-MIN_DAYS_FOR_TREND * 2:-MIN_DAYS_FOR_TREND]
    r_orders = sum(d["orders"] for d in recent)
    p_orders = sum(d["orders"] for d in prior)
    if r_orders + p_orders < MIN_ORDERS_FOR_TREND:
        return {"confidence": "insufficient",
                "reason": f"needs {MIN_ORDERS_FOR_TREND} orders across two weeks",
                "have": r_orders + p_orders}
    r_rev = sum(d["revenue_cents"] for d in recent)
    p_rev = sum(d["revenue_cents"] for d in prior)
    def _pct(new, old):
        if old == 0:
            return None            # "up from nothing" is not a percentage
        return round((new - old) / old * 100)
    return {
        "confidence": "ok",
        "orders_this_week": r_orders, "orders_last_week": p_orders,
        "orders_change_pct": _pct(r_orders, p_orders),
        "revenue_this_week_cents": r_rev, "revenue_last_week_cents": p_rev,
        "revenue_change_pct": _pct(r_rev, p_rev),
        "direction": ("up" if r_orders > p_orders
                      else "down" if r_orders < p_orders else "flat"),
    }


def project(series, horizon_days=7):
    """Run-rate projection: recent daily average carried forward.

    Deliberately unsophisticated. With a few weeks of history a fitted curve
    would be false precision — this states exactly what it is ("based on your
    last N days") so nobody mistakes it for a forecast it isn't."""
    active = [d for d in series if d["orders"] > 0]
    if len(active) < MIN_DAYS_FOR_TREND:
        return {"confidence": "insufficient",
                "reason": f"needs {MIN_DAYS_FOR_TREND} days with orders",
                "have": len(active)}
    basis = series[-14:] if len(series) >= 14 else series
    days = len(basis)
    avg_orders = sum(d["orders"] for d in basis) / days
    avg_revenue = sum(d["revenue_cents"] for d in basis) / days
    # Spread across the basis tells us how much to trust the average. A kitchen
    # doing 10,10,11 a day is predictable; one doing 0,1,30 is not.
    counts = [d["orders"] for d in basis]
    mean = sum(counts) / days
    variance = sum((c - mean) ** 2 for c in counts) / days
    spread = (variance ** 0.5) / mean if mean else 0
    return {
        "confidence": "ok" if spread < 0.75 else "rough",
        "basis_days": days,
        "spread": round(spread, 2),
        "projected_orders": round(avg_orders * horizon_days),
        "projected_revenue_cents": round(avg_revenue * horizon_days),
        "horizon_days": horizon_days,
        "per_day_orders": round(avg_orders, 1),
    }


def top_items(records, top=5):
    """Best sellers, parsed from the real ticket text."""
    import re
    counts = Counter()
    for r in records:
        raw = (r.get("fields", {}).get("items_description") or "").split(" — subtotal")[0]
        for part in re.split(r",\s*(?=\d+\s*[×xX])", raw):
            m = re.match(r"^\s*(\d+)\s*[×xX]\s*(.+?)(?:\s*\(\$[\d.]+\))?\s*$", part)
            if m:
                counts[m.group(2).strip()[:60]] += int(m.group(1))
    return [{"name": n, "qty": q} for n, q in counts.most_common(top)]


def repeat_rate(records):
    """How many customers come back — the single clearest health signal for a
    local business, and the one the big platforms never show a merchant."""
    by_phone = defaultdict(int)
    for r in records:
        phone = (r.get("fields", {}).get("customer_phone_raw") or "").strip()
        if phone:
            by_phone[phone] += 1
    if len(by_phone) < MIN_ORDERS_FOR_AVERAGE:
        return {"confidence": "insufficient",
                "needs": MIN_ORDERS_FOR_AVERAGE - len(by_phone)}
    repeats = sum(1 for c in by_phone.values() if c > 1)
    return {"confidence": "ok", "customers": len(by_phone), "returning": repeats,
            "repeat_pct": round(repeats / len(by_phone) * 100)}


def build_report(records, horizon_days=7, include_items=True):
    """One assembled view for any audience."""
    series = daily_series(records, days=30)
    report = {
        "summary": summarize(records),
        "series": series,
        "trend": trend(series),
        "projection": project(series, horizon_days),
        "busiest_hours": busiest_hours(records),
        "busiest_days": busiest_days(records),
        "repeat": repeat_rate(records),
    }
    if include_items:
        report["top_items"] = top_items(records)
    return report
