"""v1.9.24 — whitespace-only required fields are rejected, not silently
accepted as if they were real content. .strip() runs before the required-field
check for every field, so tabs/newlines/spaces alone never pass."""
import os, tempfile

os.environ.setdefault("DATABASE_URL", "sqlite:///" + tempfile.mktemp(suffix=".db"))
os.environ.setdefault("ADMIN_KEY", "test-key")

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app, raise_server_exceptions=False)


def test_whitespace_only_address_rejected():
    r = client.get("/v0/intake", params={
        "dropoff_address": "   ", "items_description": "1x Item"})
    assert r.status_code == 400


def test_tabs_and_newlines_as_address_rejected():
    r = client.get("/v0/intake", params={
        "dropoff_address": "\t\n  \t", "items_description": "1x Item"})
    assert r.status_code == 400


def test_whitespace_only_items_rejected():
    r = client.get("/v0/intake", params={
        "dropoff_address": "1 Real St", "items_description": "   "})
    assert r.status_code == 400


def test_both_whitespace_only_rejected():
    r = client.get("/v0/intake", params={
        "dropoff_address": " ", "items_description": "\n"})
    assert r.status_code == 400


def test_real_content_with_surrounding_whitespace_is_accepted_and_trimmed():
    """The strip() shouldn't be so aggressive it rejects legitimate input that
    just has incidental leading/trailing whitespace (e.g. from a paste)."""
    r = client.get("/v0/intake", params={
        "dropoff_address": "  123 Real St, Knoxville TN  ",
        "items_description": "  1x Burger  "})
    # not rejected for being empty — whatever happens next (Airtable
    # unavailable in this test env) is a separate concern from validation
    assert r.status_code != 400
