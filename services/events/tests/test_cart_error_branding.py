"""v1.9.23 — a stale cart item (86'd mid-order) must show the customer a real,
branded page — not a raw JSON blob.

Root cause: the global exception handler in main.py only brands 404s, and
treats every /v0/ path as never wanting HTML regardless of the browser's Accept
header. The real order form submits via GET (so a customer never even reaches
the multipart/form-data code path — that's a separate, unreached branch), and
an item going unavailable between browsing and submitting raised an
HTTPException that used to propagate straight past intake()'s own branding
logic into that global handler, surfacing as {"detail":"..."} in the customer's
browser mid-checkout.
"""
import os, tempfile

os.environ.setdefault("DATABASE_URL", "sqlite:///" + tempfile.mktemp(suffix=".db"))
os.environ.setdefault("ADMIN_KEY", "test-key")

from fastapi.testclient import TestClient
from app.main import app
from app import menu, growth

menu.seed_menus()
growth.migrate_brand_columns()
growth.seed_brands_and_demos()
client = TestClient(app, raise_server_exceptions=False)


def test_real_browser_form_submission_gets_branded_html_on_unavailable_item():
    r = client.get("/v0/intake", params={
        "dropoff_address": "1 Test St", "items_description": "1x Fake Item",
        "partner": "asiacafe", "cart_json": '[{"item_id":"nonexistent-item-id","qty":1}]'
    }, headers={"Accept": "text/html,application/xhtml+xml"})
    assert r.status_code == 422
    assert "text/html" in r.headers["content-type"]
    assert "GateWay" in r.text
    assert "no longer available" in r.text


def test_json_api_caller_still_gets_clean_json_on_unavailable_item():
    r = client.post("/v0/intake", json={
        "dropoff_address": "1 Test St", "items_description": "1x Fake Item",
        "partner": "asiacafe", "cart_json": '[{"item_id":"nonexistent-item-id","qty":1}]'
    })
    assert r.status_code == 422
    assert "application/json" in r.headers["content-type"]
    body = r.json()
    assert body["received"] is False
    assert body["error"] == "cart_item_invalid"


def test_wrong_kitchen_item_also_gets_branded_html():
    """The cross-kitchen cart-tamper guard goes through the same fix."""
    r = client.get("/v0/intake", params={
        "dropoff_address": "1 Test St", "items_description": "1x Item",
        "partner": "stephens",
        "cart_json": '[{"item_id":"nonexistent-item-id","qty":1}]',
    }, headers={"Accept": "text/html"})
    assert r.status_code == 422
    assert "text/html" in r.headers["content-type"]
    assert "GateWay" in r.text
