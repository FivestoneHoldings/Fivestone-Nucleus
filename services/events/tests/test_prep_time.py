"""v1.8 — honest 'usually ready in ~X min' badge, derived from real kitchen
telemetry only. Never a guess, never shown without a real sample."""
import os, json, tempfile
os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")

from app.db import SessionLocal, engine, Base
from app import models
Base.metadata.create_all(engine)
from app.models import Event
from app.identity import _prep_minutes_by_partner


def _log(partner, mins):
    db = SessionLocal()
    db.add(Event(event_type="order.kitchen_ready", entity_ref="ORD-X",
                 tenant="gateway", actor="kitchen:test",
                 payload=json.dumps({"partner": partner, "prep_minutes": mins})))
    db.commit()
    db.close()


def test_no_badge_without_a_real_sample():
    # only 2 data points — below the 3-sample floor, must not appear
    _log("teststore1", 20)
    _log("teststore1", 22)
    out = _prep_minutes_by_partner()
    assert "teststore1" not in out


def test_median_used_not_mean_so_outliers_dont_skew():
    for m in (18, 19, 20, 21, 90):  # one chaotic ticket at the end
        _log("teststore2", m)
    out = _prep_minutes_by_partner()
    assert out["teststore2"] == 20  # median of [18,19,20,21,90], not the mean (33.6)


def test_home_and_featured_tiles_show_prep_badge():
    home = open(os.path.join(os.path.dirname(__file__), "..",
                             "app", "ui", "home.html")).read()
    assert "p.prep_minutes" in home
    assert "min\u2058" in home or "min`" in home or "~${p.prep_minutes} min" in home


def test_board_partners_endpoint_exposes_prep_minutes():
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "app", "identity.py")).read()
    assert '"prep_minutes": prep.get(p.code)' in src
    assert src.count('"prep_minutes": prep.get(p.code)') == 2  # public + board


def test_board_ui_shows_prep_time_to_founder():
    b = open(os.path.join(os.path.dirname(__file__), "..",
                          "app", "ui", "board.html")).read()
    assert "Median prep time" in b
