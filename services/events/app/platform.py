"""Patch community, loyalty, demand and expanded-service workflows.

Every write is durable and auditable. Public identity is deliberately a random
per-device identifier, never a phone number; sensitive operator actions remain
behind the existing individually revocable board access layer.
"""
from datetime import datetime, timezone
import json
import re
import secrets
import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_

from .db import SessionLocal
from .models import (BringRequest, BringVote, CommunityFollow, CommunityItem,
                     CommunityReport, CommunitySubmission,
                     Event, LoyaltyAccount, Partner, PartnerApplication, PatchPreference,
                     PatchOffer, SavedOffer, ServiceRequest)

router = APIRouter()
_IDENTITY = re.compile(r"^[A-Za-z0-9_-]{20,80}$")
_PUBLIC_HITS: dict[tuple[str, str], list[float]] = {}


def _guard_public(request: Request, action: str, limit: int = 20) -> None:
    ip = (request.headers.get("x-forwarded-for", "") or
          (request.client.host if request.client else "?")).split(",")[0].strip()
    now = time.monotonic()
    key = (ip, action)
    recent = [stamp for stamp in _PUBLIC_HITS.get(key, []) if now - stamp < 60]
    if len(recent) >= limit:
        raise HTTPException(429, "Too many attempts—wait a minute and try again")
    recent.append(now)
    _PUBLIC_HITS[key] = recent
    if len(_PUBLIC_HITS) > 10_000:
        _PUBLIC_HITS.clear()


def _identity(request: Request) -> str:
    value = request.headers.get("x-patch-identity", "").strip()
    if not _IDENTITY.fullmatch(value):
        raise HTTPException(401, "A valid Patch device identity is required")
    return value


def _event(db, kind: str, ref: str, actor: str, payload: dict) -> None:
    db.add(Event(event_type=kind, entity_ref=ref, tenant="patch", actor=actor,
                 payload=json.dumps(payload, separators=(",", ":"))))


def award_delivery_points(order_id: str, points: int = 100) -> bool:
    """Award once for a delivered order linked to a Patch device."""
    db = SessionLocal()
    try:
        already = db.query(Event).filter_by(event_type="loyalty.delivery_awarded",
                                             entity_ref=order_id).first()
        if already:
            return False
        linked = (db.query(Event).filter_by(event_type="order.customer_identity",
                                            entity_ref=order_id)
                  .order_by(Event.occurred_at.desc()).first())
        if not linked:
            return False
        try:
            identity = json.loads(linked.payload).get("identity", "")
        except (ValueError, TypeError):
            return False
        if not _IDENTITY.fullmatch(identity):
            return False
        account = db.get(LoyaltyAccount, identity)
        if not account:
            account = LoyaltyAccount(identity=identity, points=0, lifetime_points=0)
            db.add(account)
        account.points += max(0, points)
        account.lifetime_points += max(0, points)
        _event(db, "loyalty.delivery_awarded", order_id, "system",
               {"identity_hint": identity[-8:], "points": points})
        db.commit()
        return True
    finally:
        db.close()


def seed_patch_platform() -> None:
    db = SessionLocal()
    try:
        if not db.query(CommunityItem).count():
            db.add_all([
                CommunityItem(kind="welcome", title="Patch is open for local delivery",
                              summary="Order from local kitchens, send a custom delivery, or plan a larger meal from one place.",
                              source_name="Patch operations", published=True),
                CommunityItem(kind="service", title="Catering and recurring lunch requests are live",
                              summary="Tell us the headcount, date and budget. Patch operations will confirm the plan before anything is charged.",
                              source_name="Patch operations", published=True),
            ])
        if not db.query(PatchOffer).count():
            db.add_all([
                PatchOffer(title="Welcome to Patch", detail="Save 10% on a first local-kitchen order.",
                           promo_code="WELCOME10"),
                PatchOffer(title="Neighbor loyalty reward", detail="Save this reward and use LOYAL10 at checkout.",
                           promo_code="LOYAL10"),
            ])
        db.commit()
    finally:
        db.close()


