"""v1.9.36 — baseline browser-side security hardening.

None of this replaces server-side validation — it's a second layer that costs
nothing and closes off whole classes of attack outright: clickjacking (a hidden
iframe of the board or driver hub tricking a click), protocol downgrade,
content-type sniffing, and loading a script from a domain we never named.
"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_hsts_forces_https_for_a_year_including_subdomains():
    r = client.get("/healthz")
    hsts = r.headers.get("strict-transport-security", "")
    assert "max-age=31536000" in hsts
    assert "includeSubDomains" in hsts


def test_frame_options_blocks_clickjacking():
    """Nobody can put the board, kitchen, or driver screens in a hidden iframe
    on another site to trick a click on a real button."""
    r = client.get("/healthz")
    assert r.headers.get("x-frame-options") == "DENY"


def test_csp_denies_framing_too():
    r = client.get("/healthz")
    assert "frame-ancestors 'none'" in r.headers.get("content-security-policy", "")


def test_content_type_sniffing_is_disabled():
    r = client.get("/healthz")
    assert r.headers.get("x-content-type-options") == "nosniff"


def test_referrer_policy_does_not_leak_full_urls_cross_site():
    r = client.get("/healthz")
    assert r.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


def test_csp_only_allows_scripts_from_named_origins():
    csp = client.get("/healthz").headers.get("content-security-policy", "")
    assert "script-src 'self' 'unsafe-inline' https://unpkg.com" in csp
    # nothing wildcard, nothing unaccounted for
    assert "script-src *" not in csp


def test_csp_covers_every_external_domain_the_app_actually_loads():
    """Checked against a live grep of every https:// reference in the UI —
    Leaflet (unpkg), map tiles (OSM), Google Fonts. A CSP tighter than what the
    app actually uses breaks it silently; this pins the real requirement."""
    csp = client.get("/healthz").headers.get("content-security-policy", "")
    for origin in ["https://unpkg.com", "https://fonts.googleapis.com",
                  "https://fonts.gstatic.com", "https://nominatim.openstreetmap.org"]:
        assert origin in csp, origin


def test_headers_present_on_html_pages_not_just_api():
    r = client.get("/")
    assert r.headers.get("x-frame-options") == "DENY"
    assert "Content-Security-Policy" in r.headers or "content-security-policy" in r.headers


def test_headers_present_even_on_error_responses():
    """A 404 must be just as hardened as a 200 — an attacker often probes with
    bad requests first."""
    r = client.get("/this-route-does-not-exist")
    assert r.headers.get("x-frame-options") == "DENY"
