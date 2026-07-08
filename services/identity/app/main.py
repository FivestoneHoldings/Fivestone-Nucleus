"""Nucleus Identity Service — SKELETON (build-out: FSH-900 M2).
Will own: people, organizations, entity registry across all operating companies.
"""
from fastapi import FastAPI

app = FastAPI(title="Nucleus Identity Service", version="0.0.1")


@app.get("/healthz")
def healthz():
    return {"ok": True, "service": "identity", "status": "skeleton"}
