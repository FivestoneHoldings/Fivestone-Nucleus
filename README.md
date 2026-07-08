# fivestone-nucleus
The Nucleus platform — Fivestone Holdings' enterprise operating system.
Governed by FSH-100 (Nucleus Constitution) and FSH-200 (Technical Blueprint). Stack per ADR-007: Python 3.12 · FastAPI · PostgreSQL · Railway.

## Services
- **services/events** — Append-only Event Service (N-2: the record never pretends). FIRST built; everything writes here.
- **services/identity** — Identity Service (people, orgs, entities). Skeleton.
- **services/access** — Access Service (roles, grants, tokens). Skeleton.

## Local dev
```
cd services/events
pip install -r requirements.txt
uvicorn app.main:app --reload
pytest
```
Uses SQLite locally; DATABASE_URL env var switches to PostgreSQL in deployment (Railway).
