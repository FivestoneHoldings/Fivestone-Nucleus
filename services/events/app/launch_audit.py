"""Read-only launch audit for a deployed Patch/GateWay service.

The founder credential is read from ``ADMIN_KEY`` and never printed. This
command does not create or mutate orders, drivers, partners, or database rows.

Usage::

    ADMIN_KEY=... python -m app.launch_audit \
      --base-url https://fivestone-nucleus-production.up.railway.app
"""
from __future__ import annotations

import argparse
import json
import os
from urllib.parse import quote, urlparse

import httpx


def _check(checks: list[dict], area: str, ok: bool, detail: str) -> None:
    checks.append({"area": area, "ok": bool(ok), "detail": detail})


def audit(client, admin_key: str) -> dict:
    """Return redacted, machine-checkable launch facts using GET requests only."""
    checks: list[dict] = []

    try:
        response = client.get("/healthz")
        health = response.json() if response.status_code == 200 else {}
        _check(checks, "Health", response.status_code == 200 and health.get("ok") is True,
               f"HTTP {response.status_code} · version {health.get('version', '?')}")
        _check(checks, "PostgreSQL durability",
               health.get("db_backend") == "postgresql" and health.get("db_durable") is True,
               f"backend={health.get('db_backend', '?')} durable={health.get('db_durable', False)}")
    except Exception as exc:
        _check(checks, "Health", False, f"request failed: {type(exc).__name__}")
        _check(checks, "PostgreSQL durability", False, "health response unavailable")

    try:
        response = client.get("/api/diag")
        diag = response.json() if response.status_code == 200 else {}
        configured = bool(diag.get("airtable_pat_set") and diag.get("admin_key_set"))
        _check(checks, "Required integrations", response.status_code == 200 and configured,
               f"Airtable={bool(diag.get('airtable_pat_set'))} founder={bool(diag.get('admin_key_set'))}")
        headers_ok = (response.headers.get("cache-control") == "no-store" and
                      response.headers.get("x-robots-tag") == "noindex, nofollow")
        _check(checks, "Operational response privacy", headers_ok,
               "no-store and noindex headers present" if headers_ok else "required headers missing")
    except Exception as exc:
        _check(checks, "Required integrations", False, f"request failed: {type(exc).__name__}")
        _check(checks, "Operational response privacy", False, "diagnostic response unavailable")

    surface_codes = {}
    for path, label in (("/", "home"), ("/order", "checkout"), ("/courier", "courier")):
        try:
            surface_codes[label] = client.get(path).status_code
        except Exception:
            surface_codes[label] = 0
    _check(checks, "Customer surfaces", all(code == 200 for code in surface_codes.values()),
           " · ".join(f"{name}={code}" for name, code in surface_codes.items()))

    try:
        response = client.get("/v0/partners")
        payload = response.json() if response.status_code == 200 else {}
        partners = payload.get("partners", []) if isinstance(payload, dict) else []
        _check(checks, "Partner discovery", response.status_code == 200 and bool(partners),
               f"{len(partners)} partner(s) available")
    except Exception as exc:
        _check(checks, "Partner discovery", False, f"request failed: {type(exc).__name__}")

    readiness = {}
    if not admin_key:
        _check(checks, "Founder readiness gate", False, "ADMIN_KEY is not configured for the audit")
    else:
        try:
            # quote() prevents path-shaping characters in a generated secret;
            # neither the URL nor the response is included in the report.
            response = client.get(f"/api/board/{quote(admin_key, safe='')}/readiness")
            readiness = response.json() if response.status_code == 200 else {}
            blockers = readiness.get("blocking", []) if isinstance(readiness, dict) else []
            _check(checks, "Founder readiness gate",
                   response.status_code == 200 and readiness.get("ready_to_take_orders") is True,
                   "ready" if not blockers and response.status_code == 200
                   else f"{len(blockers)} blocking area(s)")
        except Exception as exc:
            _check(checks, "Founder readiness gate", False,
                   f"request failed: {type(exc).__name__}")

    blocking = [item["area"] for item in checks if not item["ok"]]
    return {
        "ready": not blocking,
        "checks": checks,
        "blocking": blocking,
        "readiness_blocking": readiness.get("blocking", []) if isinstance(readiness, dict) else [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Patch launch audit")
    parser.add_argument("--base-url", default=os.environ.get(
        "PATCH_BASE_URL", "https://fivestone-nucleus-production.up.railway.app"))
    args = parser.parse_args()
    parsed = urlparse(args.base_url)
    is_local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (parsed.scheme == "http" and is_local):
        raise SystemExit("Refusing a non-HTTPS remote base URL")
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=20,
                      follow_redirects=False) as client:
        report = audit(client, os.environ.get("ADMIN_KEY", ""))
    print(json.dumps(report, indent=2, sort_keys=True))
    raise SystemExit(0 if report["ready"] else 1)


if __name__ == "__main__":
    main()
