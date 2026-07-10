"""Guides serve, teach the right things, and leak no secrets."""
import os
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_driver_guide():
    r = client.get("/guide/driver")
    assert r.status_code == 200
    for phrase in ("ON SHIFT", "Picked Up", "Delivered", "Tips are 100% yours"):
        assert phrase in r.text


def test_kitchen_guide():
    r = client.get("/guide/kitchen")
    assert r.status_code == 200
    for phrase in ("READY FOR PICKUP", "Pause new orders"):
        assert phrase in r.text


def test_guides_leak_no_secrets():
    admin = os.environ.get("ADMIN_KEY", "test-key")
    for path in ("/guide/driver", "/guide/kitchen"):
        t = client.get(path).text
        assert admin not in t
        assert "gw-mml" not in t and "kt-" not in t
