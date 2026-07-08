"""Airtable data layer for GateWay Dispatch v0.
Server-side only — the PAT lives in Railway env vars, never in a browser.
Table IDs are canonical per BUILD-LOG-v0-base.md.
"""
import os
import httpx

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
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{API}/{BASE}/{table}", headers=_headers(), params=params)
        r.raise_for_status()
        return r.json().get("records", [])


async def patch_record(table: str, record_id: str, fields: dict) -> dict:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.patch(f"{API}/{BASE}/{table}/{record_id}",
                          headers=_headers(), json={"fields": fields})
        r.raise_for_status()
        return r.json()


async def create_record(table: str, fields: dict) -> dict:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{API}/{BASE}/{table}",
                         headers=_headers(), json={"fields": fields})
        r.raise_for_status()
        return r.json()
