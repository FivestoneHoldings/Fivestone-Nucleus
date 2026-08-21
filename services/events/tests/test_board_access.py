"""v1.9.37 — per-person board access instead of one shared key.

Before this, one ADMIN_KEY protected all 46 board endpoints, shared by
whoever needed in. Fine for a founder alone; wrong the moment a second person
needs access, because there's no way to revoke ONE person without rotating the
key and re-issuing it to everyone else — disruptive enough that in practice it
never happens, so a leaked screenshot or an ex-employee's access stays valid
forever. Now each person gets their own named, independently-revocable key.
"""
import os, tempfile

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///" + tempfile.mktemp(suffix=".db"))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _founder_key(monkeypatch):
    """Scoped to THIS module only. Other test files set ADMIN_KEY too, and
    whichever ran last in the shared process wins — a hardcoded value here
    passed in isolation and failed in the full suite for exactly that reason."""
    monkeypatch.setenv("ADMIN_KEY", "founder-master-key")


def test_founder_master_key_still_works():
    """Backward compatible — existing ADMIN_KEY-based access must not break."""
    assert client.get("/api/board/founder-master-key/feedback").status_code == 200


def test_clean_board_entrypoint_uses_header_session_not_url_credentials():
    page = client.get("/board")
    assert page.status_code == 200
    assert "Open Command" in page.text
    assert "/api/board/session" in page.text
    assert "/api/board/login" in page.text
    assert "sessionStorage" not in page.text
    assert "location.pathname.split('/').filter(Boolean).pop()" not in page.text
    assert page.headers["cache-control"] == "no-store"


def test_header_session_authorizes_without_putting_key_in_route():
    denied = client.get("/api/board/session/readiness")
    assert denied.status_code == 403
    allowed = client.get("/api/board/session/readiness",
                         headers={"X-Board-Key": "founder-master-key"})
    assert allowed.status_code == 200
    assert "X-Board-Key" not in allowed.request.url.path


def test_login_uses_httponly_cookie_and_logout_clears_it():
    login = client.post("/api/board/login",
                        json={"key": "founder-master-key", "remember": True})
    assert login.status_code == 200
    cookie = login.headers["set-cookie"]
    assert "gw_board_session=" in cookie and "HttpOnly" in cookie
    assert "SameSite=strict" in cookie and "Max-Age=604800" in cookie
    assert client.get("/api/board/session/readiness").status_code == 200
    logout = client.post("/api/board/logout")
    assert logout.status_code == 200
    assert "gw_board_session=" in logout.headers["set-cookie"]
    assert client.get("/api/board/session/readiness").status_code == 403


def test_header_cannot_rescue_an_unrelated_bad_path_key():
    response = client.get("/api/board/not-the-key/readiness",
                          headers={"X-Board-Key": "founder-master-key"})
    assert response.status_code == 403


def test_legacy_board_link_scrubs_address_bar_before_api_calls():
    bridge = client.get("/board/founder-master-key", follow_redirects=False)
    assert bridge.status_code == 303
    assert bridge.headers["location"] == "/board"
    assert "HttpOnly" in bridge.headers["set-cookie"]
    page = client.get("/board")
    assert "showReadiness" in page.text


def test_unknown_key_is_rejected():
    assert client.get("/api/board/totally-made-up/feedback").status_code == 403


def test_founder_can_mint_a_named_key():
    r = client.post("/api/board/founder-master-key/team-access",
                    json={"name": "Jasmine (ops)"})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Jasmine (ops)"
    assert body["key"].startswith("gwb-")


def test_minted_key_actually_works_on_board_endpoints():
    key = client.post("/api/board/founder-master-key/team-access",
                      json={"name": "Test User"}).json()["key"]
    assert client.get(f"/api/board/{key}/feedback").status_code == 200


def test_only_the_founders_own_key_can_mint_more_keys():
    """The privilege boundary that matters: a team member's own valid key must
    not be enough to grant themselves or others more access."""
    team_key = client.post("/api/board/founder-master-key/team-access",
                           json={"name": "Regular User"}).json()["key"]
    r = client.post(f"/api/board/{team_key}/team-access", json={"name": "Escalation"})
    assert r.status_code == 403


def test_revoking_one_key_does_not_touch_another():
    """The entire point of the feature."""
    a = client.post("/api/board/founder-master-key/team-access",
                    json={"name": "Person A"}).json()
    b = client.post("/api/board/founder-master-key/team-access",
                    json={"name": "Person B"}).json()
    client.delete(f"/api/board/founder-master-key/team-access/{a['id']}")
    assert client.get(f"/api/board/{a['key']}/feedback").status_code == 403
    assert client.get(f"/api/board/{b['key']}/feedback").status_code == 200


def test_revoking_a_team_key_never_touches_the_founders_own():
    key = client.post("/api/board/founder-master-key/team-access",
                      json={"name": "Someone"}).json()
    client.delete(f"/api/board/founder-master-key/team-access/{key['id']}")
    assert client.get("/api/board/founder-master-key/feedback").status_code == 200


def test_the_key_list_never_exposes_the_raw_key():
    client.post("/api/board/founder-master-key/team-access", json={"name": "Privacy Check"})
    listing = client.get("/api/board/founder-master-key/team-access").json()
    blob = str(listing)
    assert "gwb-" not in blob        # no raw key anywhere in the response
    assert any(row["name"] == "Privacy Check" for row in listing["access"])


def test_keys_are_stored_hashed_not_plaintext():
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "app", "boardauth.py")).read()
    assert "hashlib.sha256" in src
    assert "key_hash" in src


def test_an_empty_name_is_refused():
    r = client.post("/api/board/founder-master-key/team-access", json={"name": "  "})
    assert r.status_code == 400


def test_revoking_an_unknown_id_is_a_clean_404():
    r = client.delete("/api/board/founder-master-key/team-access/does-not-exist")
    assert r.status_code == 404


def test_every_module_now_shares_one_auth_implementation():
    """The five duplicated _check_key bodies were the actual bug risk — a fix
    in one could silently miss the other four. All must delegate now."""
    import os as _os
    root = _os.path.join(_os.path.dirname(__file__), "..", "app")
    for name in ("dispatch.py", "growth.py", "identity.py", "menu.py", "options.py"):
        src = open(_os.path.join(root, name)).read()
        assert "boardauth.check_key(key)" in src, name
