"""Event model — APPEND-ONLY by law (FSH-100 N-2, GWD-002 §6).
No update or delete path exists in this service. None will be added.
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, Float, Integer, String, DateTime, Text, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    tenant: Mapped[str] = mapped_column(String(60), nullable=False, default="gateway")
    actor: Mapped[str] = mapped_column(String(120), nullable=False, default="system")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    __table_args__ = (
        Index("ix_events_entity_ref", "entity_ref"),
        Index("ix_events_type_time", "event_type", "occurred_at"),
        Index("ix_events_tenant", "tenant"),
    )


class Proof(Base):
    """Proof-of-delivery photo, stored on OWNED infrastructure (closes the v0 gap)."""
    __tablename__ = "proofs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    content_b64: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(60), nullable=False, default="image/jpeg")
    lat: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    lng: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class Partner(Base):
    """Partner/tenant registry — Identity service owns this at M3 (ADR-008 staging)."""
    __tablename__ = "partners"

    code: Mapped[str] = mapped_column(String(60), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pilot")
    contact: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    address: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    delivery_fee_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=599)
    # Service area. Radius is a business setting the founder can tune per
    # kitchen; 0 disables the check entirely for that partner. lat/lng are
    # geocoded from `address` once and then reused forever.
    delivery_radius_miles: Mapped[float] = mapped_column(Float, nullable=False, default=5.0)
    lat: Mapped[float] = mapped_column(Float, nullable=True)
    lng: Mapped[float] = mapped_column(Float, nullable=True)
    # Title for the spotlight row at the top of their menu. Empty = "⭐ Featured".
    featured_label: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    # Opening hours as {"mon":["11:00","21:00"], ..., "sun":null}. Empty means
    # "no hours set", which means always open — see app/hours.py.
    hours_json: Mapped[str] = mapped_column(Text, nullable=False, default="")
    accepting_orders: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    portal_token: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    thank_you_note: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    about_blurb: Mapped[str] = mapped_column(String(280), nullable=False, default="")
    hero_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    special_text: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    special_date: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    cuisine: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    tagline: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    brand_color: Mapped[str] = mapped_column(String(9), nullable=False, default="")
    logo_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    cover_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class Notification(Base):
    """SMS outbox — every attempt recorded, sent or not. The record never pretends."""
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    to_phone: Mapped[str] = mapped_column(String(30), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)  # sent | failed | skipped_unconfigured | skipped_no_phone
    detail: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class PaymentAttempt(Base):
    """One provider-facing payment lifecycle for an order.

    This intentionally records an attempt before any money is moved. The
    provider reference is unique when present, while the Patch idempotency key
    prevents a browser retry from creating a second charge.
    """
    __tablename__ = "payment_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False, default="stripe")
    provider_payment_id: Mapped[str | None] = mapped_column(String(120), nullable=True, unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="usd")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="created")
    partner_code: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    raw_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow,
                                                 onupdate=_utcnow, nullable=False)


class MoneyLedgerEntry(Base):
    """Immutable money movement expressed in integer cents.

    Each business event creates balanced entries under one idempotency key. A
    negative amount is a debit from that account; positive is a credit. This is
    Patch's reconciliation record, independent from Stripe's dashboard.
    """
    __tablename__ = "money_ledger_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    payment_attempt_id: Mapped[str] = mapped_column(String(36), nullable=False, default="", index=True)
    account: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="usd")
    entry_type: Mapped[str] = mapped_column(String(60), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        Index("ix_ledger_idempotency_account", "idempotency_key", "account", unique=True),
    )


class PaymentWebhookReceipt(Base):
    """Provider webhook inbox. A provider event is processed at most once."""
    __tablename__ = "payment_webhook_receipts"

    provider: Mapped[str] = mapped_column(String(30), primary_key=True)
    provider_event_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="received")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)


class MenuItem(Base):
    """Partner menu catalog. Prices in cents. Seeded menus are DRAFTS until the
    partner confirms pricing — editable live from the Command Board."""
    __tablename__ = "menu_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    partner_code: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(80), nullable=False, default="Menu")
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    description: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    image_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class DriverLocation(Base):
    """Last-known driver position (upsert, one row per driver). Powers the
    live map on the customer tracking page while a delivery is in transit."""
    __tablename__ = "driver_locations"

    driver_ref: Mapped[str] = mapped_column(String(120), primary_key=True)
    lat: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    lng: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class ReopenAlert(Base):
    """A neighbor asked to be told when a paused kitchen comes back."""
    __tablename__ = "reopen_alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    partner_code: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    notified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PromoCode(Base):
    """A discount the founder stands behind. Server is the only authority on
    what a code is worth — the driver's cash-due must never trust the client."""
    __tablename__ = "promo_codes"

    code: Mapped[str] = mapped_column(String(30), primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False, default="percent")  # percent | cents
    value: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    description: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    partner_code: Mapped[str] = mapped_column(String(60), nullable=False, default="")  # "" = all merchants
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    max_uses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 0 = unlimited
    uses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class PartnerPost(Base):
    """A kitchen's own news feed post — 'Back from vacation!', 'New winter menu
    is in!' — real, dated, kitchen-authored updates. Shown newest-first on their
    storefront and rolled into the home highlights rail. Distinct from
    special_text/special_date (today's single dish special): a post is a running
    blog, not a single slot."""
    __tablename__ = "partner_posts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    partner_code: Mapped[str] = mapped_column(String(60), nullable=False)
    text: Mapped[str] = mapped_column(String(280), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class Lead(Base):
    """Someone raised their hand — a driver who wants to drive, a merchant who
    wants in. Customer service is everything; nothing gets lost."""
    __tablename__ = "leads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # driver | merchant
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    message: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class SupportTicket(Base):
    """A neighbor needs help. Every message lands somewhere a human will read."""
    __tablename__ = "support_tickets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    order_id: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class OptionGroup(Base):
    """A question the kitchen asks about an item: 'Choose your protein',
    'Spice level', 'Add a side'. Attached to ONE menu item.

    min_select/max_select drive the UI *and* the server guard: a required
    protein choice (min=1) must be answered before the item can be ordered, and
    a 'pick up to 3 sauces' group (max=3) cannot be gamed into 30.
    """
    __tablename__ = "option_groups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    item_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    min_select: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_select: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class OptionChoice(Base):
    """One answer to an OptionGroup's question. price_delta_cents may be zero
    (Chicken, no charge) or positive (Shrimp +$4.00). It is NEVER negative — a
    modifier must not be able to discount an order."""
    __tablename__ = "option_choices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    group_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    price_delta_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class DeliveryPreference(Base):
    """How THIS neighbor wants to be delivered to. 'Blue house, no garage.
    Always knock. Leave it with the screen door closed — the dog gets out.'

    The big apps give you one cramped text box per order and forget it the moment
    it's delivered. We remember, because the third time a driver comes to your
    door you shouldn't have to explain your own house again.
    """
    __tablename__ = "delivery_preferences"

    phone: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    dropoff_style: Mapped[str] = mapped_column(String(30), nullable=False, default="")  # hand_to_me|leave_at_door|meet_outside
    knock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    avoid_doorbell: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    home_description: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    access_notes: Mapped[str] = mapped_column(String(400), nullable=False, default="")  # gate codes, parking, apt buzzer
    driver_notes: Mapped[str] = mapped_column(String(400), nullable=False, default="")  # "dog is friendly", "baby asleep"
    allergies: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    utensils: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    preferred_driver: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    avatar: Mapped[str] = mapped_column(String(10), nullable=False, default="")  # emoji avatar, no PII
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow,
                                                 onupdate=_utcnow, nullable=False)