@router.get("/v0/patch/overview")
def overview(request: Request):
    identity = request.headers.get("x-patch-identity", "").strip()
    valid_identity = bool(_IDENTITY.fullmatch(identity))
    db = SessionLocal()
    try:
        feed = (db.query(CommunityItem).filter(CommunityItem.published.is_(True))
                .order_by(CommunityItem.created_at.desc()).limit(30).all())
        now = datetime.now(timezone.utc)
        offers = (db.query(PatchOffer).filter(PatchOffer.active.is_(True),
                  or_(PatchOffer.expires_at.is_(None), PatchOffer.expires_at > now))
                  .order_by(PatchOffer.created_at.desc()).all())
        saved = set()
        points = 0
        follows = []
        preferences = {"palette": "patch", "text_size": "standard", "contrast": "standard",
                       "reduced_motion": False, "density": "comfortable",
                       "email_updates": False, "sms_updates": False,
                       "quiet_start": "21:00", "quiet_end": "09:00"}
        if valid_identity:
            saved = {r.offer_id for r in db.query(SavedOffer).filter(
                SavedOffer.identity == identity, SavedOffer.redeemed_at.is_(None)).all()}
            account = db.get(LoyaltyAccount, identity)
            points = account.points if account else 0
            follows = [r.topic for r in db.query(CommunityFollow).filter(
                CommunityFollow.identity == identity).all()]
            pref = db.get(PatchPreference, identity)
            if pref:
                preferences = {k: getattr(pref, k) for k in preferences}
        requests = db.query(BringRequest).order_by(BringRequest.created_at.desc()).limit(50).all()
        vote_counts = dict(db.query(BringVote.request_id, func.count(BringVote.id))
                           .group_by(BringVote.request_id).all())
        my_votes = set()
        if valid_identity:
            my_votes = {v.request_id for v in db.query(BringVote).filter(BringVote.identity == identity).all()}
        return {
            "feed": [{"id": x.id, "kind": x.kind, "title": x.title, "summary": x.summary,
                      "source_name": x.source_name, "source_url": x.source_url, "area": x.area,
                      "starts_at": x.starts_at.isoformat() if x.starts_at else None,
                      "created_at": x.created_at.isoformat()} for x in feed],
            "offers": [{"id": x.id, "partner_code": x.partner_code, "title": x.title,
                         "detail": x.detail, "promo_code": x.promo_code,
                         "points_cost": x.points_cost, "saved": x.id in saved,
                         "expires_at": x.expires_at.isoformat() if x.expires_at else None} for x in offers],
            "bring": [{"id": x.id, "name": x.name, "category": x.category, "area": x.area,
                       "note": x.note, "status": x.status, "votes": vote_counts.get(x.id, 0),
                       "voted": x.id in my_votes} for x in requests],
            "wallet": {"points": points, "saved_count": len(saved)}, "follows": follows,
            "preferences": preferences,
        }
    finally:
        db.close()


class FollowIn(BaseModel):
    topic: str = Field(min_length=2, max_length=80)


@router.post("/v0/patch/follows", status_code=201)
def follow(request: Request, body: FollowIn):
    _guard_public(request, "follow")
    identity, topic = _identity(request), body.topic.strip().lower()
    db = SessionLocal()
    try:
        row = db.query(CommunityFollow).filter_by(identity=identity, topic=topic).first()
        if not row:
            row = CommunityFollow(identity=identity, topic=topic)
            db.add(row)
            _event(db, "community.followed", row.id, f"device:{identity[-8:]}", {"topic": topic})
            db.commit()
        return {"ok": True, "topic": topic}
    finally:
        db.close()


