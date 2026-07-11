"""Settle-up artifacts: partner-isolated CSV with dollars, statement math + isolation."""
import datetime as _dt
import pytest
from fastapi.testclient import TestClient
import app.airtable_client as at
import app.dispatch as dp
from app.main import app
from tests.fake_airtable import FakeAirtable

client = TestClient(app)
K = "/api/board/test-key"
fake = FakeAirtable()
NOW = _dt.datetime.now(_dt.timezone.utc)
TODAY = NOW.strftime("%Y-%m-%d")
D2 = (NOW - _dt.timedelta(days=2)).strftime("%Y-%m-%d")

fake.seed(at.ORDERS, {"order_id": "ORD-ST-A1", "status": "delivered", "partner_code": "stephens",
                       "items_description": "1× Pepperoni", "received_at": f"{D2}T15:00:00.000Z",
                       "delivered_at": f"{D2}T15:40:00.000Z",
                       "subtotal_cents": 1799, "fee_cents": 399, "tip_cents": 300, "total_cents": 2498})
fake.seed(at.ORDERS, {"order_id": "ORD-ST-A2", "status": "closed", "partner_code": "stephens",
                       "items_description": "1× Calzone", "received_at": f"{TODAY}T12:00:00.000Z",
                       "delivered_at": f"{TODAY}T12:30:00.000Z",
                       "subtotal_cents": 1200, "fee_cents": 399, "tip_cents": 0, "total_cents": 1599})
fake.seed(at.ORDERS, {"order_id": "ORD-ST-VOID", "status": "cancelled", "partner_code": "stephens",
                       "items_description": "1× Regret", "received_at": f"{TODAY}T13:00:00.000Z",
                       "subtotal_cents": 900, "fee_cents": 399, "tip_cents": 0, "total_cents": 1299})
fake.seed(at.ORDERS, {"order_id": "ORD-ST-OTHER", "status": "delivered", "partner_code": "burgerboys",
                       "items_description": "1× Halfpounder", "received_at": f"{TODAY}T14:00:00.000Z",
                       "delivered_at": f"{TODAY}T14:30:00.000Z", "total_cents": 1500})


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    for m in (at, dp.at):
        monkeypatch.setattr(m, "list_records", fake.list_records)
    yield


def test_csv_partner_isolation_and_dollars():
    csv_out = client.get(f"{K}/export.csv", params={"partner": "stephens", "days": 7}).text
    assert "ORD-ST-A1" in csv_out and "ORD-ST-A2" in csv_out
    assert "ORD-ST-OTHER" not in csv_out          # never another partner's ledger
    assert "subtotal_usd" in csv_out and "17.99" in csv_out and "24.98" in csv_out


def test_csv_range_vs_single_day():
    single = client.get(f"{K}/export.csv").text     # today only
    assert "ORD-ST-A2" in single and "ORD-ST-A1" not in single
    ranged = client.get(f"{K}/export.csv", params={"days": 7}).text
    assert "ORD-ST-A1" in ranged


def test_statement_math_and_isolation():
    html = client.get(f"{K}/statement/stephens", params={"days": 7}).text
    assert "PARTNER STATEMENT" in html and "stephens" in html
    assert "ORD-ST-OTHER" not in html               # isolation
    # totals: delivered+closed only — 1799+1200 sub, 399+399 fee, 300 tip, 2498+1599 total
    assert "$29.99" in html and "$7.98" in html and "$3.00" in html and "$40.97" in html
    # cancelled row present but struck + excluded
    assert 'class="void"' in html and "ORD-ST-VOID" in html
    assert ">2<" in html                            # delivered count
    assert "Print / Save PDF" in html


def test_statement_bad_key_403():
    assert client.get("/api/board/wrong/statement/stephens").status_code == 403
