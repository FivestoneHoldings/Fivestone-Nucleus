from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.migrate_airtable_to_postgres import apply_payloads, relationship_orphans
from app.operations_models import OpsCustomer, OpsDriver, OpsEvent, OpsOrder


def _rec(record_id, fields):
    return {"id": record_id, "createdTime": "2026-07-08T14:14:22.000Z", "fields": fields}


def test_backfill_is_idempotent_and_preserves_duplicate_human_order_ids():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    payloads = {
        "customers": [_rec("rec-customer", {"customer_id": "CUS-1",
                                                "orders": ["rec-one"]})],
        "orders": [
            _rec("rec-one", {"order_id": "ORD-DUP", "status": {"name": "received"},
                              "total_cents": 1599, "driver": ["rec-driver"],
                              "customer": [{"id": "rec-customer"}]}),
            _rec("rec-two", {"order_id": "ORD-DUP", "status": {"name": "cancelled"},
                              "total_cents": 1599}),
        ],
        "drivers": [_rec("rec-driver", {"driver_id": "DRV-1", "display_name": "Pilot",
                                           "status": {"name": "active"}})],
        "deliveries": [],
        "events": [_rec("rec-event", {"event_id": "EVT-1", "event_type": "order.received",
                                         "entity_ref": "ORD-DUP", "actor": "system"})],
    }
    with Session(engine) as db:
        first = apply_payloads(payloads, db)
        db.commit()
        second = apply_payloads(payloads, db)
        db.commit()
        assert first["counts_match"] is True
        assert second["counts_match"] is True
        assert second["reconciled"] is True
        assert second["relationship_orphans"] == []
        assert second["duplicate_order_ids"] == ["ORD-DUP"]
        assert len(db.scalars(select(OpsOrder)).all()) == 2
        assert len(db.scalars(select(OpsDriver)).all()) == 1
        assert len(db.scalars(select(OpsCustomer)).all()) == 1
        assert len(db.scalars(select(OpsEvent)).all()) == 1
        assert db.get(OpsOrder, "rec-one").driver_source_ids_json == '["rec-driver"]'
        assert db.get(OpsOrder, "rec-one").customer_source_ids_json == '["rec-customer"]'


def test_relationship_reconciliation_rejects_missing_link_targets():
    payloads = {"customers": [], "orders": [
        _rec("rec-order", {"driver": ["rec-missing-driver"]})],
        "drivers": [], "deliveries": [], "events": []}
    assert relationship_orphans(payloads) == [{
        "table": "orders", "record_id": "rec-order", "field": "driver",
        "missing_ids": ["rec-missing-driver"],
    }]