class PreferenceIn(BaseModel):
    palette: str = Field(pattern="^(patch|warm|midnight)$")
    text_size: str = Field(pattern="^(standard|large|extra_large)$")
    contrast: str = Field(pattern="^(standard|high)$")
    reduced_motion: bool = False
    density: str = Field(pattern="^(comfortable|compact)$")
    email_updates: bool = False
    sms_updates: bool = False
    quiet_start: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    quiet_end: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


@router.put("/v0/patch/preferences")
def save_preferences(request: Request, body: PreferenceIn):
    _guard_public(request, "preferences")
    identity = _identity(request)
    db = SessionLocal()
    try:
        row = db.get(PatchPreference, identity)
        if not row:
            row = PatchPreference(identity=identity)
            db.add(row)
        for name, value in body.model_dump().items():
            setattr(row, name, value)
        _event(db, "preferences.updated", identity[-8:], f"device:{identity[-8:]}",
               {"palette": row.palette, "text_size": row.text_size,
                "contrast": row.contrast, "reduced_motion": row.reduced_motion})
        db.commit()
        return {"ok": True}
    finally:
        db.close()


class SubmissionIn(BaseModel):
    kind: str = Field(pattern="^(neighbor_note|courier_recognition|partner_love)$")
    partner_code: str = Field(default="", max_length=60)
    text: str = Field(min_length=8, max_length=500)
    display_name: str = Field(default="Neighbor", max_length=80)
    consent_to_publish: bool


@router.post("/v0/patch/community-submissions", status_code=201)
def community_submission(request: Request, body: SubmissionIn):
    _guard_public(request, "community_submission", 5)
    identity = _identity(request)
    if not body.consent_to_publish:
        raise HTTPException(422, "Publishing consent is required")
    db = SessionLocal()
    try:
        if body.partner_code and not db.get(Partner, body.partner_code):
            raise HTTPException(422, "Partner does not exist")
        row = CommunitySubmission(identity=identity, **body.model_dump())
        db.add(row)
        db.flush()
        _event(db, "community.submission_received", row.id, f"device:{identity[-8:]}",
               {"kind": row.kind, "partner_code": row.partner_code})
        db.commit()
        return {"ok": True, "id": row.id, "status": "pending",
                "message": "Thanks—Patch will review this before it appears publicly."}
    finally:
        db.close()


class ReportIn(BaseModel):
    reason: str = Field(default="review requested", max_length=240)


@router.post("/v0/patch/community-items/{item_id}/report", status_code=201)
def report_community_item(request: Request, item_id: str, body: ReportIn):
    _guard_public(request, "community_report", 10)
    identity = _identity(request)
    db = SessionLocal()
    try:
        item = db.get(CommunityItem, item_id)
        if not item or not item.published:
            raise HTTPException(404, "Community item not found")
        existing = db.query(CommunityReport).filter_by(item_id=item_id, identity=identity).first()
        if not existing:
            db.add(CommunityReport(item_id=item_id, identity=identity, reason=body.reason.strip()))
            _event(db, "community.item_reported", item_id, f"device:{identity[-8:]}", {})
            db.commit()
        return {"ok": True}
    finally:
        db.close()


class BringIn(BaseModel):
    name: str = Field(min_length=2, max_length=140)
    category: str = Field(default="restaurant", max_length=60)
    area: str = Field(default="Knoxville", max_length=100)
    note: str = Field(default="", max_length=400)


