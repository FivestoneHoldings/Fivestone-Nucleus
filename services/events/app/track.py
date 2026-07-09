"""Public order tracking — /track/{order_id}. The order ID is the secret.
Exposes only: status, timeline stamps, items. No addresses, no names, no phones.
"""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from . import airtable_client as at

router = APIRouter()

STEPS = [("received_at", "Order received"),
         ("confirmed_at", "Confirmed by dispatch"),
         ("assigned_at", "Driver assigned"),
         ("in_transit_at", "Picked up — on the way"),
         ("delivered_at", "Delivered")]

PAGE = """<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Track your order — GateWay Delivery</title>
<link rel="manifest" href="/static/manifest.json">
<link rel="apple-touch-icon" href="/static/apple-touch-icon.png">
<meta name="theme-color" content="#1f4d3a">
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;600;800&family=IBM+Plex+Mono:wght@500&display=swap" rel="stylesheet">
<style>body{{font-family:'Archivo',system-ui,sans-serif;background:#f7f6f3;color:#16181b;
max-width:480px;margin:0 auto;padding:28px 20px 60px}}
.mark{{font-weight:800;font-size:1.15rem}}.mark span{{color:#1f4d3a}}
.oid{{font-family:'IBM Plex Mono',monospace;font-size:.75rem;color:#6b6f76;margin:4px 0 22px}}
.status{{font-size:1.5rem;font-weight:800;margin-bottom:4px}}
.items{{font-size:.9rem;color:#5a5e64;background:#fff;border:1.5px solid #e0ddd6;
border-radius:10px;padding:10px 14px;margin:14px 0 26px}}
.step{{display:flex;gap:14px;padding:0 0 26px 0;position:relative}}
.dot{{width:22px;height:22px;border-radius:50%;flex-shrink:0;background:#e0ddd6;z-index:1}}
.step.done .dot{{background:#1f4d3a}}
.step:not(:last-child):before{{content:"";position:absolute;left:10px;top:22px;bottom:0;width:2px;background:#e0ddd6}}
.step.done:not(:last-child):before{{background:#1f4d3a}}
.lbl{{font-weight:600;font-size:.95rem}}
.time{{font-family:'IBM Plex Mono',monospace;font-size:.68rem;color:#9a9ea5}}
.foot{{font-family:'IBM Plex Mono',monospace;font-size:.62rem;color:#9a9ea5;margin-top:26px;
text-transform:uppercase;letter-spacing:.08em;text-align:center}}</style>
<meta http-equiv="refresh" content="60"></head>
<body><div class="mark">GateWay <span>Delivery</span></div>
<div class="oid">{order_id}</div>
<div class="status">{headline}</div>
<div class="items">{items}</div>
{timeline}
<div class="foot">Updates automatically · GateWay Delivery · Fivestone Holdings</div>
</body></html>"""

HEADLINES = {"received": "We've got your order 👍", "confirmed": "Confirmed — lining it up",
             "assigned": "A driver has your order", "in_transit": "On the way to you 🚚",
             "delivered": "Delivered ✓", "closed": "Delivered ✓",
             "cancelled": "This order was cancelled", "failed": "Delivery issue — we're on it"}


def _fmt(ts: str) -> str:
    return ts.replace("T", " ").split(".")[0] + " UTC" if ts else ""


@router.get("/track/{order_id}", response_class=HTMLResponse)
async def track(order_id: str):
    oid = order_id.upper().strip()
    recs = await at.list_records(at.ORDERS, formula=f"{{order_id}}='{oid}'", max_records=1)
    if not recs:
        return HTMLResponse(PAGE.format(
            order_id=oid, headline="Order not found",
            items="Double-check the tracking link, or call GateWay.", timeline=""), status_code=404)
    f = recs[0]["fields"]
    status = f.get("status", "received")
    steps_html = ""
    for field, label in STEPS:
        ts = f.get(field, "")
        steps_html += (f'<div class="step {"done" if ts else ""}"><div class="dot"></div>'
                       f'<div><div class="lbl">{label}</div>'
                       f'<div class="time">{_fmt(ts) if ts else "—"}</div></div></div>')
    total = f.get("total_cents")
    items_line = f.get("items_description", "")
    if total:
        try:
            items_line += f'<br><b style="color:#1f4d3a">Total ${int(total)/100:.2f}</b>'
        except (ValueError, TypeError):
            pass
    return PAGE.format(order_id=oid,
                       headline=HEADLINES.get(status, status),
                       items=items_line, timeline=steps_html)
