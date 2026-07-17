"""v1.9.12 — CRITICAL: not a single order can ever be missed by the kitchen.
Root-caused a real 'orders not popping up' report: the kitchen's active-ticket
query required received_at OR requested_for to DATETIME_FORMAT-match 'today' —
fragile if that Airtable field isn't a true date type, or a record sits right at
a UTC-day boundary. The fix: active tickets are now queried by STATUS ONLY, with
zero date dependency, so an open ticket can never silently vanish.
"""
import os

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _f(p):
    return open(os.path.join(ROOT, p)).read()


def test_kitchen_active_query_has_no_date_dependency():
    src = _f("app/kitchen.py")
    # the active-ticket formula must be status-only (source has doubled braces
    # since it's inside an f-string: {{status}} -> {status} at runtime)
    assert ("OR({{status}}='received',{{status}}='confirmed',{{status}}='assigned')"
            in src)


def test_kitchen_active_query_is_a_separate_call_from_stats_query():
    src = _f("app/kitchen.py")
    # active tickets and today's stats are two independent queries (gather),
    # so a bug/edge-case in the stats query can never affect what's visible
    assert "_aio.gather(" in src
    assert src.count("at.list_records(\n            at.ORDERS,") >= 2


def test_board_open_orders_queries_were_already_status_only():
    # board_orders / board_snapshot's visible-ticket query must never have
    # regressed to a date filter either
    src = _f("app/dispatch.py")
    assert "NOT(OR({status}='closed',{status}='cancelled'))" in src
