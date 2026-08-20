from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.finance import (CUSTOMER_RECEIVABLE, PATCH_CLEARING, PATCH_REVENUE,
                         create_payment_attempt, record_balanced_entries,
                         record_webhook_once, reconciliation_totals)
from app.models import MoneyLedgerEntry, PaymentWebhookReceipt


def test_payment_attempt_and_ledger_are_idempotent_and_balanced():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        first = create_payment_attempt(db, order_id="ORD-1", amount_cents=2000,
                                       idempotency_key="checkout:ORD-1")
        second = create_payment_attempt(db, order_id="ORD-1", amount_cents=2000,
                                        idempotency_key="checkout:ORD-1")
        assert first.id == second.id

        entries = [(CUSTOMER_RECEIVABLE, -2000, "Customer charge"),
                   (PATCH_CLEARING, 1800, "Funds held for allocations"),
                   (PATCH_REVENUE, 200, "Patch service fee")]
        first_entries = record_balanced_entries(db, order_id="ORD-1",
            payment_attempt_id=first.id, idempotency_key="capture:pi_1", entries=entries)
        second_entries = record_balanced_entries(db, order_id="ORD-1",
            payment_attempt_id=first.id, idempotency_key="capture:pi_1", entries=entries)
        assert len(first_entries) == len(second_entries) == 3
        assert db.query(MoneyLedgerEntry).count() == 3
        assert sum(reconciliation_totals(db, "ORD-1").values()) == 0


def test_unbalanced_ledger_and_duplicate_webhook_are_safe():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        try:
            record_balanced_entries(db, order_id="ORD-2", idempotency_key="bad",
                                    entries=[(PATCH_CLEARING, 10, "bad")])
            assert False, "unbalanced money must be rejected"
        except ValueError:
            pass
        first = record_webhook_once(db, provider="stripe", event_id="evt_1",
                                    event_type="payment_intent.succeeded", payload={"id": "evt_1"})
        second = record_webhook_once(db, provider="stripe", event_id="evt_1",
                                     event_type="payment_intent.succeeded", payload={"id": "evt_1"})
        assert first.provider_event_id == second.provider_event_id
        assert db.query(PaymentWebhookReceipt).count() == 1
