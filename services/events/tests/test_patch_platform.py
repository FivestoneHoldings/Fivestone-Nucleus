from fastapi.testclient import TestClient

from app.main import app
from app.db import SessionLocal
from app.models import Event
from app.platform import award_delivery_points


client = TestClient(app)
IDENTITY = "p_123456789012345678901234567890"
HEADERS = {"X-Patch-Identity": IDENTITY}


def test_patch_page_and_seeded_overview_are_live():
    page = client.get("/patch")
    assert page.status_code == 200
    assert "Bring it" in page.text
    response = client.get("/v0/patch/overview", headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["feed"]
    assert data["offers"]
    assert data["wallet"]["points"] == 0


def test_bring_request_deduplicates_and_allows_one_vote_per_identity():
    body = {"name": "Neighborhood Test Kitchen", "category": "restaurant",
            "area": "Knoxville", "note": "A useful test nomination"}
    first = client.post("/v0/patch/bring", headers=HEADERS, json=body)
    assert first.status_code == 201
    second = client.post("/v0/patch/bring", headers=HEADERS, json=body)
    assert second.status_code == 201
    overview = client.get("/v0/patch/overview", headers=HEADERS).json()
    row = next(x for x in overview["bring"] if x["id"] == first.json()["id"])
    assert row["votes"] == 1
    assert row["voted"] is True


def test_offer_save_is_idempotent():
    offer = client.get("/v0/patch/overview", headers=HEADERS).json()["offers"][0]
    assert client.post(f"/v0/patch/offers/{offer['id']}/save", headers=HEADERS).status_code == 200
    assert client.post(f"/v0/patch/offers/{offer['id']}/save", headers=HEADERS).status_code == 200
    data = client.get("/v0/patch/overview", headers=HEADERS).json()
    assert data["wallet"]["saved_count"] == 1


def test_service_request_enters_operator_queue():
    body = {"kind": "catering", "name": "Pat", "phone": "865-555-0123",
            "party_size": 25, "requested_for": "Friday noon", "budget_cents": 50000,
            "notes": "Lunch for the team"}
    created = client.post("/v0/patch/service-requests", headers=HEADERS, json=body)
    assert created.status_code == 201
    queue = client.get("/api/board/test-key/patch-work")
    assert queue.status_code == 200
    assert any(x["id"] == created.json()["id"] for x in queue.json()["service_requests"])


def test_partner_application_review_transition_is_audited():
    created = client.post("/v0/patch/partner-applications", json={
        "business_name": "Test Bakery", "contact_name": "Owner",
        "phone": "865-555-0100", "email": "owner@example.com",
        "address": "100 Main Street, Knoxville, TN"})
    assert created.status_code == 201
    changed = client.patch(
        f"/api/board/test-key/patch-work/application/{created.json()['id']}",
        json={"status": "reviewing", "note": "Initial review started"})
    assert changed.status_code == 200
    queue = client.get("/api/board/test-key/patch-work").json()
    row = next(x for x in queue["partner_applications"] if x["id"] == created.json()["id"])
    assert row["status"] == "reviewing"


def test_delivery_points_are_idempotent():
    order_id = "ORD-PATCHPOINTSTEST"
    db = SessionLocal()
    db.add(Event(event_type="order.customer_identity", entity_ref=order_id,
                 tenant="gateway", actor="system", payload='{"identity":"p_123456789012345678901234567890"}'))
    db.commit()
    db.close()
    assert award_delivery_points(order_id) is True
    assert award_delivery_points(order_id) is False
    wallet = client.get("/v0/patch/overview", headers=HEADERS).json()["wallet"]
    assert wallet["points"] == 100


def test_operator_can_publish_reviewed_item_and_create_offer():
    item = client.post("/api/board/test-key/community-items", json={
        "kind": "event", "title": "Market day",
        "summary": "A reviewed neighborhood event.", "source_name": "City calendar",
        "source_url": "https://example.com/event", "published": True})
    assert item.status_code == 201
    assert any(x["id"] == item.json()["id"] for x in client.get(
        "/v0/patch/overview", headers=HEADERS).json()["feed"])
    offer = client.post("/api/board/test-key/offers", json={
        "title": "Test reward", "detail": "Created by an authorized operator.",
        "promo_code": "test20", "points_cost": 50})
    assert offer.status_code == 201


def test_neighbor_submission_requires_consent_and_moderation():
    body = {"kind": "courier_recognition", "text": "The courier was thoughtful and careful.",
            "display_name": "A neighbor", "consent_to_publish": False}
    assert client.post("/v0/patch/community-submissions", headers=HEADERS, json=body).status_code == 422
    body["consent_to_publish"] = True
    created = client.post("/v0/patch/community-submissions", headers=HEADERS, json=body)
    assert created.status_code == 201
    queue = client.get("/api/board/test-key/patch-work").json()
    assert any(x["id"] == created.json()["id"] for x in queue["community_submissions"])
    approved = client.patch(
        f"/api/board/test-key/patch-work/submission/{created.json()['id']}",
        json={"status": "approved", "note": "Safe to publish"})
    assert approved.status_code == 200
    feed = client.get("/v0/patch/overview", headers=HEADERS).json()["feed"]
    assert any(x["id"] == approved.json()["community_item_id"] for x in feed)


def test_accessibility_and_notification_preferences_round_trip():
    body = {"palette": "midnight", "text_size": "large", "contrast": "high",
            "reduced_motion": True, "density": "compact", "email_updates": False,
            "sms_updates": True, "quiet_start": "20:30", "quiet_end": "08:15"}
    assert client.put("/v0/patch/preferences", headers=HEADERS, json=body).status_code == 200
    preferences = client.get("/v0/patch/overview", headers=HEADERS).json()["preferences"]
    assert preferences == body
