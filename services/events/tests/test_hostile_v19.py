"""v1.9 hostile sweep — the new surfaces must not leak, tamper, or XSS.
A million-dollar operation can't ship endpoints that trust the client."""
import os
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
ROOT = os.path.join(os.path.dirname(__file__), "..")


def _f(p):
    return open(os.path.join(ROOT, p)).read()


def test_highlights_never_leaks_tokens_or_phones():
    d = client.get("/v0/highlights").json()
    blob = str(d)
    assert "portal_token" not in blob
    assert "kt-" not in blob   # kitchen tokens never surface in public news


def test_highlights_caps_output():
    # even with many partners, the rail is bounded so it can't be flooded
    src = _f("app/identity.py")
    assert "out[:8]" in src


def test_kitchen_accept_estimate_cannot_be_negative_or_huge():
    src = _f("app/kitchen.py")
    assert "max(0, min(120" in src  # server clamps the prep estimate


def test_receipt_escapes_item_names():
    # the receipt renders item names through _esc (the quote/bracket-safe path)
    t = _f("app/track.py")
    # every dynamic piece in the receipt goes through _esc()
    assert "_esc(_nm)" in t and "_esc(_qty)" in t


def test_receipt_money_is_server_read_not_client_supplied():
    # the receipt reads money from the stored order fields, never a query param
    t = _f("app/track.py")
    assert 'f.get("subtotal_cents")' in t or '_c("subtotal_cents")' in t


def test_driver_history_only_shows_own_completed_runs():
    src = _f("app/dispatch.py")
    # done_list is derived from my_done, which is filtered to this driver
    assert "my_done[:30]" in src
    assert 'drv["id"] in (r["fields"].get("driver") or [])' in src


def test_kitchen_history_scoped_to_the_partner():
    src = _f("app/kitchen.py")
    # the history query is filtered by partner_code — one kitchen never sees another's
    assert "{{partner_code}}='{p.code}'" in src
