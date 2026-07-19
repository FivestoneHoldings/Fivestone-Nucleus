"""v1.9.25 — the Kitchen app has its own front door.

Merchants had to go through the command board (an internal tool) to reach their
own screen. /merchant is a standalone sign-in that verifies the access code,
remembers the device, and lands them straight on live tickets next time."""
import os, tempfile

os.environ.setdefault("DATABASE_URL", "sqlite:///" + tempfile.mktemp(suffix=".db"))
os.environ.setdefault("ADMIN_KEY", "test-key")

from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app.models import Partner
from app import menu, growth

menu.seed_menus(); growth.migrate_brand_columns(); growth.seed_brands_and_demos()
client = TestClient(app)

_db = SessionLocal()
TOKEN = _db.query(Partner).filter(Partner.code == "asiacafe").first().portal_token
_db.close()


def test_merchant_signin_page_serves():
    r = client.get("/merchant")
    assert r.status_code == 200
    assert "Kitchen access code" in r.text


def test_verify_endpoint_accepts_a_real_token():
    r = client.get(f"/api/kitchen/{TOKEN}/verify")
    assert r.status_code == 200
    assert r.json()["code"] == "asiacafe"


def test_verify_endpoint_rejects_a_bad_token():
    r = client.get("/api/kitchen/kt-notreal999/verify")
    assert r.status_code == 404


def test_verify_does_not_depend_on_airtable():
    """Sign-in must work even when Airtable is unreachable — otherwise an
    outage there locks every merchant out of their own screen mid-service."""
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "app", "kitchen.py")).read()
    fn = src.split("async def verify_kitchen_token")[1].split("@router")[0]
    assert "at.list_records" not in fn and "await at." not in fn


def test_signin_page_verifies_before_remembering():
    ui = open(os.path.join(os.path.dirname(__file__), "..",
                           "app", "ui", "merchant.html")).read()
    assert "/verify" in ui
    # the token is only persisted after a successful check
    assert ui.index("localStorage.setItem(KEY, token)") > ui.index("if(!r.ok)")


def test_kitchen_screen_remembers_device_and_offers_signout():
    k = open(os.path.join(os.path.dirname(__file__), "..",
                          "app", "ui", "kitchen.html")).read()
    assert "gw_kitchen_token" in k
    assert "kitchenSignOut" in k
