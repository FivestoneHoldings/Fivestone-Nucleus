"""v1.7 — speed & fluidity. The founder saw a system.slow_request on the board.

Board endpoints were firing independent Airtable reads sequentially; now they
run concurrently (asyncio.gather) and cache the rarely-changing driver list.
"""
import os
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_board_endpoints_use_concurrency():
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "app", "dispatch.py")).read()
    # both hot board reads should now gather independent Airtable calls
    assert "asyncio.gather" in src
    assert src.count("asyncio.gather") >= 2


def test_metrics_surfaces_slow_requests():
    r = client.get("/metrics")
    assert r.status_code == 200
    d = r.json()
    assert "slow_requests_24h" in d
    assert "slowest_paths" in d
    assert isinstance(d["slowest_paths"], list)
