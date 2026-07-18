"""v1.9.19 — 'today' must mean the MARKET's today.

Computing the business day in UTC was a real operational bug: Knoxville is
UTC-4 in summer, so at 8 PM local the server's date rolled to tomorrow — mid
dinner service. A kitchen's 'revenue today' reset to zero on its busiest hour,
and a driver working the dinner shift watched 'tips today' drop to $0.00.
"""
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from app.bizday import business_day, business_day_of, at_day, MARKET_TZ
from tests.fake_airtable import evaluate

EASTERN = ZoneInfo("America/New_York")


def test_market_timezone_is_the_knoxville_market():
    assert str(MARKET_TZ) == "America/New_York"


def test_nine_pm_delivery_counts_toward_the_same_business_day():
    """The exact bug: 9 PM local is already tomorrow in UTC."""
    nine_pm_local = datetime(2026, 7, 18, 21, 0, tzinfo=EASTERN)
    stored_utc = nine_pm_local.astimezone(timezone.utc).isoformat()
    # stored timestamp really is the next UTC date...
    assert stored_utc.startswith("2026-07-19")
    # ...but it belongs to the 18th's business day
    assert business_day_of(stored_utc) == "2026-07-18"


def test_business_day_of_handles_missing_or_junk_stamps():
    assert business_day_of("") == ""
    assert business_day_of("not-a-date") == ""
    assert business_day_of(None) == ""


def test_business_day_matches_local_wall_clock():
    assert business_day() == datetime.now(EASTERN).strftime("%Y-%m-%d")


def test_airtable_formula_is_timezone_aware():
    f = at_day("delivered_at")
    assert "SET_TIMEZONE" in f
    assert "America/New_York" in f


def test_airtable_day_comparison_buckets_a_9pm_delivery_correctly():
    """Both sides of the comparison must agree on which day it is — proven
    against the fake Airtable evaluator, which models SET_TIMEZONE the way real
    Airtable does."""
    nine_pm_local = datetime(2026, 7, 18, 21, 0, tzinfo=EASTERN)
    rec = {"id": "rec1", "fields": {
        "delivered_at": nine_pm_local.astimezone(timezone.utc).isoformat()}}
    # timezone-aware comparison: counts toward the 18th (correct)
    assert evaluate(f"{at_day('delivered_at')}='2026-07-18'", rec)
    # the old UTC-naive comparison would have mis-bucketed it to the 19th
    assert evaluate("DATETIME_FORMAT({delivered_at},'YYYY-MM-DD')='2026-07-19'", rec)


def test_no_module_still_computes_today_in_utc():
    """Regression lock: the UTC-today pattern must not creep back in."""
    import os, glob
    root = os.path.join(os.path.dirname(__file__), "..", "app")
    offenders = []
    for path in glob.glob(os.path.join(root, "*.py")):
        src = open(path).read()
        if 'datetime.now(timezone.utc).strftime("%Y-%m-%d")' in src:
            offenders.append(os.path.basename(path))
    # intake.py's fingerprint bucket is deliberately UTC (it only has to be
    # stable and self-consistent, never displayed), so it's the one allowance
    assert offenders in ([], ["intake.py"]), f"UTC 'today' returned in: {offenders}"
