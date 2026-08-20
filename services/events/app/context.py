"""Official local context, isolated from transactional order truth.

The National Weather Service is used because it is authoritative, open, and
requires no customer data or commercial API key. A 15-minute cache is far
slower than NWS's documented 30-second maximum request cadence.
"""
from datetime import datetime, timezone
import time

from fastapi import APIRouter
import httpx

router = APIRouter()
NWS_ALERTS = "https://api.weather.gov/alerts/active?point=35.9606,-83.9207"
NWS_DOCS = "https://www.weather.gov/documentation/services-web-alerts"
HEADERS = {"User-Agent": "PatchDelivery/1.10 (fivestone-nucleus-production.up.railway.app)",
           "Accept": "application/geo+json"}
_CACHE: dict = {"at": 0.0, "payload": None}
_ROAD_EVENTS = ("tornado", "flood", "ice", "snow", "winter", "thunderstorm",
                "high wind", "dense fog", "flash flood")


async def _fetch_json() -> dict:
    async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=3.0)) as client:
        response = await client.get(NWS_ALERTS, headers=HEADERS)
        response.raise_for_status()
        return response.json()


def _impact(alerts: list[dict]) -> dict:
    affecting = [a for a in alerts if any(word in a["event"].lower() for word in _ROAD_EVENTS)]
    if not affecting:
        return {"level": "normal", "headline": "Normal delivery conditions",
                "message": "No active National Weather Service road-impact alerts for Knoxville."}
    severe = any(a["severity"].lower() in {"severe", "extreme"} for a in affecting)
    names = ", ".join(dict.fromkeys(a["event"] for a in affecting[:3]))
    if severe:
        return {"level": "high", "headline": "Weather may delay or pause delivery",
                "message": f"Active {names}. Patch will confirm safe timing before dispatch."}
    return {"level": "watch", "headline": "Allow extra delivery time",
            "message": f"Active {names}. Drivers may use safer routes and need more time."}


def _parse(raw: dict) -> dict:
    alerts = []
    for feature in raw.get("features", [])[:20]:
        p = feature.get("properties", {})
        alerts.append({"id": str(feature.get("id", "")), "event": str(p.get("event", "Alert"))[:100],
                       "severity": str(p.get("severity", "Unknown"))[:30],
                       "urgency": str(p.get("urgency", "Unknown"))[:30],
                       "headline": str(p.get("headline", ""))[:300],
                       "area": str(p.get("areaDesc", ""))[:300],
                       "ends": p.get("ends") or p.get("expires")})
    return {"available": True, "stale": False, "source": "National Weather Service",
            "source_url": NWS_DOCS, "checked_at": datetime.now(timezone.utc).isoformat(),
            "alerts": alerts, "delivery_impact": _impact(alerts)}


async def local_context(force: bool = False) -> dict:
    now = time.monotonic()
    if not force and _CACHE["payload"] is not None and now - _CACHE["at"] < 900:
        return _CACHE["payload"]
    try:
        payload = _parse(await _fetch_json())
        _CACHE.update(at=now, payload=payload)
        return payload
    except Exception:
        if _CACHE["payload"] is not None:
            return {**_CACHE["payload"], "stale": True}
        return {"available": False, "stale": False, "source": "National Weather Service",
                "source_url": NWS_DOCS, "alerts": [],
                "delivery_impact": {"level": "unknown", "headline": "Weather check unavailable",
                                    "message": "Patch operations will confirm conditions before dispatch."}}


@router.get("/v0/patch/context")
async def context_endpoint():
    return await local_context()
