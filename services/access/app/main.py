"""Nucleus Access Service — SKELETON (build-out: FSH-900 M2).
Will own: roles, grants, day-tokens (GWD driver day-sheet auth), API keys.
"""
from fastapi import FastAPI

app = FastAPI(title="Nucleus Access Service", version="0.0.1")


@app.get("/healthz")
def healthz():
    return {"ok": True, "service": "access", "status": "skeleton"}
