"""Durable dual-write bridge for the final Airtable operational cutover."""
from datetime import datetime, timezone
import json
import os
import uuid

from sqlalchemy import func, select

from .db import SessionLocal
from .operations_models import OperationalSyncQueue


def enabled() -> bool:
    return os.environ.get("OPERATIONS_SYNC_ENABLED", "true").lower() in {"1", "true", "yes"}


def _builder(table_name: str):
    # Imported lazily to avoid an import cycle: the migration module uses the
    # Airtable client to fetch its initial snapshot.
    from .migrate_airtable_to_postgres import BUILDERS
    return BUILDERS[table_name]


def enqueue(table_name: str, record: dict, action: str) -> str | None:
    if not enabled() or table_name not in {"customers", "orders", "drivers", "deliveries", "events"}:
        return None
    record_id = str(record.get("id", ""))
    if not record_id:
        return None
    queue_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        db.add(OperationalSyncQueue(id=queue_id, table_name=table_name,
                                    source_record_id=record_id, action=action,
                                    raw_json=json.dumps(record, separators=(",", ":")),
                                    status="pending", attempts=0))
        db.commit()
    finally:
        db.close()
    apply_one(queue_id)
    return queue_id


def apply_one(queue_id: str) -> bool:
    db = SessionLocal()
    try:
        row = db.get(OperationalSyncQueue, queue_id)
        if not row or row.status == "applied":
            return bool(row)
        row.attempts += 1
        record = json.loads(row.raw_json)
        db.merge(_builder(row.table_name)(record))
        row.status = "applied"
        row.last_error = ""
        row.applied_at = datetime.now(timezone.utc)
        db.commit()
        return True
    except Exception as exc:
        db.rollback()
        failed = db.get(OperationalSyncQueue, queue_id)
        if failed:
            failed.attempts += 1
            failed.status = "retry"
            failed.last_error = str(exc)[:1000]
            db.commit()
        return False
    finally:
        db.close()


def retry_pending(limit: int = 200) -> dict:
    db = SessionLocal()
    try:
        ids = list(db.scalars(select(OperationalSyncQueue.id).where(
            OperationalSyncQueue.status.in_(("pending", "retry")))
            .order_by(OperationalSyncQueue.created_at).limit(limit)))
    finally:
        db.close()
    applied = sum(1 for queue_id in ids if apply_one(queue_id))
    return {"attempted": len(ids), "applied": applied, "remaining": sync_health()["pending"]}


def sync_health() -> dict:
    db = SessionLocal()
    try:
        pending = db.scalar(select(func.count()).select_from(OperationalSyncQueue).where(
            OperationalSyncQueue.status.in_(("pending", "retry")))) or 0
        failed = db.query(OperationalSyncQueue).filter(
            OperationalSyncQueue.status == "retry").order_by(
            OperationalSyncQueue.created_at.desc()).limit(10).all()
        return {"enabled": enabled(), "pending": pending,
                "recent_failures": [{"id": r.id, "table": r.table_name,
                                     "record_id": r.source_record_id,
                                     "attempts": r.attempts,
                                     "error": r.last_error} for r in failed]}
    finally:
        db.close()
