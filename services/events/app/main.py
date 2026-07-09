"""Nucleus Event Service v0 — the truth, as a service.
Append-only: POST and GET only. There is no PUT, PATCH, or DELETE, by law (N-2).
"""
from datetime import datetime, timezone
from fastapi import FastAPI, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import select
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from .db import SessionLocal, Base, engine, get_db
from .models import Event
from .schemas import EventIn, EventOut
from .dispatch import router as dispatch_router
from .intake import router as intake_router
from .identity import router as identity_router, seed_partners
from .menu import router as menu_router, seed_menus
from .track import router as track_router
from .kitchen import router as kitchen_router

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Nucleus API",
    version="0.2.0",
    description="Fivestone Nucleus: append-only Event Service + GateWay Dispatch v0 surfaces (ADR-008 monolith; split at M3).",
)

app.include_router(dispatch_router)
app.include_router(intake_router)
app.include_router(identity_router)
app.include_router(track_router)
app.include_router(kitchen_router)
app.include_router(menu_router)
seed_partners()
seed_menus()

_UI = Path(__file__).parent / "ui"
@app.get("/", response_class=HTMLResponse)
def home():
    return (_UI / "home.html").read_text()


app.mount("/static", StaticFiles(directory=str(_UI / "static")), name="static")


def _page(name: str) -> str:
    return (_UI / name).read_text()


@app.get("/driver/{day_token}", response_class=HTMLResponse)
def driver_ui(day_token: str):
    """Driver day-sheet (GWD-004): the three buttons live here."""
    return _page("driver.html")


@app.get("/board/{key}", response_class=HTMLResponse)
def board_ui(key: str):
    """Founder command board."""
    return _page("board.html")


@app.get("/order", response_class=HTMLResponse)
def order_form():
    """Public partner order form — posts to the canonical intake webhook."""
    return _page("order-form.html")


NUCLEUS_VERSION = "0.20"


@app.get("/healthz")
def healthz():
    db_ok = True
    try:
        from sqlalchemy import text
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
    except Exception:
        db_ok = False
    return {"ok": db_ok, "service": "nucleus", "version": NUCLEUS_VERSION,
            "db": "up" if db_ok else "DOWN",
            "time": datetime.now(timezone.utc).isoformat()}


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
