"""v1.9.34 — customer complaints reach someone who can act on them.

Feedback was going to the kitchen and nobody else. Two problems: a complaint
about DELIVERY (late, wrong address, rude driver) landed on a kitchen that
can't fix it and shouldn't be judged for it, and GateWay never learned it
happened. An unhappy customer whose complaint vanishes into a dashboard is a
customer lost without anyone knowing why.
"""
import json, os, tempfile

os.environ.setdefault("DATABASE_URL", "sqlite:///" + tempfile.mktemp(suffix=".db"))
os.environ.setdefault("ADMIN_KEY", "k")

from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app.models import Event
from app import menu, growth

menu.seed_menus(); growth.migrate_brand_columns(); growth.seed_brands_and_demos()
client = TestClient(app, raise_server_exceptions=False)


def _key():
    return os.environ.get("ADMIN_KEY", "k")


def _seed(oid, good, note="", partner="asiacafe"):
    db = SessionLocal()
    db.add(Event(event_type="order.feedback", entity_ref=oid, tenant="gateway",
                 actor="customer",
                 payload=json.dumps({"good": good, "note": note, "partner": partner})))
    db.commit(); db.close()


def test_board_can_see_customer_feedback():
    _seed("ORD-FB01", True, "Driver was lovely")
    d = client.get(f"/api/board/{_key()}/feedback").json()
    assert any(f["order_id"] == "ORD-FB01" for f in d["feedback"])


def test_unhappy_and_unresolved_comes_first():
    """That's the queue; happy feedback is context, not a task."""
    _seed("ORD-FB02", True, "great")
    _seed("ORD-FB03", False, "cold food")
    d = client.get(f"/api/board/{_key()}/feedback").json()
    assert d["feedback"][0]["good"] is False


def test_unresolved_count_reflects_real_work_outstanding():
    _seed("ORD-FB04", False, "missing item")
    before = client.get(f"/api/board/{_key()}/feedback").json()["unresolved_unhappy"]
    client.post(f"/api/board/{_key()}/feedback/ORD-FB04/handled")
    after = client.get(f"/api/board/{_key()}/feedback").json()["unresolved_unhappy"]
    assert after == before - 1


def test_handled_feedback_is_marked_not_deleted():
    """The record has to survive — 'we made it right' is history worth keeping."""
    _seed("ORD-FB05", False, "late")
    client.post(f"/api/board/{_key()}/feedback/ORD-FB05/handled")
    d = client.get(f"/api/board/{_key()}/feedback").json()
    row = next(f for f in d["feedback"] if f["order_id"] == "ORD-FB05")
    assert row["handled"] is True
    assert row["note"] == "late"


def test_feedback_requires_the_board_key():
    assert client.get("/api/board/WRONG-KEY/feedback").status_code in (401, 403)
    assert client.post("/api/board/WRONG-KEY/feedback/ORD-X/handled").status_code in (401, 403)


def test_board_ui_surfaces_it():
    ui = open(os.path.join(os.path.dirname(__file__), "..",
                           "app", "ui", "board.html")).read()
    assert "toggleFeedback" in ui and "markFeedbackHandled" in ui
    assert "Need you" in ui        # the count that means "act today"
