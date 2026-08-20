"""Owned operational mirror for the Airtable-to-PostgreSQL transition.

The Airtable record ID is preserved as the primary key. Human order IDs are
not primary keys because the pilot data contains duplicate order IDs; keeping
both source rows is safer than silently collapsing history.
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text, Index
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SourceRecordMixin:
    source_record_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)
    raw_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class OpsCustomer(SourceRecordMixin, Base):
    __tablename__ = "ops_customers"

    customer_id: Mapped[str] = mapped_column(String(60), nullable=False, default="", index=True)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    customer_type: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    contact_name: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    pickup_address_default: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    order_source_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")


class OpsDriver(SourceRecordMixin, Base):
    __tablename__ = "ops_drivers"

    driver_id: Mapped[str] = mapped_column(String(60), nullable=False, default="", index=True)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    day_token: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    token_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    order_source_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    delivery_source_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")


class OpsOrder(SourceRecordMixin, Base):
    __tablename__ = "ops_orders"

    order_id: Mapped[str] = mapped_column(String(60), nullable=False, default="", index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    source_channel: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    pickup_address: Mapped[str] = mapped_column(Text, nullable=False, default="")
    dropoff_address: Mapped[str] = mapped_column(Text, nullable=False, default="")
    dropoff_contact_name: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    dropoff_contact_phone: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    items_description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    special_instructions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    requested_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    promised_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    promised_window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fingerprint: Mapped[str] = mapped_column(String(100), nullable=False, default="", index=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    in_transit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    fail_reason: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ai_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    customer_name_raw: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    customer_phone_raw: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    partner_code: Mapped[str] = mapped_column(String(80), nullable=False, default="", index=True)
    subtotal_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fee_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tip_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    customer_source_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    driver_source_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    delivery_source_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    __table_args__ = (
        Index("ix_ops_orders_status_received", "status", "received_at"),
        Index("ix_ops_orders_partner_status", "partner_code", "status"),
    )


class OpsDelivery(SourceRecordMixin, Base):
    __tablename__ = "ops_deliveries"

    delivery_id: Mapped[str] = mapped_column(String(60), nullable=False, default="", index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stop_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fail_reason: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    proof_photo_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    order_source_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    driver_source_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")


class OpsEvent(SourceRecordMixin, Base):
    __tablename__ = "ops_events"

    event_id: Mapped[str] = mapped_column(String(80), nullable=False, default="", index=True)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False, default="", index=True)
    entity_ref: Mapped[str] = mapped_column(String(120), nullable=False, default="", index=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actor: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="")


class AirtableMigrationRun(Base):
    __tablename__ = "airtable_migration_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    source_counts_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    target_counts_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    duplicate_order_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")


class OperationalSyncQueue(Base):
    """Durable handoff from a successful Airtable mutation to owned Postgres.

    The queue row commits before transformation is attempted. A conversion or
    database failure therefore becomes visible/retryable instead of silently
    allowing the two operational stores to drift.
    """
    __tablename__ = "operational_sync_queue"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    table_name: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    source_record_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    raw_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
