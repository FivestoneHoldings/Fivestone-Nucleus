"""v1.8 — honest ETA window on the tracking page."""
import os
from datetime import datetime, timezone, timedelta
from app.track import _eta_window


def test_no_eta_once_delivered():
    assert _eta_window({}, "delivered") is None
    assert _eta_window({}, "closed") is None


def test_eta_present_while_active():
    now = datetime.now(timezone.utc).isoformat()
    e = _eta_window({"received_at": now}, "received")
    assert e is not None and "iso" in e


def test_eta_rebases_to_freshest_stamp():
    old = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    fresh = datetime.now(timezone.utc).isoformat()
    # in_transit should anchor off in_transit_at (fresh), giving a near window
    e = _eta_window({"received_at": old, "in_transit_at": fresh}, "in_transit")
    assert e is not None
    # ~12 min remaining +/- window, definitely under 30
    assert e.get("mins", 99) <= 20


def test_eta_window_is_a_range_not_false_precision():
    now = datetime.now(timezone.utc).isoformat()
    e = _eta_window({"received_at": now}, "confirmed")
    # either a clock range with an en dash, or the graceful "any minute"
    assert "\u2013" in e["text"] or "minute" in e["text"].lower()


def test_track_page_renders_eta_and_localizes():
    t = open(os.path.join(os.path.dirname(__file__), "..",
                          "app", "track.py")).read()
    assert 'class="eta"' in t
    assert "paintEta" in t  # browser localizes the ISO to the viewer tz


def test_track_page_has_share_button():
    t = open(os.path.join(os.path.dirname(__file__), "..",
                          "app", "track.py")).read()
    assert "shareTrack" in t
    assert "navigator.share" in t
    assert "navigator.clipboard.writeText" in t  # fallback for browsers w/o Web Share
