"""conftest imports run before every test module — environment MUST be set here,
before the app (and its DB engine) is ever imported."""
import os
import tempfile

os.environ.setdefault("DATABASE_URL", "sqlite:///" + tempfile.mktemp(suffix=".db"))
os.environ.setdefault("ADMIN_KEY", "test-key")
os.environ.setdefault("AIRTABLE_PAT", "fake-pat")

import pytest
import app.dispatch as dp


@pytest.fixture(autouse=True)
def _clear_ttl_cache():
    dp._TTL_CACHE.clear()
    yield
    dp._TTL_CACHE.clear()
