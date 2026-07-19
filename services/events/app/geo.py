"""Geocoding and delivery-radius checks, on OpenStreetMap.

Every kitchen gets a delivery radius (5 miles to start, adjustable per partner).
To enforce it we need coordinates for two things: the kitchen's address and the
customer's drop-off address. We use Nominatim, OSM's free geocoder — no API key,
no bill, and we already lean on OSM for the live driver map.

Three rules matter here:

1. RESPECT THE SERVICE. Nominatim's usage policy is max 1 request/second and a
   real User-Agent identifying the app. We throttle to that and cache every
   lookup permanently in our own table, so a repeat address is free forever.
   Addresses don't move; there is no reason to ask twice.

2. FAIL OPEN, NEVER FAIL SILENT. If Nominatim is down, slow, or can't parse an
   address, we ACCEPT the order and flag it as distance-unverified rather than
   turning away a paying customer. A wrongly-rejected local order is a lost
   customer and a support call; a wrongly-accepted far one is a dispatcher
   noticing a flag and making one phone call. The asymmetry is obvious.

3. THE RADIUS IS A BUSINESS SETTING, NOT A LAW OF PHYSICS. It lives on the
   partner row and the founder can change it per kitchen at any time.
"""
import hashlib
import math
import time
from typing import Optional, Tuple

import httpx
from sqlalchemy import text

from .db import SessionLocal, engine

NOMINATIM = "https://nominatim.openstreetmap.org/search"
# Nominatim asks that apps identify themselves with a contact point.
USER_AGENT = "GateWayDispatch/1.0 (Fivestone Holdings; hello@gatewaydispatch.com)"
MIN_INTERVAL_S = 1.05          # policy is 1 req/s — leave headroom
TIMEOUT_S = 3.0                # a customer is waiting; don't hang checkout on this
DEFAULT_RADIUS_MILES = 5.0
EARTH_RADIUS_MILES = 3958.7613

# Circuit breaker. If the geocoder is unreachable we must not pay the timeout on
# every single order — that would put seconds of dead wait between a customer
# hitting "place order" and anything happening. After a few consecutive
# failures we stop calling entirely for a cooldown, during which every lookup
# returns "unknown" instantly and orders sail through unverified (fail open).
_FAIL_THRESHOLD = 3
_COOLDOWN_S = 300
_consecutive_failures = 0
_circuit_open_until = 0.0

_last_call = 0.0


def _circuit_is_open() -> bool:
    return time.monotonic() < _circuit_open_until


def _note_failure():
    global _consecutive_failures, _circuit_open_until
    _consecutive_failures += 1
    if _consecutive_failures >= _FAIL_THRESHOLD:
        _circuit_open_until = time.monotonic() + _COOLDOWN_S


def _note_success():
    global _consecutive_failures, _circuit_open_until
    _consecutive_failures = 0
    _circuit_open_until = 0.0


def _norm(address: str) -> str:
    """Normalize an address for cache lookup so trivial differences in spacing
    or case don't cause a duplicate geocode request."""
    return " ".join((address or "").lower().split())


def _key(address: str) -> str:
    return hashlib.sha256(_norm(address).encode()).hexdigest()[:32]


def ensure_cache_table():
    """Created alongside the other tables; safe to call repeatedly."""
    with engine.connect() as conn:
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS geocode_cache (
                    key VARCHAR(32) PRIMARY KEY,
                    query VARCHAR(300) NOT NULL DEFAULT '',
                    lat DOUBLE PRECISION,
                    lng DOUBLE PRECISION,
                    found BOOLEAN NOT NULL DEFAULT FALSE
                )"""))
            conn.commit()
        except Exception:
            conn.rollback()


def _cache_get(address: str):
    """Returns (lat, lng) | (None, None) for a known-unresolvable address, or
    None when we've never looked this address up at all."""
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT lat, lng, found FROM geocode_cache WHERE key = :k"),
                {"k": _key(address)}).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    return (row[0], row[1]) if row[2] else (None, None)


