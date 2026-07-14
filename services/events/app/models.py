"""Event model — APPEND-ONLY by law (FSH-100 N-2, GWD-002 §6).
No update or delete path exists in this service. None will be added.
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, Integer, String, DateTime, Text, Index
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
    delivery_fee_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=399)
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
