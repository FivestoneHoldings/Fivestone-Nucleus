from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.migrate_sqlite_to_postgres import copy_owned_tables, inventory
from app.models import Partner, PromoCode


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
