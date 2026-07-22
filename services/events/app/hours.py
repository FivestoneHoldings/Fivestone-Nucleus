"""Opening hours.

Until now a kitchen could only close by remembering to hit "pause". Forget once
on a Sunday night and a customer orders into a dark building: the order sits
unmade, the customer waits, and someone has to refund it and apologise. Hours
are the fix — the storefront closes itself.

Two deliberate choices:

1. NO HOURS SET MEANS ALWAYS OPEN. A partner who has never configured hours
   behaves exactly as before. Nobody gets surprise-closed by a feature they
   didn't ask for; the check only applies to kitchens that opted in.

2. THE MANUAL PAUSE STILL WINS. Hours say when a kitchen normally trades; the
   pause button says what's true right now (slammed, staff out, walk-in rush).
   A kitchen inside its hours but paused is closed, and no schedule overrides
   the human standing in the kitchen.

Times are stored as plain local "HH:MM" strings against the market timezone —
the same wall clock a cook reads off the wall, with no timezone arithmetic to
get wrong. Overnight spans (open 17:00, close 02:00) are supported, since
kitchens that close after midnight are exactly the ones a naive comparison
breaks on.
"""
import json
from datetime import datetime, timedelta

from .bizday import MARKET_TZ

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_LABELS = {"mon": "Monday", "tue": "Tuesday", "wed": "Wednesday",
              "thu": "Thursday", "fri": "Friday", "sat": "Saturday",
              "sun": "Sunday"}


def parse_hours(raw):
    """Stored JSON -> {day: [open, close] | None}. Bad data reads as 'no hours
    set', which means always open — a corrupt field must never silently close a
    business."""
    if not raw:
        return {}
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    _MISSING = object()
    for day in DAYS:
        span = data.get(day, _MISSING)
        if span is _MISSING:
            continue                             # day absent = unspecified = open
        if span is None:
            out[day] = None                      # explicitly closed that day
        elif (isinstance(span, (list, tuple)) and len(span) == 2
              and all(_valid_time(t) for t in span)):
            out[day] = [str(span[0]), str(span[1])]
        # present but malformed: treat as unspecified rather than closed, so a
        # bad value can never silently shut a kitchen
    return out


def _valid_time(t):
    try:
        h, m = str(t).split(":")
        return 0 <= int(h) <= 23 and 0 <= int(m) <= 59
    except (ValueError, AttributeError):
        return False


def _mins(t):
    h, m = str(t).split(":")
    return int(h) * 60 + int(m)


def _fmt(t):
    """'17:00' -> '5pm', '17:30' -> '5:30pm' — how a person says it."""
    try:
        h, m = [int(x) for x in str(t).split(":")]
    except (ValueError, AttributeError):
        return str(t)
    ampm = "am" if h < 12 else "pm"
    h12 = (h % 12) or 12
    return f"{h12}:{m:02d}{ampm}" if m else f"{h12}{ampm}"


def status(partner, now=None):
    """Is this kitchen open right now?

    Returns {open, reason, message, next_open}. `open` is what the storefront
    and intake act on; `message` is what a customer reads."""
    now = now or datetime.now(MARKET_TZ)
    hours = parse_hours(getattr(partner, "hours_json", ""))
    if not hours:
        return {"open": True, "reason": "no_hours", "message": "", "next_open": ""}

    today_key = DAYS[now.weekday()]
    minute_now = now.hour * 60 + now.minute

    # An overnight span from YESTERDAY can still be running (open 17:00,
    # close 02:00 — at 1am we're inside last night's shift, not today's).
    y_key = DAYS[(now.weekday() - 1) % 7]
    y_span = hours.get(y_key)
    if y_span and _mins(y_span[1]) <= _mins(y_span[0]):
        if minute_now < _mins(y_span[1]):
            return {"open": True, "reason": "overnight", "message": "",
                    "next_open": ""}

    span = hours.get(today_key, "unspecified")
    if span == "unspecified":
        return {"open": True, "reason": "unspecified_day", "message": "",
                "next_open": ""}
    if span is not None:
        o, c = _mins(span[0]), _mins(span[1])
        inside = (o <= minute_now < c) if c > o else (minute_now >= o)
        if inside:
            return {"open": True, "reason": "within_hours", "message": "",
                    "next_open": ""}
        if minute_now < o:                       # opens later today
            return {"open": False, "reason": "before_open",
                    "message": f"Opens at {_fmt(span[0])} today",
                    "next_open": _fmt(span[0])}

    nxt = _next_opening(hours, now)
    return {"open": False, "reason": "closed",
            "message": f"Closed — {nxt}" if nxt else "Closed right now",
            "next_open": nxt}


def _next_opening(hours, now):
    """'opens Monday at 11am' — searching forward a week."""
    for ahead in range(1, 8):
        d = now + timedelta(days=ahead)
        span = hours.get(DAYS[d.weekday()], "unspecified")
        if span == "unspecified":
            return f"opens {DAY_LABELS[DAYS[d.weekday()]]}"
        if span:
            when = "tomorrow" if ahead == 1 else DAY_LABELS[DAYS[d.weekday()]]
            return f"opens {when} at {_fmt(span[0])}"
    return ""


def summary(partner):
    """Human-readable week, for the storefront's info panel."""
    hours = parse_hours(getattr(partner, "hours_json", ""))
    if not hours:
        return []
    out = []
    for day in DAYS:
        span = hours.get(day, "unspecified")
        if span == "unspecified":
            continue
        out.append({"day": DAY_LABELS[day],
                    "text": "Closed" if span is None
                            else f"{_fmt(span[0])} – {_fmt(span[1])}"})
    return out
