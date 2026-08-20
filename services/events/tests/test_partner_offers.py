from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.growth import promo_discount_cents
from app.main import app
from app.models import Partner, PatchOffer


client = TestClient(app)


def _partner():
    db = SessionLocal()
    try:
        p = db.get(Partner, "offer-test")
        if not p:
            p = Partner(code="offer-test", display_name="Offer Test Kitchen",
                        portal_token="kt-offer-test", accepting_orders=True)
            db.add(p)
            db.commit()
    finally:
        db.close()


def test_partner_can_publish_and_pause_a_wallet_offer():
    _partner()
    created = client.post("/api/kitchen/kt-offer-test/offers", json={
        "title": "Dinner tonight", "detail": "A real partner-funded offer.",
        "percent": 20, "end_of_day": True})
    assert created.status_code == 201
    code = created.json()["promo_code"]
    db = SessionLocal()
    try:
        discount, _ = promo_discount_cents(code, "offer-test", 5000, db)
        assert discount == 1000
    finally:
        db.close()
    listing = client.get("/api/kitchen/kt-offer-test/offers").json()["offers"]
    assert any(x["id"] == created.json()["id"] and x["active"] for x in listing)
    paused = client.post(f"/api/kitchen/kt-offer-test/offers/{created.json()['id']}/active",
                         json={"active": False})
    assert paused.status_code == 200
    db = SessionLocal()
    try:
        assert promo_discount_cents(code, "offer-test", 5000, db)[0] == 0
    finally:
        db.close()


def test_expired_offer_is_hidden_and_rejected_by_checkout_math():
    _partner()
    db = SessionLocal()
    try:
        offer = PatchOffer(partner_code="offer-test", title="Expired test",
                           detail="No longer valid", promo_code="EXPIRED-PATCH",
                           active=True, expires_at=datetime.now(timezone.utc)-timedelta(minutes=1))
        from app.models import PromoCode
        db.add(offer)
        db.add(PromoCode(code="EXPIRED-PATCH", kind="percent", value=50,
                         partner_code="offer-test", active=True))
        db.commit()
        assert promo_discount_cents("EXPIRED-PATCH", "offer-test", 2000, db)[0] == 0
    finally:
        db.close()
    overview = client.get("/v0/patch/overview",
                          headers={"X-Patch-Identity": "p_partner_offer_test_1234567890"}).json()
    assert all(x["promo_code"] != "EXPIRED-PATCH" for x in overview["offers"])
