"""Board access, per person.

Before this, one ADMIN_KEY protected all 46 board endpoints, shared by
whoever needed in. That's fine for a founder working alone. It stops being
fine the moment a second person needs access, because there is no way to
revoke ONE person without rotating the key and re-issuing it to everyone else
— which is disruptive enough that in practice nobody does it, so an
ex-employee, a lost phone, or a leaked screenshot stays valid forever.

Design:

  * ADMIN_KEY (the environment variable) is still valid, always, as the
    founder's own master key. There is always a way in even if the database
    holding per-person keys is unreachable — a login system that can lock out
    its own owner is worse than the problem it solves.

  * Every other person gets their own named key, minted by the founder,
    independently revocable. Revoking Malcolm's assistant's key does nothing
    to Malcolm's, and vice versa.

  * Keys are stored HASHED (sha256), the same posture as a password — the
    database is never a list of live credentials waiting to be read.

  * Every check records who it was and when, so "who did this" has an answer
    that isn't just "the board."
"""
import hashlib
import secrets
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import Column, String, DateTime, Boolean
from sqlalchemy.orm import Session

from .db import Base, SessionLocal


class BoardAccess(Base):
    __tablename__ = "board_access"

    id = Column(String(36), primary_key=True, default=lambda: secrets.token_hex(16))
    name = Column(String(80), nullable=False, default="")
    key_hash = Column(String(64), nullable=False, unique=True, index=True)
    key_hint = Column(String(8), nullable=False, default="")   # last 4 chars, for the UI list
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _admin_key() -> str:
    import os
    return os.environ.get("ADMIN_KEY", "")


def check_key(key: str) -> str:
    """Validate a board key. Returns the name to attribute actions to.

    Raises 403 on anything invalid, missing, or revoked — same failure mode
    regardless of WHY it failed, so a bad key can't be used to fingerprint
    whether a name exists in the system."""
    key = str(key or "")
    admin = _admin_key()
    if admin and secrets.compare_digest(key, admin):
        return "Founder"
    if not key:
        raise HTTPException(403, "Bad board key")
    db: Session = SessionLocal()
    try:
        row = (db.query(BoardAccess)
               .filter(BoardAccess.key_hash == _hash(key)).first())
        if not row or row.revoked_at is not None:
            raise HTTPException(403, "Bad board key")
        row.last_used_at = datetime.now(timezone.utc)
        db.commit()
        return row.name or "Team member"
    finally:
        db.close()


def mint_key(name: str) -> dict:
    """Create a new named board key. Returns it ONCE — like any real credential,
    it's shown at creation and never again; only the hash is kept."""
    raw = "gwb-" + secrets.token_urlsafe(24)
    db: Session = SessionLocal()
    try:
        row = BoardAccess(name=(name or "Team member")[:80],
                          key_hash=_hash(raw), key_hint=raw[-4:])
        db.add(row)
        db.commit()
        return {"id": row.id, "name": row.name, "key": raw}
    finally:
        db.close()


def revoke_key(access_id: str) -> bool:
    db: Session = SessionLocal()
    try:
        row = db.get(BoardAccess, access_id)
        if not row:
            return False
        row.revoked_at = datetime.now(timezone.utc)
        db.commit()
        return True
    finally:
        db.close()


def list_keys() -> list:
    """Never returns the key itself — only what's needed to recognize and
    manage it: name, last 4 characters, when it was used, whether it's live."""
    db: Session = SessionLocal()
    try:
        rows = db.query(BoardAccess).order_by(BoardAccess.created_at.desc()).all()
        return [{"id": r.id, "name": r.name, "hint": r.key_hint,
                "created_at": r.created_at.isoformat() if r.created_at else "",
                "last_used_at": r.last_used_at.isoformat() if r.last_used_at else "",
                "revoked": r.revoked_at is not None} for r in rows]
    finally:
        db.close()