@router.post("/v0/patch/bring", status_code=201)
def create_bring(request: Request, body: BringIn):
    _guard_public(request, "bring", 10)
    identity = _identity(request)
    db = SessionLocal()
    try:
        existing = db.query(BringRequest).filter(func.lower(BringRequest.name) == body.name.strip().lower(),
                                                 func.lower(BringRequest.area) == body.area.strip().lower()).first()
        row = existing or BringRequest(name=body.name.strip(), category=body.category.strip().lower(),
                                       area=body.area.strip(), note=body.note.strip())
        if not existing:
            db.add(row)
            db.flush()
        if not db.query(BringVote).filter_by(request_id=row.id, identity=identity).first():
            db.add(BringVote(request_id=row.id, identity=identity))
            db.flush()
        if db.query(BringVote).filter_by(request_id=row.id).count() >= 100 and row.status == "gathering_votes":
            row.status = "outreach_ready"
        _event(db, "bring.requested" if not existing else "bring.voted", row.id,
               f"device:{identity[-8:]}", {"name": row.name, "area": row.area})
        db.commit()
        return {"ok": True, "id": row.id}
    finally:
        db.close()


@router.post("/v0/patch/bring/{request_id}/vote")
def vote(request: Request, request_id: str):
    _guard_public(request, "bring_vote", 20)
    identity = _identity(request)
    db = SessionLocal()
    try:
        row = db.get(BringRequest, request_id)
        if not row:
            raise HTTPException(404, "Request not found")
        if db.query(BringVote).filter_by(request_id=request_id, identity=identity).first():
            return {"ok": True, "already_voted": True}
        db.add(BringVote(request_id=request_id, identity=identity))
        db.flush()
        if db.query(BringVote).filter_by(request_id=request_id).count() >= 100 and row.status == "gathering_votes":
            row.status = "outreach_ready"
        _event(db, "bring.voted", request_id, f"device:{identity[-8:]}", {})
        db.commit()
        return {"ok": True, "already_voted": False}
    finally:
        db.close()


@router.post("/v0/patch/offers/{offer_id}/save")
def save_offer(request: Request, offer_id: str):
    _guard_public(request, "offer_save", 20)
    identity = _identity(request)
    db = SessionLocal()
    try:
        offer = db.get(PatchOffer, offer_id)
        if not offer or not offer.active:
            raise HTTPException(404, "Offer not found")
        saved = db.query(SavedOffer).filter_by(offer_id=offer_id, identity=identity).first()
        if not saved:
            saved = SavedOffer(offer_id=offer_id, identity=identity)
            db.add(saved)
            _event(db, "offer.saved", offer_id, f"device:{identity[-8:]}", {})
            db.commit()
        return {"ok": True, "promo_code": offer.promo_code}
    finally:
        db.close()


class ServiceIn(BaseModel):
    kind: str = Field(pattern="^(catering|recurring_lunch|custom_delivery|partner_delivery)$")
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=7, max_length=40)
    email: str = Field(default="", max_length=160)
    organization: str = Field(default="", max_length=160)
    requested_for: str = Field(default="", max_length=80)
    party_size: int = Field(default=1, ge=1, le=5000)
    pickup: str = Field(default="", max_length=300)
    dropoff: str = Field(default="", max_length=300)
    cadence: str = Field(default="once", max_length=80)
    budget_cents: int = Field(default=0, ge=0, le=100_000_000)
    notes: str = Field(default="", max_length=1200)


@router.post("/v0/patch/service-requests", status_code=201)
def service_request(request: Request, body: ServiceIn):
    _guard_public(request, "service_request", 5)
    identity = request.headers.get("x-patch-identity", "").strip()
    if identity and not _IDENTITY.fullmatch(identity):
        raise HTTPException(401, "Invalid Patch device identity")
    db = SessionLocal()
    try:
        row = ServiceRequest(id=str(uuid.uuid4()), identity=identity, **body.model_dump())
        db.add(row)
        _event(db, "service.requested", row.id, f"device:{identity[-8:]}" if identity else "public:web",
               {"kind": row.kind, "name": row.name, "phone": row.phone, "requested_for": row.requested_for})
        db.commit()
        return {"ok": True, "id": row.id, "status": row.status,
                "message": "Patch operations will confirm the details before fulfillment."}
    finally:
        db.close()