class DriverProfile(Base):
    """The driver is a person, not a routing token. Name, vehicle, a note from
    dispatch, and the things a customer is allowed to know about who's coming."""
    __tablename__ = "driver_profiles"

    driver_id: Mapped[str] = mapped_column(String(60), primary_key=True)   # airtable record id
    display_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    avatar: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    vehicle: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    vehicle_color: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    bio: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    photo_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class DriverRequest(Base):
    """A neighbor asked for a specific driver by name. We try. We never promise —
    a driver has their own day, and a promise we can't keep is worse than a
    'maybe' we were honest about."""
    __tablename__ = "driver_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    requested_driver: Mapped[str] = mapped_column(String(80), nullable=False)
    customer_phone: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    honored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class CommunityItem(Base):
    """Reviewed, attributable local information shown in Patch Today."""
    __tablename__ = "community_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    kind: Mapped[str] = mapped_column(String(30), nullable=False, default="community")
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    summary: Mapped[str] = mapped_column(String(600), nullable=False, default="")
    source_name: Mapped[str] = mapped_column(String(120), nullable=False, default="Patch")
    source_url: Mapped[str] = mapped_column(String(700), nullable=False, default="")
    area: Mapped[str] = mapped_column(String(100), nullable=False, default="Knoxville")
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class CommunityFollow(Base):
    __tablename__ = "community_follows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    identity: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    topic: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("identity", "topic", name="uq_community_follow_identity_topic"),)


