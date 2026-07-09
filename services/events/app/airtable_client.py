"""Airtable data layer for GateWay Dispatch v0.
Server-side only — the PAT lives in Railway env vars, never in a browser.
Table IDs are canonical per BUILD-LOG-v0-base.md.
"""
import asyncio
import os
import httpx

RETRY_STATUSES = {429, 500, 502, 503, 504}


async def _request(method: str, url: str, **kw) -> httpx.Response:
    """3 attempts with exponential backoff on rate limits / transient 5xx."""
    last: httpx.Response | None = None
    for attempt in range(3):
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.request(method, url, **kw)
        if r.status_code not in RETRY_STATUSES:
            r.raise_for_status()
            return r
        last = r
        await asyncio.sleep(0.5 * (2 ** attempt))  # 0.5s, 1s, 2s
    last.raise_for_status()
    return last

BASE = "appT0k6nqQC490WTg"
ORDERS = "tblxkQlInSdBwIeLR"
DRIVERS = "tblmRlBF50oAsP4EJ"
EVENTS = "tblNtaoMbDWYnCjEe"

API = "https://api.airtable.com/v0"


def _headers() -> dict:
    pat = os.environ.get("AIRTABLE_PAT", "")
    return {"Authorization": f"Bearer {pat}", "Content-Type": "application/json"}


def configured() -> bool:
    return bool(os.environ.get("AIRTABLE_PAT"))


async def list_records(table: str, formula: str = "", fields: list[str] | None = None,
                       max_records: int = 100) -> list[dict]:
    params: list[tuple] = [("maxRecords", str(max_records))]
    if formula:
        params.append(("filterByFormula", formula))
    for f in fields or []:
        params.append(("fields[]", f))
    r = await _request("GET", f"{API}/{BASE}/{table}", headers=_headers(), params=params)
    return r.json().get("records", [])


async def patch_record(table: str, record_id: str, fields: dict) -> dict:
    r = await _request("PATCH", f"{API}/{BASE}/{table}/{record_id}",
                       headers=_headers(), json={"fields": fields})
    return r.json()


async def create_record(table: str, fields: dict) -> dict:
    r = await _request("POST", f"{API}/{BASE}/{table}",
                       headers=_headers(), json={"fields": fields})
    return r.json()
