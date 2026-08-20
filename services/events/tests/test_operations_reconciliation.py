"""The ops digest is safe for a later Make notification: aggregate only and
protected by a board key."""
from fastapi.testclient import TestClient

from app.finance import create_payment_attempt, record_balanced_entries
from app.main import app
from app.db import SessionLocal


client = TestClient(app)


def test_reconciliation_summary_requires_board_access():
    assert client.get("/v0/ops/reconciliation").status_code == 403


def test_reconciliation_summary_reports_balanced_aggregate_without_pii():
    db = SessionLocal()
    try:
        attempt = create_payment_attempt(
            db, order_id="ORD-OPS-1", amount_cents=2500,
            idempotency_key="ops-attempt-1", partner_code="partner-a",
        )
        record_balanced_entries(
            db, order_id="ORD-OPS-1", payment_attempt_id=attempt.id,
            idempotency_key="ops-ledger-1",
            entries=[("customer_receivable", -2500, "Customer charge"),
                     ("partner_payable", 2500, "Partner payable")],
        )
        db.commit()
    finally:
        db.close()

    response = client.get("/v0/ops/reconciliation?key=test-key")
    assert response.status_code == 200
    payload = response.json()
    integrity = payload["money_integrity"]
    assert integrity["ledger_net_cents"] == 0
    assert integrity["unbalanced_payment_groups"] == 0
    assert integrity["ledger_entry_count"] >= 2
    assert payload["card_processing"]["enabled"] is False
    assert "ORD-OPS-1" not in str(payload)
    assert "partner-a" not in str(payload)


def test_reconciliation_summary_accepts_scoped_digest_key(monkeypatch):
    monkeypatch.setenv("OPS_DIGEST_KEY", "make-digest-only-key")
    response = client.get("/v0/ops/reconciliation?key=make-digest-only-key")
    assert response.status_code == 200
    assert response.json()["card_processing"]["enabled"] is False
