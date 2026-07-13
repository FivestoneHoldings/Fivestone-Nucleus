"""Custom/percentage tipping, per-item requests, menu search, backend tuning."""
import pytest
from fastapi.testclient import TestClient
import app.airtable_client as at
from app.main import app

client = TestClient(app)


def test_tip_block_has_percentages_and_custom():
    html = client.get("/order?partner=stephens").text
    assert "tipWrap" in html and "pickPct" in html and "pickCustom" in html
    assert "TIP_PCTS = [15, 18, 20, 25]" in html
    assert "100% of the tip is theirs" in html
    assert "add more after delivery" in html


def test_menu_search_and_item_notes_present():
    html = client.get("/order?partner=stephens").text
    assert "msearch" in html and "filterMenu" in html
    assert "itemNote" in html and "special request" in html
    assert "straight to the cook" in html


def test_metrics_endpoint_no_pii():
    client.get("/healthz")
    d = client.get("/metrics").json()
    for k in ("requests", "avg_ms", "max_ms", "errors_5xx", "version"):
        assert k in d
    assert d["requests"] >= 1
    body = str(d)
    assert "address" not in body and "phone" not in body


def test_server_timing_header():
    r = client.get("/healthz")
    assert "Server-Timing" in r.headers
    assert r.headers["Server-Timing"].startswith("app;dur=")


def test_airtable_client_pools_connections():
    at._CLIENT = None
    c1 = at._client()
    c2 = at._client()
    assert c1 is c2                      # reused across calls, not rebuilt per request
    assert c1.timeout.connect == 5.0     # bounded connect
    assert c1.timeout.read == 12.0       # bounded read
    at._CLIENT = None
