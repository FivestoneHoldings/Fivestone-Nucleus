"""Database layer — Nucleus Event Service.
SQLite for local dev; PostgreSQL via DATABASE_URL in deployment (ADR-007).
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./nucleus_events.db")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

DB_BACKEND = "sqlite" if DATABASE_URL.startswith("sqlite") else "postgresql"
# SQLite is suitable for local development. In production it is only durable
# when an operator has explicitly attached and declared a persistent volume.
DB_DURABLE = DB_BACKEND == "postgresql" or (
    os.environ.get("SQLITE_DURABLE_VOLUME", "").lower() in {"1", "true", "yes"}
)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
