"""conftest imports run before every test module — environment MUST be set here,
before the app (and its DB engine) is ever imported."""
import os
import tempfile
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "sqlite:///" + tempfile.mktemp(suffix=".db"))
os.environ.setdefault("ADMIN_KEY", "test-key")
os.environ.setdefault("AIRTABLE_PAT", "fake-pat")
os.environ.setdefault("CUSTOMER_PROFILES_ENABLED", "true")
os.environ.setdefault("GATEWAY_HQ_PHONE", "865-555-0100")
os.environ.setdefault("GATEWAY_BACKUP_VERIFIED_AT", datetime.now(timezone.utc).isoformat())

import pytest
import app.dispatch as dp
import app.geo as geo


@pytest.fixture(autouse=True)
def _clear_ttl_cache():
    dp._TTL_CACHE.clear()
    yield
    dp._TTL_CACHE.clear()


@pytest.fixture(autouse=True)
def _no_live_geocoder(monkeypatch):
    """Unit tests must not change behavior based on what an Internet geocoder
    happens to resolve for synthetic addresses such as ``1 Test St``."""
    monkeypatch.setattr(geo, "check_delivery_range", lambda partner, address: {
        "allowed": True, "miles": None,
        "radius": float(getattr(partner, "delivery_radius_miles", 0) or 0),
        "verified": False,
    })
