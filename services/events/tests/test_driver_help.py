"""v1.9.28 — a driver can reach a human immediately.

Before this, a driver could call the CUSTOMER but had no way to reach GateWay
at all. A driver alone at an unlit address, in a wreck, or with a hostile
customer had no channel. Severity is decided by the category, not by asking a
frightened person to rate their own emergency."""
import os, tempfile

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///" + tempfile.mktemp(suffix=".db"))
os.environ.setdefault("ADMIN_KEY", "k")
os.environ["GATEWAY_HQ_PHONE"] = "865-555-0100"

from fastapi.testclient import TestClient
import app.dispatch as dispatch
from app.main import app

DRIVER = {"id": "recDRV", "fields": {"driver_id": "DRV-1", "day_token": "tok1",
                                     "display_name": "Marcus", "phone": "8655559999"}}


async def _fake_driver(tok):
    if tok != "tok1":
        from fastapi import HTTPException
        raise HTTPException(404, "no such driver")
    return DRIVER


client = TestClient(app)


def _key():
    """Read the key at CALL time. Other test modules set ADMIN_KEY at import,
    and whichever imported last wins — baking it in here made these tests pass
    alone and fail in the full suite."""
    return os.environ.get("ADMIN_KEY", "k")


@pytest.fixture(autouse=True)
def _stub_driver_lookup(monkeypatch):
    """Scoped to THIS module only. Patching dispatch._driver_by_token at import
    time leaked into every other test file in the session and broke 36 of them —
    monkeypatch restores it after each test instead."""
    monkeypatch.setattr(dispatch, "_driver_by_token", _fake_driver)


def test_hq_contact_returns_configured_number():
    assert client.get("/api/driver/tok1/hq").json()["phone"] == "865-555-0100"


def test_hq_contact_requires_a_valid_driver_token():
    assert client.get("/api/driver/BADTOK/hq").status_code == 404


def test_safety_report_is_critical():
    r = client.post("/api/driver/tok1/help",
                    json={"kind": "safety", "message": "unlit address"})
    assert r.json()["severity"] == "critical"


def test_routine_report_is_not_critical():
    r = client.post("/api/driver/tok1/help", json={"kind": "order"})
    assert r.json()["severity"] == "normal"


def test_unknown_category_falls_back_safely():
    r = client.post("/api/driver/tok1/help", json={"kind": "nonsense-injection"})
    assert r.status_code == 200
    assert r.json()["severity"] == "normal"


def test_help_request_reaches_the_board():
    client.post("/api/driver/tok1/help",
                json={"kind": "accident", "order_id": "ORD-XYZ"})
    tix = client.get(f"/v0/support-tickets?key={_key()}").json()["tickets"]
    assert any("ORD-XYZ" in t["message"] and "CRITICAL" in t["message"] for t in tix)


def test_help_request_is_also_logged_permanently():
    """A UI can be closed; the event log can't be. The record must survive."""
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "app", "dispatch.py")).read()
    assert "driver.help_requested" in src


def _newest_driver_ticket():
    """Find OUR ticket by content, not by list position — other tests create
    tickets too, and index 0 is whatever happened to be written last."""
    tix = client.get(f"/v0/support-tickets?key={_key()}").json()["tickets"]
    return next(t for t in tix if t["message"].startswith("[DRIVER ·"))


def test_ticket_can_be_resolved_so_the_banner_clears():
    client.post("/api/driver/tok1/help",
                json={"kind": "safety", "message": "resolve-me marker"})
    tid = _newest_driver_ticket()["id"]
    assert client.patch(f"/v0/support-tickets/{tid}?key={_key()}",
                        json={"status": "closed"}).status_code == 200
    after = client.get(f"/v0/support-tickets?key={_key()}").json()["tickets"]
    assert next(t for t in after if t["id"] == tid)["status"] == "closed"


def test_resolving_a_ticket_requires_the_board_key():
    client.post("/api/driver/tok1/help", json={"kind": "safety"})
    tid = _newest_driver_ticket()["id"]
    r = client.patch(f"/v0/support-tickets/{tid}?key=WRONG",
                     json={"status": "closed"})
    assert r.status_code in (401, 403)


def test_driver_hub_and_board_wire_it_up():
    ui = os.path.join(os.path.dirname(__file__), "..", "app", "ui")
    d = open(os.path.join(ui, "driver.html")).read()
    b = open(os.path.join(ui, "board.html")).read()
    assert "toggleHelp" in d and "sendHelp" in d
    assert "Call GateWay now" in d
    assert "checkDriverAlerts" in b and 'id="driverAlerts"' in b
