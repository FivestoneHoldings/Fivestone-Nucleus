"""Courier fetch receives JSON while browser form checkout receives HTML.

Both checkout surfaces now POST so customer PII is not placed in URLs. The
real browser form asks for HTML by normal navigation; courier explicitly asks
for JSON so it can show its inline confirmation card.
"""
import os, tempfile

os.environ.setdefault("DATABASE_URL", "sqlite:///" + tempfile.mktemp(suffix=".db"))
os.environ.setdefault("ADMIN_KEY", "test-key")

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app, raise_server_exceptions=False)
UI = os.path.join(os.path.dirname(__file__), "..", "app", "ui")


def test_get_with_explicit_json_accept_returns_json_not_html():
    """This is exactly what courier.html's fetch() call sends."""
    r = client.get("/v0/intake", params={
        "dropoff_address": "1 Courier St", "items_description": "[COURIER] pkg"
    }, headers={"Accept": "application/json"})
    assert "application/json" in r.headers["content-type"]


def test_get_with_real_browser_accept_header_still_returns_html():
    """The real order-form.html <form> navigation must be untouched."""
    r = client.get("/v0/intake", params={
        "dropoff_address": "1 Food St", "items_description": "1x Burger"
    }, headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})
    assert "text/html" in r.headers["content-type"]


def test_get_with_no_accept_header_defaults_to_html():
    """Backward compatible: any other caller with no explicit preference keeps
    the original method-based behavior."""
    r = client.get("/v0/intake", params={
        "dropoff_address": "1 Plain St", "items_description": "1x Item"})
    assert "text/html" in r.headers["content-type"]


def test_courier_html_explicitly_requests_json():
    src = open(os.path.join(UI, "courier.html")).read()
    assert "'Accept': 'application/json'" in src
    assert "method: 'POST'" in src
