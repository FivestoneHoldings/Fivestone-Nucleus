from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.migrate_sqlite_to_postgres import copy_owned_tables, inventory
from app.models import Event, Partner, PromoCode


def test_legacy_sqlite_copy_is_idempotent(tmp_path: Path):
    source_path = tmp_path / "source.db"
    source = create_engine(f"sqlite:///{source_path.as_posix()}")
    target = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(source)
    with Session(source) as db:
        db.add(Partner(code="flower-shop", display_name="Flower Shop"))
        db.add(PromoCode(code="WELCOME", kind="cents", value=500))
        db.commit()

    assert inventory(str(source_path))["partners"] == 1
    first = copy_owned_tables(str(source_path), target)
    second = copy_owned_tables(str(source_path), target)
    assert first["counts_match"] is True
    assert second["counts_match"] is True

    with Session(target) as db:
        assert len(db.scalars(select(Partner)).all()) == 1
        assert len(db.scalars(select(PromoCode)).all()) == 1


def test_recovered_event_history_merges_without_copying_duplicate_seed_data(tmp_path: Path):
    current_path = tmp_path / "current.db"
    recovery_path = tmp_path / "recovery.db"
    current = create_engine(f"sqlite:///{current_path.as_posix()}")
    recovery = create_engine(f"sqlite:///{recovery_path.as_posix()}")
    target = create_engine("sqlite:///:memory:")
    for engine in (current, recovery):
        Base.metadata.create_all(engine)
    with Session(current) as db:
        db.add(Partner(code="merchant", display_name="Current Merchant"))
        db.add(Event(id="event-current", event_type="order.received", entity_ref="ORD-NEW"))
        db.commit()
    with Session(recovery) as db:
        db.add(Partner(code="merchant", display_name="Stale Merchant"))
        db.add(Event(id="event-recovered", event_type="order.received", entity_ref="ORD-OLD"))
        db.commit()

    copy_owned_tables(str(current_path), target)
    report = copy_owned_tables(str(recovery_path), target,
                               table_names={"events"}, allow_target_extras=True)
    assert report["counts_match"] is False
    assert report["source_rows_present"] is True
    assert report["reconciled"] is True
    with Session(target) as db:
        assert db.get(Partner, "merchant").display_name == "Current Merchant"
        assert {event.id for event in db.scalars(select(Event)).all()} == {
            "event-current", "event-recovered"}
