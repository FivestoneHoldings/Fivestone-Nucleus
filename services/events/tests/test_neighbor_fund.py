"""v1.7 — the Neighbor Fund, developed and explained.

Founder: 'better define the round up for a neighbor program and aspect of
everything. i love that but it needs to be developed more and explained a bit
better in the app.'
"""
import os
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_neighbor_fund_page_serves():
    r = client.get("/neighbor-fund")
    assert r.status_code == 200
    body = r.text
    assert "Neighbor Fund" in body
    # the three things the founder wanted made clear: what it is, how it works,
    # and the promise that GateWay takes nothing
    assert "How it works" in body
    assert "takes nothing" in body.lower() or "GateWay takes nothing" in body


def test_fund_endpoint_is_fee_accurate():
    d = client.get("/v0/community-fund").json()
    assert d["fee_cents"] == 599
    for k in ("deliveries_covered", "toward_next_cents", "recent"):
        assert k in d


def test_track_and_home_link_to_the_explainer():
    track = open(os.path.join(os.path.dirname(__file__), "..",
                              "app", "track.py")).read()
    home = open(os.path.join(os.path.dirname(__file__), "..",
                             "app", "ui", "home.html")).read()
    assert "/neighbor-fund" in track
    assert "/neighbor-fund" in home
