"""v1.9.31 — kitchens close themselves.

Before this a kitchen could only close by remembering to hit "pause". Forget
once on a Sunday night and a customer orders into a dark building: nothing gets
made, they wait, and someone refunds and apologises.

Two safety rules the tests pin down:
  * no hours set = always open (nobody gets surprise-closed by a feature they
    never configured, and a corrupt field can't close a business)
  * a SCHEDULED order is judged at the time it's FOR, not when it's placed —
    ordering Friday lunch on Thursday night is the whole point of scheduling
"""
import json
from datetime import datetime, timedelta

from app.hours import status, summary, parse_hours
from app.bizday import MARKET_TZ


class _P:
    def __init__(self, h):
        self.hours_json = json.dumps(h) if h else ""


def _at(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=MARKET_TZ)


NORMAL = _P({"mon": ["11:00", "21:00"], "tue": ["11:00", "21:00"],
             "wed": ["11:00", "21:00"], "thu": ["11:00", "21:00"],
             "fri": ["11:00", "22:00"], "sat": ["11:00", "22:00"], "sun": None})
LATE = _P({d: ["17:00", "02:00"] for d in
           ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]})


# --- safety defaults: these must never close a business by accident ---

def test_no_hours_means_always_open():
    assert status(_P(None))["open"] is True


def test_corrupt_hours_field_means_always_open():
    class Broken:
        hours_json = "{{{not json"
    assert status(Broken())["open"] is True


def test_empty_hours_means_always_open():
    assert status(_P({}))["open"] is True


def test_garbage_times_are_ignored_not_honoured():
    assert parse_hours(json.dumps({"mon": ["25:99", "banana"]})) == {}


def test_a_partly_filled_week_does_not_close_the_other_days():
    """Caught in review: reading an ABSENT day as null meant a kitchen that set
    only Monday's hours was marked closed Tuesday through Sunday — accidentally
    shutting the business six days a week."""
    only_monday = parse_hours(json.dumps({"mon": ["11:00", "21:00"]}))
    assert only_monday == {"mon": ["11:00", "21:00"]}
    tuesday_2pm = _at(2026, 7, 21, 14, 0)
    assert status(_P({"mon": ["11:00", "21:00"]}), tuesday_2pm)["open"] is True


def test_explicit_null_still_means_closed():
    """The other half of the same distinction — a deliberate closure must hold."""
    assert parse_hours(json.dumps({"sun": None})) == {"sun": None}


# --- ordinary trading ---

def test_open_during_posted_hours():
    assert status(NORMAL, _at(2026, 7, 22, 12, 0))["open"] is True


def test_closed_before_opening_says_when_it_opens():
    s = status(NORMAL, _at(2026, 7, 22, 9, 0))
    assert s["open"] is False
    assert "11am" in s["message"]


def test_closed_after_hours():
    assert status(NORMAL, _at(2026, 7, 22, 22, 0))["open"] is False


def test_a_closed_day_is_closed():
    assert status(NORMAL, _at(2026, 7, 26, 13, 0))["open"] is False   # Sunday


# --- the case naive implementations get wrong ---

def test_overnight_span_is_still_open_after_midnight():
    """Open 5pm-2am: at 1am you are inside LAST NIGHT'S shift, not today's."""
    assert status(LATE, _at(2026, 7, 23, 1, 0))["open"] is True


def test_overnight_span_is_closed_after_it_ends():
    assert status(LATE, _at(2026, 7, 23, 3, 0))["open"] is False


def test_overnight_span_is_open_in_the_evening():
    assert status(LATE, _at(2026, 7, 22, 18, 0))["open"] is True


# --- presentation ---

def test_summary_reads_like_a_human_wrote_it():
    rows = summary(NORMAL)
    assert {"day": "Monday", "text": "11am – 9pm"} in rows
    assert {"day": "Sunday", "text": "Closed"} in rows


def test_wiring_is_in_place():
    import os
    root = os.path.join(os.path.dirname(__file__), "..", "app")
    intake = open(os.path.join(root, "intake.py")).read()
    assert "kitchen_closed" in intake
    # scheduled orders are judged at the requested time, not "now"
    assert "hours.status(p, when)" in intake
    kitchen = open(os.path.join(root, "kitchen.py")).read()
    assert "/api/kitchen/{token}/hours" in kitchen
    ui = open(os.path.join(root, "ui", "kitchen.html")).read()
    assert "toggleHours" in ui and "saveHours" in ui
    storefront = open(os.path.join(root, "ui", "order-form.html")).read()
    assert "hours_status" in storefront