def _cache_put(address: str, lat: Optional[float], lng: Optional[float]):
    found = lat is not None and lng is not None
    try:
        with engine.connect() as conn:
            conn.execute(text("DELETE FROM geocode_cache WHERE key = :k"),
                         {"k": _key(address)})
            conn.execute(text("""INSERT INTO geocode_cache (key, query, lat, lng, found)
                                 VALUES (:k, :q, :lat, :lng, :f)"""),
                         {"k": _key(address), "q": (address or "")[:300],
                          "lat": lat, "lng": lng, "f": found})
            conn.commit()
    except Exception:
        pass  # a cache miss is survivable; never break an order over it


def geocode(address: str) -> Tuple[Optional[float], Optional[float]]:
    """Address -> (lat, lng), or (None, None) if it can't be resolved.

    Cached permanently. Never raises: callers treat (None, None) as 'unknown'
    and fall back to accepting the order."""
    if not address or not address.strip():
        return (None, None)
    cached = _cache_get(address)
    if cached is not None:
        return cached
    if _circuit_is_open():
        return (None, None)      # geocoder is down; fail open, instantly

    global _last_call
    wait = MIN_INTERVAL_S - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()

    try:
        r = httpx.get(NOMINATIM,
                      params={"q": address, "format": "json", "limit": 1,
                              "countrycodes": "us"},
                      headers={"User-Agent": USER_AGENT},
                      timeout=TIMEOUT_S)
        if r.status_code == 200:
            _note_success()
            data = r.json()
            if data:
                lat, lng = float(data[0]["lat"]), float(data[0]["lon"])
                _cache_put(address, lat, lng)
                return (lat, lng)
            # Resolved cleanly to "no such place" — cache the negative so we
            # don't re-ask on every retry of a typo'd address.
            _cache_put(address, None, None)
        else:
            _note_failure()
    except Exception:
        # Network/timeout/parse trouble: do NOT cache. The address may be fine
        # and the service merely unreachable this minute.
        _note_failure()
    return (None, None)


def miles_between(lat1, lng1, lat2, lng2) -> Optional[float]:
    """Great-circle distance in miles. Straight-line, not driving distance —
    honest enough for a service-area check, and it never over-rejects (real
    driving distance is always >= this, so the radius is generous by design)."""
    if None in (lat1, lng1, lat2, lng2):
        return None
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return EARTH_RADIUS_MILES * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def partner_coords(partner) -> Tuple[Optional[float], Optional[float]]:
    """A kitchen's coordinates, geocoded from its address once and then stored
    on the partner row so we never look it up again."""
    lat = getattr(partner, "lat", None)
    lng = getattr(partner, "lng", None)
    if lat is not None and lng is not None:
        return (lat, lng)
    lat, lng = geocode(partner.address)
    if lat is not None:
        db = SessionLocal()
        try:
            from .models import Partner as _P
            row = db.get(_P, partner.code)
            if row is not None:
                row.lat, row.lng = lat, lng
                db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
    return (lat, lng)


def check_delivery_range(partner, dropoff_address: str) -> dict:
    """Is this drop-off inside the kitchen's delivery radius?

    Returns {"allowed": bool, "miles": float|None, "radius": float,
             "verified": bool}. `verified` is False when we couldn't geocode
    one side — in that case `allowed` is True (fail open) and dispatch sees the
    order flagged rather than the customer seeing a refusal."""
    # `0 or DEFAULT` would silently reinstate the default — but 0 is the
    # founder's way of switching the check OFF for a kitchen, so None (never
    # set) and 0 (deliberately disabled) must be told apart.
    raw = getattr(partner, "delivery_radius_miles", None)
    radius = DEFAULT_RADIUS_MILES if raw is None else float(raw)
    if radius <= 0:                     # 0 = radius check disabled for this kitchen
        return {"allowed": True, "miles": None, "radius": radius, "verified": False}

    plat, plng = partner_coords(partner)
    dlat, dlng = geocode(dropoff_address)
    miles = miles_between(plat, plng, dlat, dlng)
    if miles is None:
        return {"allowed": True, "miles": None, "radius": radius, "verified": False}
    return {"allowed": miles <= radius, "miles": round(miles, 1),
            "radius": radius, "verified": True}
