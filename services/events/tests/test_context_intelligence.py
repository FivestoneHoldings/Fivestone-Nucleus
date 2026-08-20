import asyncio

from fastapi.testclient import TestClient

from app import context
from app.main import app


client = TestClient(app)


def _run(coro):
    """Run async code without breaking legacy tests that still call get_event_loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


def _raw(event="Flash Flood Warning", severity="Severe"):
    return {"features": [{"id": "https://api.weather.gov/alerts/test",
                          "properties": {"event": event, "severity": severity,
                                         "urgency": "Immediate", "headline": "Test alert",
                                         "areaDesc": "Knox County", "expires": "2026-08-21T01:00:00Z"}}]}


def test_official_alert_becomes_delivery_impact(monkeypatch):
    async def fake():
        return _raw()
    monkeypatch.setattr(context, "_fetch_json", fake)
    context._CACHE.update(at=0.0, payload=None)
    result = _run(context.local_context(force=True))
    assert result["source"] == "National Weather Service"
    assert result["delivery_impact"]["level"] == "high"
    assert result["alerts"][0]["event"] == "Flash Flood Warning"


def test_non_road_alert_does_not_claim_a_delay(monkeypatch):
    async def fake():
        return _raw("Heat Advisory", "Moderate")
    monkeypatch.setattr(context, "_fetch_json", fake)
    result = _run(context.local_context(force=True))
    assert result["delivery_impact"]["level"] == "normal"


def test_provider_failure_uses_cached_data(monkeypatch):
    context._CACHE.update(at=0.0, payload=context._parse(_raw()))
    async def broken():
        raise RuntimeError("provider down")
    monkeypatch.setattr(context, "_fetch_json", broken)
    result = _run(context.local_context(force=True))
    assert result["available"] is True
    assert result["stale"] is True


def test_context_endpoint_contract(monkeypatch):
    async def fake():
        return _raw("Winter Storm Warning", "Severe")
    monkeypatch.setattr(context, "_fetch_json", fake)
    context._CACHE.update(at=0.0, payload=None)
    response = client.get("/v0/patch/context")
    assert response.status_code == 200
    assert response.json()["delivery_impact"]["level"] == "high"
    assert "weather.gov" in response.json()["source_url"]
