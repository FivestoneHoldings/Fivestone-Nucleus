"""Event model — APPEND-ONLY by law (FSH-100 N-2, GWD-002 §6).
No update or delete path exists in this service. None will be added.
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Text, Index
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
