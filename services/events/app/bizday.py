"""The business day.

Everything a restaurant, a driver, or a dispatcher calls "today" has to mean
*their* today. Computing it in UTC was a real operational bug: Knoxville is
UTC-4 in summer, so at 8:00 PM local the server's calendar date rolled to
tomorrow — in the middle of dinner service. A kitchen's "revenue today" reset to
zero on its busiest hour, and a driver working the dinner shift watched their
"tips today" drop to $0.00 while they were still driving.

One market for now, so one timezone constant. When GateWay opens a second metro
this becomes a per-market lookup, and every caller already routes through here.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# The market GateWay operates in — Knoxville, Tennessee and the surrounding area.
MARKET_TZ = ZoneInfo("America/New_York")


def local_now() -> datetime:
    """Wall-clock time in the market GateWay actually serves."""
    return datetime.now(MARKET_TZ)


def business_day(offset_days: int = 0) -> str:
    """Today's date as the kitchen would write it on a ticket — YYYY-MM-DD in
    market-local time. Rolls over at local midnight, not UTC midnight."""
    return (local_now() + timedelta(days=offset_days)).strftime("%Y-%m-%d")


def business_day_of(stamp: str) -> str:
    """Which business day a stored timestamp belongs to.

    Timestamps are written in UTC (ISO 8601); a delivery at 9 PM local is stored
    as the next UTC date, so converting back to market time before taking the
    date is what makes 'delivered today' honest. Returns '' when the stamp is
    missing or unparseable, so callers can skip it rather than mis-bucket it.
    """
    if not stamp:
        return ""
    try:
        dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return ""
    if dt.tzinfo is None:
        from datetime import timezone as _tz
        dt = dt.replace(tzinfo=_tz.utc)
    return dt.astimezone(MARKET_TZ).strftime("%Y-%m-%d")


def at_day(field: str) -> str:
    """Airtable formula fragment: a UTC-stored timestamp field rendered as its
    MARKET-LOCAL calendar date.

    Both sides of a day comparison have to agree on which timezone "the day"
    means. Airtable's DATETIME_FORMAT renders in UTC by default, so comparing it
    against a local date string silently mis-bucketed every order placed after
    8 PM local. SET_TIMEZONE fixes the field side; business_day() fixes ours.

    Only use this for server-written UTC timestamps (received_at, delivered_at,
    confirmed_at...). Do NOT use it on requested_for, which the browser submits
    as naive local wall-clock time and is already in market time.
    """
    return f"DATETIME_FORMAT(SET_TIMEZONE({{{field}}},'America/New_York'),'YYYY-MM-DD')"
