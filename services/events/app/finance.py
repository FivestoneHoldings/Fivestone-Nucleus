"""Patch money integrity primitives.

This module deliberately does not create a Stripe charge. It makes the owned
recording and reconciliation rules testable before live payment credentials,
webhook secrets, payouts, or customers are introduced.
"""
import json
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import MoneyLedgerEntry, PaymentAttempt, PaymentWebhookReceipt


PATCH_CLEARING = "patch_clearing"
CUSTOMER_RECEIVABLE = "customer_receivable"
PARTNER_PAYABLE = "partner_payable"
COURIER_PAYABLE = "courier_payable"
TAX_PAYABLE = "tax_payable"
PATCH_REVENUE = "patch_revenue"
PROCESSOR_EXPENSE = "processor_expense"


def create_payment_attempt(db: Session, *, order_id: str, amount_cents: int,
                           idempotency_key: str, partner_code: str = "") -> PaymentAttempt:
    if amount_cents <= 0:
        raise ValueError("Payment amount must be greater than zero")
    existing = db.scalar(select(PaymentAttempt).where(
        PaymentAttempt.idempotency_key == idempotency_key))
    if existing:
        return existing
    attempt = PaymentAttempt(
        id=str(uuid.uuid4()), order_id=order_id, amount_cents=amount_cents,
        idempotency_key=idempotency_key, partner_code=partner_code,
    )
    db.add(attempt)
    db.flush()
    return attempt


def record_balanced_entries(db: Session, *, order_id: str, idempotency_key: str,
                            entries: list[tuple[str, int, str]], payment_attempt_id: str = "") -> list[MoneyLedgerEntry]:
    """Record one balanced business event once.

    ``entries`` is ``(account, signed cents, description)``. The total must be
    zero so that every dollar entering Patch is allocated somewhere explicit.
    """
    if not entries or sum(amount for _, amount, _ in entries) != 0:
        raise ValueError("Ledger entries must be non-empty and balance to zero")
    existing = list(db.scalars(select(MoneyLedgerEntry).where(
        MoneyLedgerEntry.idempotency_key == idempotency_key)))
    if existing:
        return existing
    rows = [MoneyLedgerEntry(
        id=str(uuid.uuid4()), order_id=order_id, payment_attempt_id=payment_attempt_id,
        account=account, amount_cents=amount, entry_type="payment_capture",
        idempotency_key=idempotency_key, description=description,
    ) for account, amount, description in entries]
    db.add_all(rows)
    db.flush()
    return rows


def record_webhook_once(db: Session, *, provider: str, event_id: str,
                        event_type: str, payload: dict) -> PaymentWebhookReceipt:
    existing = db.get(PaymentWebhookReceipt, {"provider": provider, "provider_event_id": event_id})
    if existing:
        return existing
    receipt = PaymentWebhookReceipt(provider=provider, provider_event_id=event_id,
                                    event_type=event_type,
                                    payload_json=json.dumps(payload, sort_keys=True),
                                    status="received")
    db.add(receipt)
    db.flush()
    return receipt


def reconciliation_totals(db: Session, order_id: str) -> dict[str, int]:
    """Return current per-account totals for an order; a zero total is balanced."""
    rows = db.execute(select(MoneyLedgerEntry.account, func.sum(MoneyLedgerEntry.amount_cents))
                      .where(MoneyLedgerEntry.order_id == order_id)
                      .group_by(MoneyLedgerEntry.account)).all()
    return {account: int(total or 0) for account, total in rows}