class CommunitySubmission(Base):
    """Neighbor-authored content stays private until an operator publishes it."""
    __tablename__ = "community_submissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    identity: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False, default="neighbor_note")
    partner_code: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    text: Mapped[str] = mapped_column(String(500), nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False, default="Neighbor")
    consent_to_publish: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    moderation_note: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class CommunityReport(Base):
    __tablename__ = "community_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    item_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    identity: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(240), nullable=False, default="review requested")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("item_id", "identity", name="uq_community_report_identity"),)


class BringRequest(Base):
    """A requested business/service and its transparent outreach state."""
    __tablename__ = "bring_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    category: Mapped[str] = mapped_column(String(60), nullable=False, default="restaurant")
    area: Mapped[str] = mapped_column(String(100), nullable=False, default="Knoxville")
    note: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="gathering_votes")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class BringVote(Base):
    __tablename__ = "bring_votes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    request_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    identity: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("request_id", "identity", name="uq_bring_vote_request_identity"),)


class PatchOffer(Base):
    __tablename__ = "patch_offers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    partner_code: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(140), nullable=False)
    detail: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    promo_code: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    points_cost: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class SavedOffer(Base):
    __tablename__ = "saved_offers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    offer_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    identity: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("offer_id", "identity", name="uq_saved_offer_identity"),)


class LoyaltyAccount(Base):
    __tablename__ = "loyalty_accounts"

    identity: Mapped[str] = mapped_column(String(80), primary_key=True)
    points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lifetime_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow,
                                                 onupdate=_utcnow, nullable=False)


class PatchPreference(Base):
    __tablename__ = "patch_preferences"

    identity: Mapped[str] = mapped_column(String(80), primary_key=True)
    palette: Mapped[str] = mapped_column(String(20), nullable=False, default="patch")
    text_size: Mapped[str] = mapped_column(String(20), nullable=False, default="standard")
    contrast: Mapped[str] = mapped_column(String(20), nullable=False, default="standard")
    reduced_motion: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    density: Mapped[str] = mapped_column(String(20), nullable=False, default="comfortable")
    email_updates: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sms_updates: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    quiet_start: Mapped[str] = mapped_column(String(5), nullable=False, default="21:00")
    quiet_end: Mapped[str] = mapped_column(String(5), nullable=False, default="09:00")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow,
                                                 onupdate=_utcnow, nullable=False)


class ServiceRequest(Base):
    """Structured fulfillment intake for catering, recurring and courier work."""
    __tablename__ = "service_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    identity: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(40), nullable=False)
    email: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    organization: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    requested_for: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    party_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    pickup: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    dropoff: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    cadence: Mapped[str] = mapped_column(String(80), nullable=False, default="once")
    budget_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str] = mapped_column(String(1200), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="new")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class PartnerApplication(Base):
    __tablename__ = "partner_applications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_name: Mapped[str] = mapped_column(String(160), nullable=False)
    contact_name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(40), nullable=False)
    email: Mapped[str] = mapped_column(String(160), nullable=False)
    address: Mapped[str] = mapped_column(String(300), nullable=False)
    website: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    fulfillment: Mapped[str] = mapped_column(String(80), nullable=False, default="delivery")
    notes: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="submitted")
    review_note: Mapped[str] = mapped_column(String(600), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
