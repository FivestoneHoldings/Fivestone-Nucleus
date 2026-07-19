"""v1.9.26 — per-kitchen delivery radius on OpenStreetMap.

Design rules under test:
  * distance math is real (haversine, sanity-checked against known TN cities)
  * 0 miles means DISABLED, not "fall back to the default" (falsy-zero trap)
  * unresolvable address => order is ACCEPTED and flagged, never refused
  * a dead geocoder trips a circuit breaker instead of adding a timeout to
    every single order
"""
import os, tempfile

os.environ.setdefault("DATABASE_URL", "sqlite:///" + tempfile.mktemp(suffix=".db"))
os.environ.setdefault("ADMIN_KEY", "test-key")

import app.geo as geo
from app.geo import miles_between, check_delivery_range, DEFAULT_RADIUS_MILES

ASIA = (36.0270, -83.9910)        # 1708 Callahan Dr, Knoxville
MARYVILLE = (35.7565, -83.9705)   # ~19mi south
NASHVILLE = (36.1627, -86.7816)   # ~160mi west


class _P:
    code = "asiacafe"; display_name = "Asia Cafe"; address = "1708 Callahan Dr"
    delivery_radius_miles = 5.0; lat = ASIA[0]; lng = ASIA[1]


def _partner(**kw):
    return type("P", (_P,), kw)()


def test_haversine_matches_known_distances():
    # straight-line is always shorter than driving; these bracket the real values
    knox_to_maryville = miles_between(*ASIA, *MARYVILLE)
    assert 15 < knox_to_maryville < 22
    knox_to_nashville = miles_between(*ASIA, *NASHVILLE)
    assert 140 < knox_to_nashville < 180


def test_missing_coordinates_return_none_not_zero():
    assert miles_between(None, None, 1, 2) is None
    assert miles_between(1, 2, None, None) is None


def test_address_in_range_is_allowed(monkeypatch):
    monkeypatch.setattr(geo, "geocode", lambda a: (36.0300, -83.9950))
    v = check_delivery_range(_partner(), "just up the road")
    assert v["allowed"] is True and v["verified"] is True


def test_address_out_of_range_is_refused(monkeypatch):
    monkeypatch.setattr(geo, "geocode", lambda a: MARYVILLE)
    v = check_delivery_range(_partner(), "far away")
    assert v["allowed"] is False
    assert v["verified"] is True
    assert v["miles"] > 5


def test_zero_radius_disables_the_check_entirely(monkeypatch):
    """0 must mean OFF. `0 or DEFAULT` would silently reinstate 5 miles."""
    monkeypatch.setattr(geo, "geocode", lambda a: NASHVILLE)
    v = check_delivery_range(_partner(delivery_radius_miles=0.0), "nashville")
    assert v["allowed"] is True


def test_unset_radius_falls_back_to_the_default(monkeypatch):
    monkeypatch.setattr(geo, "geocode", lambda a: MARYVILLE)
    v = check_delivery_range(_partner(delivery_radius_miles=None), "far")
    assert v["radius"] == DEFAULT_RADIUS_MILES
    assert v["allowed"] is False


def test_wider_radius_admits_a_further_address(monkeypatch):
    monkeypatch.setattr(geo, "geocode", lambda a: MARYVILLE)
    v = check_delivery_range(_partner(delivery_radius_miles=25.0), "far")
    assert v["allowed"] is True


def test_ungeocodable_address_fails_open(monkeypatch):
    """A third-party outage must never turn away a paying customer."""
    monkeypatch.setattr(geo, "geocode", lambda a: (None, None))
    v = check_delivery_range(_partner(), "gibberish")
    assert v["allowed"] is True
    assert v["verified"] is False


def test_circuit_breaker_stops_hammering_a_dead_geocoder():
    geo._consecutive_failures = 0
    geo._circuit_open_until = 0.0
    for _ in range(geo._FAIL_THRESHOLD):
        geo._note_failure()
    assert geo._circuit_is_open()
    # while open, lookups return instantly without touching the network
    assert geo.geocode("anything at all") == (None, None)
    geo._note_success()
    assert not geo._circuit_is_open()


def test_intake_flags_unverified_distance_for_dispatch():
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "app", "intake.py")).read()
    assert "Distance unverified" in src
    assert "out_of_delivery_area" in src
