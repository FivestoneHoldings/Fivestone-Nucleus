"""Community impact: public, no-PII, cached, drives the home banner."""
import datetime as _dt
import pytest
from fastapi.testclient import TestClient
import app.airtable_client as at
import app.dispatch as dp
from app.main import app
from tests.fake_airtable import FakeAirtable

client = TestClient(app)
fake = FakeAirtable()
TODAY = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")

for i,(st,partner,sub) in enumerate([("delivered","stephens",1799),("closed","stephens",1200),
                                      ("delivered","burgerboys",900),("received","friendsbbq",2000)]):
    fake.seed(at.ORDERS, {"order_id": f"ORD-LI{i}", "status": st, "partner_code": partner,
                          "subtotal_cents": sub, "received_at": f"{TODAY}T12:00:00.000Z"})


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    monkeypatch.setattr(at, "list_records", fake.list_records)
    monkeypatch.setattr(dp.at, "list_records", fake.list_records)
    dp._TTL_CACHE.clear()
    yield


def test_local_impact_counts_delivered_only_no_pii():
    d = client.get("/v0/local-impact").json()
    assert d["delivered"] == 3                 # received excluded
    assert d["food_cents"] == 1799 + 1200 + 900
    assert d["kitchens"] == 2                   # stephens + burgerboys
    # no personal fields leak
    assert "customer" not in str(d) and "address" not in str(d)


def test_local_impact_cached():
    client.get("/v0/local-impact")
    calls = {"n": 0}
    async def counting(*a, **k):
        calls["n"] += 1
        return []
    import app.dispatch as dp2
    dp2.at.list_records = counting
    client.get("/v0/local-impact")               # served from cache
    assert calls["n"] == 0


def test_home_shows_local_banner_hook():
    assert "localImpact" in client.get("/").text
