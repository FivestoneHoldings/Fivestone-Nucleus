"""Protected operational summaries for Patch.

These endpoints deliberately report only aggregate operational facts.  They
are designed for a founder dashboard or a later notification workflow; neither
surface should receive customer addresses, phone numbers, card details, or raw
provider payloads.
"""
import os
import secrets

from fastapi import APIRouter
from sqlalchemy import select

from . import boardauth
from .db import SessionLocal
from .models import MoneyLedgerEntry, PaymentAttempt, PaymentWebhookReceipt


router = APIRouter()


def _check_operations_key(key: str) -> None:
    """Accept a narrowly-scoped digest credential when it is configured.

    Make needs only the aggregate digest, not founder-level board access.  The
    board key remains a break-glass/manual route until the scoped key is set.
    """
    configured = os.environ.get("OPS_DIGEST_KEY", "")
    if configured and secrets.compare_digest(str(key or ""), configured):
        return
    boardauth.check_key(key)


@router.get("/v0/ops/reconciliation")
def reconciliation_summary(key: str = ""):
    """Return a small, authenticated money-operations health summary.

    The route does not expose records or provider payloads.  It also reports
    card processing as disabled until the complete Stripe launch gate is met,
    rather than implying that a configured key means money handling is ready.
    """
    _check_operations_key(key)
    db = SessionLocal()
    try:
        attempts = list(db.scalars(select(PaymentAttempt)))
        entries = list(db.scalars(select(MoneyLedgerEntry)))
        receipts = list(db.scalars(select(PaymentWebhookReceipt)))

        status_counts: dict[str, int] = {}
        for attempt in attempts:
            status_counts[attempt.status] = status_counts.get(attempt.status, 0) + 1

        balances: dict[str, int] = {}
        for entry in entries:
            # Empty is used only before a provider attempt is linked.  It is
            # still a financial event and must be included in the integrity
            # check, rather than silently omitted.
            group = entry.payment_attempt_id or "unlinked"
            balances[group] = balances.get(group, 0) + entry.amount_cents

        unbalanced = sum(1 for total in balances.values() if total != 0)
        pending_webhooks = sum(1 for receipt in receipts
                               if receipt.status not in {"processed", "ignored"})
        stripe_configured = bool(os.environ.get("STRIPE_SECRET_KEY"))

        return {
            "money_integrity": {
                "ledger_entry_count": len(entries),
                "ledger_net_cents": sum(entry.amount_cents for entry in entries),
                "unbalanced_payment_groups": unbalanced,
                "payment_attempts_by_status": status_counts,
                "pending_webhooks": pending_webhooks,
            },
            "card_processing": {
                "enabled": False,
                "status": "not_ready",
                "provider_key_configured": stripe_configured,
                "reason": "Card payments stay disabled until the Stripe Connect launch gate is approved.",
            },
        }
    finally:
        db.close()
