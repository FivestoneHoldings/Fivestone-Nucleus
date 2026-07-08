"""Nucleus Event Service v0 — the truth, as a service.
Append-only: POST and GET only. There is no PUT, PATCH, or DELETE, by law (N-2).
"""
from datetime import datetime, timezone
from fastapi import FastAPI, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import select
from .db import Base, engine, get_db
from .models import Event
from .schemas import EventIn, EventOut

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Nucleus Event Service",
    version="0.1.0",
    description="Append-only event log for all Fivestone operating companies. The record never pretends.",
)


@app.get("/healthz")
def healthz():
    return {"ok": True, "service": "events", "time": datetime.now(timezone.utc).isoformat()}


@app.post("/v0/events", response_model=EventOut, status_code=201)
def append_event(body: EventIn, db: Session = Depends(get_db)):
    ev = Event(
        event_type=body.event_type,
        entity_ref=body.entity_ref,
        tenant=body.tenant,
        actor=body.actor,
        payload=body.payload,
        **({"occurred_at": body.occurred_at} if body.occurred_at else {}),
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev


@app.get("/v0/events", response_model=list[EventOut])
def list_events(
    entity_ref: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    tenant: str | None = Query(default=None),
    limit: int = Query(default=100, le=1000),
    db: Session = Depends(get_db),
):
    stmt = select(Event).order_by(Event.occurred_at.desc()).limit(limit)
    if entity_ref:
        stmt = stmt.filter(Event.entity_ref == entity_ref)
    if event_type:
        stmt = stmt.filter(Event.event_type == event_type)
    if tenant:
        stmt = stmt.filter(Event.tenant == tenant)
    return db.execute(stmt).scalars().all()