class ApplicationIn(BaseModel):
    business_name: str = Field(min_length=2, max_length=160)
    contact_name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=7, max_length=40)
    email: str = Field(min_length=5, max_length=160)
    address: str = Field(min_length=5, max_length=300)
    website: str = Field(default="", max_length=500)
    fulfillment: str = Field(default="delivery", max_length=80)
    notes: str = Field(default="", max_length=1000)


@router.post("/v0/patch/partner-applications", status_code=201)
def partner_application(request: Request, body: ApplicationIn):
    _guard_public(request, "partner_application", 3)
    db = SessionLocal()
    try:
        row = PartnerApplication(**body.model_dump())
        db.add(row)
        db.flush()
        _event(db, "partner.application_submitted", row.id, "public:web",
               {"business_name": row.business_name, "contact_name": row.contact_name})
        db.commit()
        return {"ok": True, "id": row.id, "status": row.status}
    finally:
        db.close()


@router.get("/api/board/{key}/patch-work")
def patch_work(key: str):
    from .boardauth import check_key
    check_key(key)
    db = SessionLocal()
    try:
        services = db.query(ServiceRequest).order_by(ServiceRequest.created_at.desc()).limit(200).all()
        applications = db.query(PartnerApplication).order_by(PartnerApplication.created_at.desc()).limit(200).all()
        submissions = db.query(CommunitySubmission).order_by(CommunitySubmission.created_at.desc()).limit(200).all()
        bring = db.query(BringRequest).order_by(BringRequest.created_at.desc()).limit(200).all()
        votes = dict(db.query(BringVote.request_id, func.count(BringVote.id)).group_by(BringVote.request_id).all())
        from .operations_sync import sync_health
        return {
            "service_requests": [{c.name: getattr(x, c.name) for c in ServiceRequest.__table__.columns
                                  if c.name not in {"identity"}} for x in services],
            "partner_applications": [{c.name: getattr(x, c.name) for c in PartnerApplication.__table__.columns}
                                     for x in applications],
            "community_submissions": [{c.name: getattr(x, c.name) for c in CommunitySubmission.__table__.columns
                                       if c.name != "identity"} for x in submissions],
            "bring_requests": [{"id": x.id, "name": x.name, "category": x.category,
                                "area": x.area, "status": x.status, "votes": votes.get(x.id, 0)} for x in bring],
            "operations_sync": sync_health(),
        }
    finally:
        db.close()


@router.post("/api/board/{key}/operations-sync/retry")
def retry_operations_sync(key: str):
    from .boardauth import check_key
    from .operations_sync import retry_pending
    check_key(key)
    return retry_pending()


class StatusIn(BaseModel):
    status: str = Field(pattern="^(new|reviewing|contacted|confirmed|completed|declined|submitted|changes_requested|approved|suspended|gathering_votes|outreach_ready|outreach_sent|partnered)$")
    note: str = Field(default="", max_length=600)


@router.patch("/api/board/{key}/patch-work/{kind}/{item_id}")
def update_patch_work(key: str, kind: str, item_id: str, body: StatusIn):
    from .boardauth import check_key
    actor = check_key(key)
    models = {"service": ServiceRequest, "application": PartnerApplication,
              "bring": BringRequest, "submission": CommunitySubmission}
    model = models.get(kind)
    if not model:
        raise HTTPException(404, "Unknown work type")
    db = SessionLocal()
    try:
        row = db.get(model, item_id)
        if not row:
            raise HTTPException(404, "Work item not found")
        row.status = body.status
        if kind == "application":
            row.review_note = body.note
            if body.status == "approved":
                code = re.sub(r"[^a-z0-9]+", "", row.business_name.lower())[:50] or f"partner{row.id[:6]}"
                existing = db.get(Partner, code)
                if not existing:
                    existing = Partner(code=code, display_name=row.business_name,
                                       status="onboarding", contact=f"{row.contact_name} · {row.phone} · {row.email}",
                                       address=row.address, accepting_orders=False,
                                       portal_token="kt-" + secrets.token_urlsafe(24))
                    db.add(existing)
        if kind == "submission" and body.status == "approved":
            published = CommunityItem(kind=row.kind, title=(row.display_name or "A neighbor") + " shared",
                                      summary=row.text, source_name="Patch community",
                                      area="Knoxville", published=True)
            db.add(published)
        _event(db, f"{kind}.status_changed", item_id, actor,
               {"status": body.status, "note": body.note})
        db.commit()
        result = {"ok": True, "status": body.status}
        if kind == "application" and body.status == "approved":
            result.update({"partner_code": existing.code, "portal_token": existing.portal_token})
        if kind == "submission" and body.status == "approved":
            result["community_item_id"] = published.id
        return result
    finally:
        db.close()


