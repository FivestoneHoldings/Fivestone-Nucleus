"""v1.9.35 — a driver's earnings record, and a real bucketing bug fixed.

THE BUG: the earnings endpoint filtered by market-local date (correctly) but
then bucketed each delivery using the RAW UTC timestamp. A 9pm Knoxville
delivery is 1am UTC the next day, so it was credited to a day the driver
didn't work — their daily totals never matched their actual shifts.

THE FEATURE: drivers are independent contractors. At tax time they need their
own proof of what they earned, and "log into an app and squint at a dashboard"
is not a record.
"""
import os, tempfile
from datetime import datetime, timezone

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///" + tempfile.mktemp(suffix=".db"))
os.environ.setdefault("ADMIN_KEY", "k")

from fastapi.testclient import TestClient
import app.airtable_client as at
import app.dispatch as dispatch
from app.bizday import MARKET_TZ, business_day_of
from app.main import app

DRIVER = {"id": "recD", "fields": {"day_token": "tok1", "display_name": "Marcus Webb"}}
NINE_PM = datetime.now(MARKET_TZ).replace(hour=21, minute=0, second=0, microsecond=0)
UTC_STAMP = NINE_PM.astimezone(timezone.utc).isoformat()

client = TestClient(app)


async def _fake_driver(tok):
    if tok != "tok1":
        from fastapi import HTTPException
        raise HTTPException(404, "no such driver")
    return DRIVER


async def _fake_list(table, formula="", fields=None, max_records=100):
    return [{"id": "r1", "fields": {"order_id": "ORD-A1", "status": "delivered",
                                    "driver": ["recD"], "delivered_at": UTC_STAMP,
                                    "tip_cents": 650, "partner_code": "asiacafe"}},
            {"id": "r2", "fields": {"order_id": "ORD-B2", "status": "delivered",
                                    "driver": ["recD"], "delivered_at": UTC_STAMP,
                                    "tip_cents": 400, "partner_code": "burgerboys"}}]


@pytest.fixture(autouse=True)
def _stubs(monkeypatch):
    monkeypatch.setattr(dispatch, "_driver_by_token", _fake_driver)
    monkeypatch.setattr(at, "list_records", _fake_list)


def test_a_late_delivery_credits_the_day_actually_worked():
    """The regression this release fixes. 9pm local is tomorrow in UTC."""
    assert UTC_STAMP[:10] != NINE_PM.strftime("%Y-%m-%d")   # the trap is real
    assert business_day_of(UTC_STAMP) == NINE_PM.strftime("%Y-%m-%d")
    d = client.get("/api/driver/tok1/earnings").json()
    assert d["days"][0]["date"] == NINE_PM.strftime("%Y-%m-%d")


def test_earnings_totals_are_correct():
    d = client.get("/api/driver/tok1/earnings").json()
    assert d["totals"]["deliveries"] == 2
    assert d["totals"]["tips_cents"] == 1050


def test_statement_downloads_as_a_real_csv_file():
    r = client.get("/api/driver/tok1/statement.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "attachment" in r.headers.get("content-disposition", "")
    assert ".csv" in r.headers.get("content-disposition", "")


def test_statement_has_a_row_per_delivery_and_honest_totals():
    body = client.get("/api/driver/tok1/statement.csv").text
    assert "ORD-A1" in body and "ORD-B2" in body
    assert "6.50" in body and "4.00" in body
    assert "Total tips ($),10.50" in body


def test_statement_states_that_tips_are_untouched():
    """It's the number their taxes turn on — say it plainly on the record."""
    assert "GateWay takes no cut" in client.get("/api/driver/tok1/statement.csv").text


def test_statement_is_named_for_the_driver_and_dated():
    cd = client.get("/api/driver/tok1/statement.csv").headers["content-disposition"]
    assert "marcus-webb" in cd


def test_another_driver_token_gets_nothing():
    assert client.get("/api/driver/BADTOK/statement.csv").status_code == 404


def test_driver_hub_offers_the_download():
    ui = open(os.path.join(os.path.dirname(__file__), "..",
                           "app", "ui", "driver.html")).read()
    assert "statement.csv" in ui
    assert "yours to keep for taxes" in ui
