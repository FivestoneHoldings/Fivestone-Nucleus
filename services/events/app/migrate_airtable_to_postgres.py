"""Idempotent Airtable -> owned database backfill and reconciliation.

Usage from ``services/events``::

    python -m app.migrate_airtable_to_postgres --dry-run
    python -m app.migrate_airtable_to_postgres --apply

The command never deletes or edits Airtable records and never deletes target
rows. Re-running it safely updates rows by Airtable record ID.
"""
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import airtable_client as at
from .db import Base, SessionLocal, engine
from .operations_models import (
    AirtableMigrationRun, OpsCustomer, OpsDelivery, OpsDriver, OpsEvent, OpsOrder)


TABLE_MODELS = {
    "customers": (at.CUSTOMERS, OpsCustomer),
    "orders": (at.ORDERS, OpsOrder),
    "drivers": (at.DRIVERS, OpsDriver),
    "deliveries": (at.DELIVERIES, OpsDelivery),
    "events": (at.EVENTS, OpsEvent),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dt(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _select(value) -> str:
    return str(value.get("name", "")) if isinstance(value, dict) else str(value or "")


def _link_ids(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item.get("id")) for item in value if isinstance(item, dict) and item.get("id")]


def _json(value) -> str:
    return json.dumps(value if value is not None else [], sort_keys=True, default=str)


def _base(record: dict) -> dict:
    return {
        "source_record_id": record["id"],
        "source_created_at": _dt(record.get("createdTime")),
        "source_synced_at": _now(),
        "raw_json": json.dumps(record, sort_keys=True, default=str),
    }


def _customer(record: dict) -> OpsCustomer:
    f = record.get("fields", {})
    return OpsCustomer(**_base(record), customer_id=str(f.get("customer_id", "")),
        display_name=str(f.get("display_name", "")), customer_type=_select(f.get("customer_type")),
        contact_name=str(f.get("contact_name", "")), phone=str(f.get("phone", "")),
        email=str(f.get("email", "")), pickup_address_default=str(f.get("pickup_address_default", "")),
        status=_select(f.get("status")), notes=str(f.get("notes", "")),
        created_at_utc=_dt(f.get("created_at_utc")), order_source_ids_json=_json(_link_ids(f.get("orders"))))


def _driver(record: dict) -> OpsDriver:
    f = record.get("fields", {})
    return OpsDriver(**_base(record), driver_id=str(f.get("driver_id", "")),
        display_name=str(f.get("display_name", "")), phone=str(f.get("phone", "")),
        email=str(f.get("email", "")), status=_select(f.get("status")),
        day_token=str(f.get("day_token", "")), token_expires=_dt(f.get("token_expires")),
        notes=str(f.get("notes", "")), order_source_ids_json=_json(_link_ids(f.get("orders"))),
        delivery_source_ids_json=_json(_link_ids(f.get("deliveries"))))


def _order(record: dict) -> OpsOrder:
    f = record.get("fields", {})
    return OpsOrder(**_base(record), order_id=str(f.get("order_id", "")), status=_select(f.get("status")),
        source_channel=_select(f.get("source_channel")), pickup_address=str(f.get("pickup_address", "")),
        dropoff_address=str(f.get("dropoff_address", "")),
        dropoff_contact_name=str(f.get("dropoff_contact_name", "")),
        dropoff_contact_phone=str(f.get("dropoff_contact_phone", "")),
        items_description=str(f.get("items_description", "")),
        special_instructions=str(f.get("special_instructions", "")),
        requested_for=_dt(f.get("requested_for")), promised_window_start=_dt(f.get("promised_window_start")),
        promised_window_end=_dt(f.get("promised_window_end")), fingerprint=str(f.get("fingerprint", "")),
        received_at=_dt(f.get("received_at")), confirmed_at=_dt(f.get("confirmed_at")),
        assigned_at=_dt(f.get("assigned_at")), in_transit_at=_dt(f.get("in_transit_at")),
        delivered_at=_dt(f.get("delivered_at")), closed_at=_dt(f.get("closed_at")),
        cancelled_at=_dt(f.get("cancelled_at")), failed_at=_dt(f.get("failed_at")),
        cancel_reason=str(f.get("cancel_reason", "")), fail_reason=str(f.get("fail_reason", "")),
        needs_review=bool(f.get("needs_review", False)), ai_notes=str(f.get("ai_notes", "")),
        customer_name_raw=str(f.get("customer_name_raw", "")),
        customer_phone_raw=str(f.get("customer_phone_raw", "")),
        partner_code=str(f.get("partner_code", "")), subtotal_cents=int(f.get("subtotal_cents") or 0),
        fee_cents=int(f.get("fee_cents") or 0), total_cents=int(f.get("total_cents") or 0),
        tip_cents=int(f.get("tip_cents") or 0),
        customer_source_ids_json=_json(_link_ids(f.get("customer"))),
        driver_source_ids_json=_json(_link_ids(f.get("driver"))),
        delivery_source_ids_json=_json(_link_ids(f.get("deliveries"))))


def _delivery(record: dict) -> OpsDelivery:
    f = record.get("fields", {})
    return OpsDelivery(**_base(record), delivery_id=str(f.get("delivery_id", "")),
        attempt_number=int(f.get("attempt_number") or 0), stop_sequence=int(f.get("stop_sequence") or 0),
        picked_up_at=_dt(f.get("picked_up_at")), delivered_at=_dt(f.get("delivered_at")),
        failed_at=_dt(f.get("failed_at")), fail_reason=str(f.get("fail_reason", "")),
        proof_photo_json=_json(f.get("proof_photo", [])), notes=str(f.get("notes", "")),
        order_source_ids_json=_json(_link_ids(f.get("order"))),
        driver_source_ids_json=_json(_link_ids(f.get("driver"))))


def _event(record: dict) -> OpsEvent:
    f = record.get("fields", {})
    return OpsEvent(**_base(record), event_id=str(f.get("event_id", "")),
        event_type=str(f.get("event_type", "")), entity_ref=str(f.get("entity_ref", "")),
        occurred_at=_dt(f.get("occurred_at")), actor=str(f.get("actor", "")),
        payload=str(f.get("payload", "")))


BUILDERS = {"customers": _customer, "orders": _order, "drivers": _driver,
            "deliveries": _delivery, "events": _event}


def apply_payloads(payloads: dict[str, list[dict]], db: Session) -> dict:
    """Upsert a complete Airtable snapshot and return reconciliation facts."""
    for name, records in payloads.items():
        for record in records:
            db.merge(BUILDERS[name](record))
    db.flush()

    target_counts = {}
    for name, (_, model) in TABLE_MODELS.items():
        target_counts[name] = db.scalar(select(func.count()).select_from(model)) or 0
    source_counts = {name: len(records) for name, records in payloads.items()}
    ids = [str(r.get("fields", {}).get("order_id", "")) for r in payloads["orders"]]
    duplicates = sorted(k for k, count in Counter(ids).items() if k and count > 1)
    return {"source_counts": source_counts, "target_counts": target_counts,
            "duplicate_order_ids": duplicates,
            "counts_match": source_counts == target_counts}


async def fetch_payloads() -> dict[str, list[dict]]:
    if not at.configured():
        raise RuntimeError("AIRTABLE_PAT is not configured")
    results = await asyncio.gather(*(at.list_all_records(table) for table, _ in TABLE_MODELS.values()))
    return {name: records for name, records in zip(TABLE_MODELS, results)}


async def run(apply: bool) -> dict:
    payloads = await fetch_payloads()
    if not apply:
        ids = [str(r.get("fields", {}).get("order_id", "")) for r in payloads["orders"]]
        return {"mode": "dry-run", "source_counts": {k: len(v) for k, v in payloads.items()},
                "duplicate_order_ids": sorted(k for k, n in Counter(ids).items() if k and n > 1)}

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    run_row = AirtableMigrationRun(id=str(uuid.uuid4()), started_at=_now(), status="running")
    try:
        db.add(run_row)
        report = apply_payloads(payloads, db)
        run_row.finished_at = _now()
        run_row.status = "verified" if report["counts_match"] else "count_mismatch"
        run_row.source_counts_json = _json(report["source_counts"])
        run_row.target_counts_json = _json(report["target_counts"])
        run_row.duplicate_order_ids_json = _json(report["duplicate_order_ids"])
        db.commit()
        if not report["counts_match"]:
            raise RuntimeError(f"Reconciliation failed: {report}")
        return {"mode": "apply", **report, "migration_run_id": run_row.id}
    except Exception as exc:
        db.rollback()
        raise RuntimeError(f"Migration aborted without cutover: {exc}") from exc
    finally:
        db.close()
        await at.aclose()


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(apply=args.apply)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