class CommunityIn(BaseModel):
    kind: str = Field(default="community", max_length=30)
    title: str = Field(min_length=3, max_length=160)
    summary: str = Field(min_length=3, max_length=600)
    source_name: str = Field(min_length=2, max_length=120)
    source_url: str = Field(default="", max_length=700)
    area: str = Field(default="Knoxville", max_length=100)
    published: bool = False


@router.post("/api/board/{key}/community-items", status_code=201)
def create_community_item(key: str, body: CommunityIn):
    from .boardauth import check_key
    actor = check_key(key)
    if body.source_url and not body.source_url.startswith(("https://", "http://")):
        raise HTTPException(422, "Source URL must use http or https")
    db = SessionLocal()
    try:
        row = CommunityItem(**body.model_dump())
        db.add(row)
        db.flush()
        _event(db, "community.item_created", row.id, actor,
               {"title": row.title, "published": row.published})
        db.commit()
        return {"ok": True, "id": row.id, "published": row.published}
    finally:
        db.close()


class OfferIn(BaseModel):
    title: str = Field(min_length=3, max_length=140)
    detail: str = Field(min_length=3, max_length=400)
    partner_code: str = Field(default="", max_length=60)
    promo_code: str = Field(default="", max_length=30)
    points_cost: int = Field(default=0, ge=0, le=1_000_000)


@router.post("/api/board/{key}/offers", status_code=201)
def create_offer(key: str, body: OfferIn):
    from .boardauth import check_key
    actor = check_key(key)
    db = SessionLocal()
    try:
        if body.partner_code and not db.get(Partner, body.partner_code):
            raise HTTPException(422, "Partner code does not exist")
        values = body.model_dump()
        values["promo_code"] = body.promo_code.strip().upper()
        row = PatchOffer(**values)
        db.add(row)
        db.flush()
        _event(db, "offer.created", row.id, actor, {"title": row.title})
        db.commit()
        return {"ok": True, "id": row.id}
    finally:
        db.close()


@router.post("/api/board/{key}/saved-offers/{saved_id}/redeem")
def redeem_offer(key: str, saved_id: str):
    from .boardauth import check_key
    actor = check_key(key)
    db = SessionLocal()
    try:
        saved = db.get(SavedOffer, saved_id)
        if not saved:
            raise HTTPException(404, "Saved offer not found")
        if saved.redeemed_at:
            return {"ok": True, "already_redeemed": True}
        offer = db.get(PatchOffer, saved.offer_id)
        if not offer or not offer.active:
            raise HTTPException(409, "Offer is no longer active")
        account = db.get(LoyaltyAccount, saved.identity)
        if offer.points_cost:
            if not account or account.points < offer.points_cost:
                raise HTTPException(409, "Not enough points")
            account.points -= offer.points_cost
        saved.redeemed_at = datetime.now(timezone.utc)
        _event(db, "offer.redeemed", offer.id, actor,
               {"saved_id": saved.id, "points_cost": offer.points_cost})
        db.commit()
        return {"ok": True, "already_redeemed": False}
    finally:
        db.close()
