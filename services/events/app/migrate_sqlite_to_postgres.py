"""Copy the legacy owned SQLite tables into the configured database.

The source is opened independently from ``DATABASE_URL``. The target schema is
created from the application's SQLAlchemy models, and rows are upserted by each
table's primary key inside one transaction. No source rows are changed.

Usage from ``services/events``::

    python -m app.migrate_sqlite_to_postgres --source /secure/nucleus_events.db --dry-run
    python -m app.migrate_sqlite_to_postgres --source /secure/nucleus_events.db --apply
"""
import argparse
import json
from pathlib import Path

from sqlalchemy import MetaData, and_, create_engine, func, select

from . import models  # noqa: F401 - registers all owned tables on Base.metadata
from .db import Base, engine as target_engine


def _source_engine(path: str):
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise RuntimeError(f"SQLite source does not exist: {source}")
    return create_engine(f"sqlite:///{source.as_posix()}")


def inventory(path: str) -> dict[str, int]:
    engine = _source_engine(path)
    metadata = MetaData()
    metadata.reflect(bind=engine)
    with engine.connect() as connection:
        return {
            table.name: connection.scalar(select(func.count()).select_from(table)) or 0
            for table in metadata.sorted_tables
            if table.name != "sqlite_sequence"
        }


def copy_owned_tables(path: str, target=target_engine) -> dict:
    """Idempotently copy model-owned rows and verify table counts."""
    source = _source_engine(path)
    Base.metadata.create_all(bind=target)
    source_meta = MetaData()
    target_meta = MetaData()
    source_meta.reflect(bind=source)
    target_meta.reflect(bind=target)

    shared = sorted(set(source_meta.tables) & set(Base.metadata.tables) & set(target_meta.tables))
    source_counts: dict[str, int] = {}
    target_counts: dict[str, int] = {}

    with source.connect() as source_connection, target.begin() as target_connection:
        for name in shared:
            source_table = source_meta.tables[name]
            target_table = target_meta.tables[name]
            target_columns = {column.name for column in target_table.columns}
            primary_keys = [column.name for column in target_table.primary_key.columns]
            if not primary_keys:
                raise RuntimeError(f"Cannot safely migrate {name}: table has no primary key")

            rows = [
                {key: value for key, value in dict(row._mapping).items() if key in target_columns}
                for row in source_connection.execute(select(source_table))
            ]
            source_counts[name] = len(rows)
            for row in rows:
                if any(row.get(key) is None for key in primary_keys):
                    raise RuntimeError(f"Cannot safely migrate {name}: null primary key")
                match = and_(*(target_table.c[key] == row[key] for key in primary_keys))
                exists = target_connection.scalar(select(func.count()).select_from(target_table).where(match))
                if exists:
                    values = {key: value for key, value in row.items() if key not in primary_keys}
                    if values:
                        target_connection.execute(target_table.update().where(match).values(**values))
                else:
                    target_connection.execute(target_table.insert().values(**row))

            target_counts[name] = (
                target_connection.scalar(select(func.count()).select_from(target_table)) or 0
            )

    counts_match = source_counts == target_counts
    report = {
        "tables": shared,
        "source_counts": source_counts,
        "target_counts": target_counts,
        "counts_match": counts_match,
    }
    if not counts_match:
        raise RuntimeError(f"SQLite reconciliation failed: {report}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.dry_run:
        report = {"mode": "dry-run", "source_counts": inventory(args.source)}
    else:
        report = {"mode": "apply", **copy_owned_tables(args.source)}
    print(json.dumps(report, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
