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
from .guides import router as guides_router

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
app.include_router(guides_router)
app.include_router(menu_router)
from .growth import (router as growth_router, migrate_brand_columns,
                     seed_brands_and_demos, seed_promos)
app.include_router(growth_router)
from .options import router as options_router
app.include_router(options_router)
from .drivers import router as drivers_router, seed_driver_profiles
app.include_router(drivers_router)
migrate_brand_columns()
seed_partners()
seed_menus()
from .menu import migrate_real_menus
migrate_real_menus()
seed_brands_and_demos()
seed_promos()
seed_driver_profiles()
from .dispatch import retention_sweep
retention_sweep(force=True)

_UI = Path(__file__).parent / "ui"
def _error_page(title: str, msg: str, status: int) -> HTMLResponse:
    return HTMLResponse(f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>GateWay Delivery</title>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;800&display=swap" rel="stylesheet">
<style>body{{font-family:'Archivo',system-ui,sans-serif;background:#f7f8fb;color:#16181b;
display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:20px;text-align:center}}
h1{{font-size:1.25rem;font-weight:800}}p{{color:#5a5e64;max-width:340px;line-height:1.6}}
a{{display:inline-block;margin-top:14px;background:#16337a;color:#fff;text-decoration:none;
padding:12px 22px;border-radius:10px;font-weight:800}}</style></head>
<body><div><div style="font-weight:900;font-size:1.5rem;margin-bottom:14px">Gate<span style="color:#d81f2a">Way</span></div>
<h1>{title}</h1><p>{msg}</p><a href="/">Back to GateWay</a></div></body></html>""", status_code=status)


def _wants_html(request) -> bool:
    if request.url.path.startswith(("/api/", "/v0/")):
        return False
    return "text/html" in request.headers.get("accept", "")


from starlette.exceptions import HTTPException as StarletteHTTPException


@app.exception_handler(StarletteHTTPException)
async def branded_http_errors(request, exc):
    if exc.status_code == 404 and _wants_html(request):
        return _error_page("That page doesn't exist",
                           "The link may be old or mistyped. Head back to the app and try from there.", 404)
    from fastapi.responses import JSONResponse
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.exception_handler(Exception)
async def branded_server_errors(request, exc):
    # The record never pretends: every unexpected failure is logged permanently.
    try:
        import json as _json
        from .models import Event
        db = SessionLocal()
        db.add(Event(event_type="system.error", entity_ref=request.url.path[:120],
                     tenant="gateway", actor="system",
                     payload=_json.dumps({"error": str(exc)[:300]})))
        db.commit()
        db.close()
    except Exception:
        pass
    if _wants_html(request):
        return _error_page("Something went wrong on our side",
                           "Your action was NOT completed. Give it another try in a minute — the issue has been logged.", 500)
    from fastapi.responses import JSONResponse
    return JSONResponse({"detail": "internal_error"}, status_code=500)


@app.get("/me", response_class=HTMLResponse)
def me_page():
    return (_UI / "me.html").read_text()


@app.get("/activity", response_class=HTMLResponse)
def activity_page():
    """A real order history — the Activity tab used to bounce to a single last
    order or dump you on the account page. Now it's its own surface: every
    order you've placed, one tap to track a live one or re-order a past one."""
    return (_UI / "activity.html").read_text()


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


@app.get("/team", response_class=HTMLResponse)
def team_page():
    """Team sign-in — moved OFF the consumer home (v1.1): a food court
    doesn't ask its customers for a work badge at the front door."""
    return _page("team.html")


@app.get("/courier", response_class=HTMLResponse)
def courier_page():
    """GateWay Courier — the flexible half of the model. The big apps only move
    food from partners they signed; we move what a neighbor actually needs moved."""
    return _page("courier.html")


@app.get("/support", response_class=HTMLResponse)
def support_page():
    return _page("support.html")


@app.get("/drive-with-us", response_class=HTMLResponse)
def drive_lead_page():
    return _page("lead-driver.html")


@app.get("/partner-with-us", response_class=HTMLResponse)
def merchant_lead_page():
    return _page("lead-merchant.html")


@app.get("/neighbor-fund", response_class=HTMLResponse)
def neighbor_fund_page():
    """The Neighbor Fund explainer — what round-up actually is, where the money
    goes, and our promise that GateWay takes nothing from it."""
    return _page("neighbor-fund.html")


@app.get("/order", response_class=HTMLResponse)
def order_form():
    """Public partner order form — posts to the canonical intake webhook."""
    return _page("order-form.html")


NUCLEUS_VERSION = "1.8.6"


@app.middleware("http")
async def timing_and_slow_log(request, call_next):
    import time as _t
    t0 = _t.perf_counter()
    response = await call_next(request)
    dur_ms = (_t.perf_counter() - t0) * 1000
    response.headers["Server-Timing"] = f"app;dur={dur_ms:.1f}"
    _METRICS["count"] += 1
    _METRICS["total_ms"] += dur_ms
    _METRICS["max_ms"] = max(_METRICS["max_ms"], dur_ms)
    if response.status_code >= 500:
        _METRICS["errors"] += 1
    # a request slower than 2s on a delivery board is an incident, not a stat
    if dur_ms > 2000 and not request.url.path.startswith("/static"):
        try:
            import json as _json
            from .models import Event
            db = SessionLocal()
            db.add(Event(event_type="system.slow_request", entity_ref=request.url.path[:120],
                         tenant="gateway", actor="system",
                         payload=_json.dumps({"ms": round(dur_ms)})))
            db.commit()
            db.close()
        except Exception:
            pass
    return response


_METRICS = {"count": 0, "total_ms": 0.0, "max_ms": 0.0, "errors": 0}


@app.get("/metrics")
def metrics():
    """Lightweight ops pulse — no PII, safe to hit from an uptime monitor.
    Now also summarizes slow requests from the last 24h so a latency incident is
    visible here, not just buried in the event log."""
    c = _METRICS["count"] or 1
    slow_24h = 0
    slow_paths: dict = {}
    try:
        import json as _json
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
        from .models import Event
        db = SessionLocal()
        cutoff = _dt.now(_tz.utc) - _td(hours=24)
        rows = (db.query(Event)
                .filter(Event.event_type == "system.slow_request",
                        Event.occurred_at >= cutoff).all())
        slow_24h = len(rows)
        for e in rows:
            try:
                ms = int(_json.loads(e.payload).get("ms", 0))
            except Exception:
                ms = 0
            # keep the worst ms seen per path
            if e.entity_ref not in slow_paths or ms > slow_paths[e.entity_ref]:
                slow_paths[e.entity_ref] = ms
        db.close()
    except Exception:
        pass
    worst = sorted(slow_paths.items(), key=lambda kv: kv[1], reverse=True)[:5]
    return {
        "requests": _METRICS["count"],
        "avg_ms": round(_METRICS["total_ms"] / c, 1),
        "max_ms": round(_METRICS["max_ms"], 1),
        "errors_5xx": _METRICS["errors"],
        "slow_requests_24h": slow_24h,
        "slowest_paths": [{"path": p, "ms": m} for p, m in worst],
        "version": NUCLEUS_VERSION,
    }


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
