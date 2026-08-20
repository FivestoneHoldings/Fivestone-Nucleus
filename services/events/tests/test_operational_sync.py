import asyncio

from app import airtable_client as at
from app.db import SessionLocal
from app.operations_models import OperationalSyncQueue, OpsOrder
from app.operations_sync import enqueue, retry_pending, sync_health


def _record(record_id="rec-sync", total=2599):
    return {"id": record_id, "createdTime": "2026-08-20T10:00:00Z",
            "fields": {"order_id": "ORD-SYNC", "status": "received",
                       "total_cents": total, "customer_name_raw": "Sync Test"}}


def test_successful_mutation_is_applied_to_owned_operations_table():
    queue_id = enqueue("orders", _record(), "create")
    db = SessionLocal()
    try:
        assert db.get(OpsOrder, "rec-sync").total_cents == 2599
        queued = db.get(OperationalSyncQueue, queue_id)
        assert queued.status == "applied"
        assert queued.attempts == 1
    finally:
        db.close()


def test_transform_failure_remains_durable_and_visible_for_retry():
    queue_id = enqueue("orders", _record("rec-bad", "not-money"), "patch")
    db = SessionLocal()
    try:
        queued = db.get(OperationalSyncQueue, queue_id)
        assert queued.status == "retry"
        assert queued.last_error
    finally:
        db.close()
    assert sync_health()["pending"] >= 1
    retried = retry_pending()
    assert retried["attempted"] >= 1
    assert retried["remaining"] >= 1


def test_airtable_client_queues_the_success_response(monkeypatch):
    class Response:
        def json(self):
            return _record("rec-http")

    async def fake_request(*args, **kwargs):
        return Response()

    monkeypatch.setattr(at, "_request", fake_request)
    result = asyncio.run(at.create_record(at.ORDERS, {"order_id": "ORD-SYNC"}))
    assert result["id"] == "rec-http"
    db = SessionLocal()
    try:
        assert db.get(OpsOrder, "rec-http").order_id == "ORD-SYNC"
    finally:
        db.close()
