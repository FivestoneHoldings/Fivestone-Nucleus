import pytest
import app.dispatch as dp


@pytest.fixture(autouse=True)
def _clear_ttl_cache():
    dp._TTL_CACHE.clear()
    yield
    dp._TTL_CACHE.clear()
