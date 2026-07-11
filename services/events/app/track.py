"""Public order tracking — /track/{order_id}. The order ID is the secret.
Exposes only: status, timeline stamps, items, total, and (while in transit) a live
driver map. No addresses, no names, no phones. Live location is time-boxed & coarse.
"""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

import re as _re

from . import airtable_client as at

router = APIRouter()


def _fq(v: str) -> str:
    return _re.sub(r"[^A-Za-z0-9 _.@+\-]", "", str(v or ""))[:120]

STEPS = [("received_at", "Order received"),
         ("confirmed_at", "Confirmed by dispatch"),
         ("assigned_at", "Driver assigned"),
         ("in_transit_at", "Picked up — on the way"),
         ("delivered_at", "Delivered")]

HEADLINES = {"received": "We've got your order 👍", "confirmed": "Confirmed — lining it up",
             "assigned": "A driver has your order", "in_transit": "On the way to you 🚚",
             "delivered": "Delivered ✓", "closed": "Delivered ✓",
             "cancelled": "This order was cancelled", "failed": "Delivery issue — we're on it"}

MICRO = {"received": "Hang tight — dispatch is on it.",
         "confirmed": "The kitchen has your ticket.",
         "assigned": "Your driver is heading to pick it up.",
         "in_transit": "Watch the map — your driver is moving.",
         "delivered": "Enjoy! Thanks for choosing GateWay.",
         "closed": "Enjoy! Thanks for choosing GateWay.",
         "cancelled": "Questions? Call GateWay and we'll make it right.",
         "failed": "We hit a snag — dispatch is already working it. Call us anytime."}

_HEAD = """<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Track your order — GateWay Delivery</title>
<link rel="manifest" href="/static/manifest.json">
<link rel="apple-touch-icon" href="/static/apple-touch-icon.png">
<meta name="theme-color" content="#0e1526">
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;600;800&family=IBM+Plex+Mono:wght@500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>*{-webkit-tap-highlight-color:transparent}
body{font-family:'Archivo',system-ui,sans-serif;background:#f7f8fb;color:#16181b;
max-width:480px;margin:0 auto;padding:88px 20px 60px;-webkit-font-smoothing:antialiased}
.gw-bar{position:fixed;top:0;left:0;right:0;z-index:50;background:#0e1526;display:flex;
align-items:center;justify-content:space-between;padding:12px 16px;
padding-top:max(12px, env(safe-area-inset-top));box-shadow:0 2px 14px rgba(10,15,30,.28)}
.gw-bar img{height:34px;display:block}
.gw-bar .surf{font-family:'IBM Plex Mono',monospace;font-size:.6rem;color:#8b93a7;
text-transform:uppercase;letter-spacing:.14em}
.items{box-shadow:0 3px 16px rgba(20,30,60,.06);border-radius:14px !important;border:1px solid #e4e8f2 !important}
.mark{font-weight:800;font-size:1.15rem}.mark span{color:#16337a}
.oid{font-family:'IBM Plex Mono',monospace;font-size:.75rem;color:#6b6f76;margin:4px 0 22px}
.status{font-size:1.5rem;font-weight:800;margin-bottom:4px}
.items{font-size:.9rem;color:#5a5e64;background:#fff;border:1.5px solid #d9deea;
border-radius:10px;padding:10px 14px;margin:14px 0 26px}
.step{display:flex;gap:14px;padding:0 0 26px 0;position:relative}
.dot{width:22px;height:22px;border-radius:50%;flex-shrink:0;background:#d9deea;z-index:1}
.step.done .dot{background:#16337a}
.step:not(:last-child):before{content:"";position:absolute;left:10px;top:22px;bottom:0;width:2px;background:#d9deea}
.step.done:not(:last-child):before{background:#16337a}
.lbl{font-weight:600;font-size:.95rem}
.time{font-family:'IBM Plex Mono',monospace;font-size:.68rem;color:#9a9ea5}
.foot{font-family:'IBM Plex Mono',monospace;font-size:.62rem;color:#9a9ea5;margin-top:26px;
text-transform:uppercase;letter-spacing:.08em;text-align:center}
.step.now .dot{background:#fff;border:5px solid #2f6fe0;box-sizing:border-box;animation:pulse 1.6s infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(47,111,224,.45)}70%{box-shadow:0 0 0 12px rgba(47,111,224,0)}100%{box-shadow:0 0 0 0 rgba(47,111,224,0)}}
.micro{font-size:.88rem;color:#5a5e64;margin:2px 0 6px}
.elapsed{font-family:'IBM Plex Mono',monospace;font-size:.68rem;color:#9a9ea5;margin-bottom:16px}
.celebrate{width:84px;height:84px;border-radius:50%;background:linear-gradient(135deg,#16337a,#1e4292);
color:#fff;font-size:2.4rem;line-height:84px;text-align:center;margin:8px auto 14px;
box-shadow:0 10px 30px rgba(22,51,122,.35);animation:pop .5s cubic-bezier(.2,1.6,.4,1)}
@keyframes pop{0%{transform:scale(.3);opacity:0}100%{transform:scale(1);opacity:1}}
.again{display:block;text-align:center;background:linear-gradient(135deg,#16337a,#1e4292);color:#fff;
text-decoration:none;font-weight:800;padding:15px;border-radius:14px;margin:18px 0 8px;
box-shadow:0 8px 22px rgba(22,51,122,.3)}
.livebadge{display:inline-flex;align-items:center;gap:6px;font-family:'IBM Plex Mono',monospace;
font-size:.62rem;color:#d81f2a;font-weight:700;letter-spacing:.1em}
.livebadge i{width:8px;height:8px;border-radius:50%;background:#d81f2a;animation:pulse 1.4s infinite}
@media (prefers-reduced-motion: reduce){.step.now .dot,.livebadge i,.celebrate{animation:none}}</style></head>"""

_MAP_SCRIPT = """
<div id="mapwrap" style="display:none;margin:20px 0">
  <div style="font-weight:800;font-size:.9rem;margin-bottom:8px">Your driver is on the way \U0001F69A
    <span class="livebadge" style="float:right;margin-top:3px"><i></i>LIVE</span></div>
  <div id="map" style="height:260px;border-radius:14px;overflow:hidden;border:1.5px solid #d9deea"></div>
</div>
<div class="foot">Updates automatically \u00b7 GateWay Delivery \u00b7 Fivestone Holdings</div>
<script>
const OID = document.body.getAttribute('data-oid');
let map, marker;
async function pollLoc(){
  try{
    const d = await (await fetch('/v0/track/' + encodeURIComponent(OID) + '/location')).json();
    const wrap = document.getElementById('mapwrap');
    if(!d.live){ wrap.style.display='none'; return; }
    wrap.style.display='block';
    const lat = parseFloat(d.lat), lng = parseFloat(d.lng);
    if(isNaN(lat)||isNaN(lng)) return;
    if(!map){
      map = L.map('map', {zoomControl:false, attributionControl:false}).setView([lat,lng], 14);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:18}).addTo(map);
      marker = L.marker([lat,lng]).addTo(map);
    } else {
      marker.setLatLng([lat,lng]); map.panTo([lat,lng]);
    }
  }catch(e){}
}
try{ localStorage.setItem('gw_last_order', OID); }catch(e){}
pollLoc(); setInterval(pollLoc, 20000);
// live status: reload the page the moment the order advances
let CUR = null;
async function pollStatus(){
  try{
    const d = await (await fetch('/v0/track/' + encodeURIComponent(OID) + '/status')).json();
    if(CUR === null) CUR = d.status;
    else if(d.status !== CUR) location.reload();
  }catch(e){}
}
pollStatus(); setInterval(pollStatus, 15000);
// elapsed ticker
const el = document.getElementById('elapsed');
if(el && el.dataset.rcv){
  const t0 = new Date(el.dataset.rcv).getTime();
  const tick = ()=>{
    const m = Math.max(0, Math.round((Date.now() - t0) / 60000));
    el.textContent = 'Placed ' + (m < 1 ? 'just now' : m + ' min ago');
  };
  tick(); setInterval(tick, 30000);
}
// reorder button from remembered partner
try{
  const lp = JSON.parse(localStorage.getItem('gw_last_partner') || 'null');
  const btn = document.getElementById('againBtn');
  if(btn && lp && lp.code){
    btn.href = '/order?partner=' + encodeURIComponent(lp.code);
    btn.textContent = 'Order again — ' + (lp.name || 'same kitchen');
    btn.style.display = 'block';
  } else if(btn){ btn.style.display = 'block'; }
}catch(e){}
</script>
</body></html>"""


def _fmt(ts: str) -> str:
    return ts.replace("T", " ").split(".")[0] + " UTC" if ts else ""


def _esc(x: str) -> str:
    return (x or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


@router.get("/track/{order_id}", response_class=HTMLResponse)
async def track(order_id: str):
    oid = order_id.upper().strip()
    recs = await at.list_records(at.ORDERS, formula=f"{{order_id}}='{_fq(oid)}'", max_records=1)
    if not recs:
        body = (f'<body data-oid="{_esc(oid)}">'
            f'<div class="gw-bar"><img src="/static/logo-bar.png" alt="GateWay"><span class="surf">Tracking</span></div>'
            f'<div class="mark" style="display:none">GateWay <span>Delivery</span></div>'
                f'<div class="oid">{_esc(oid)}</div>'
                f'<div class="status">Order not found</div>'
                f'<div class="items">Double-check the tracking link, or call GateWay.</div>')
        return HTMLResponse(_HEAD + body + "</body></html>", status_code=404)

    f = recs[0]["fields"]
    status = f.get("status", "received")
    active = status in ("received", "confirmed", "assigned", "in_transit")
    steps_html = ""
    now_marked = False
    for field, label in STEPS:
        ts = f.get(field, "")
        cls = "done" if ts else ""
        if not ts and active and not now_marked:
            cls = "now"
            now_marked = True
        steps_html += (f'<div class="step {cls}"><div class="dot"></div>'
                       f'<div><div class="lbl">{label}</div>'
                       f'<div class="time">{_fmt(ts) if ts else "—"}</div></div></div>')

    raw_items = f.get("items_description", "")
    # cart strings look like "2× A ($9.00), 1× B ($4.00) — subtotal $13.00"
    raw_items = raw_items.split(" — subtotal")[0]
    items_line = _esc(raw_items).replace("), ", ")<br>")
    total = f.get("total_cents")
    if total:
        try:
            items_line += f'<br><b style="color:#16337a">Total ${int(total)/100:.2f}</b>'
        except (ValueError, TypeError):
            pass

    proof_html = ""
    celebrate_html = ""
    again_html = ""
    if status in ("delivered", "closed"):
        celebrate_html = '<div class="celebrate">✓</div>'
        proof_html = (f'<div style="font-family:\'IBM Plex Mono\',monospace;font-size:.62rem;'
                      f'color:#9a9ea5;text-transform:uppercase;letter-spacing:.1em;margin-bottom:6px">'
                      f'Photo from your driver</div>'
                      f'<img src="/proof/{_esc(oid)}" alt="Delivery photo" '
                      f'style="width:100%;border-radius:14px;border:1.5px solid #d9deea;'
                      f'margin:0 0 14px" onerror="this.style.display=\'none\';this.previousElementSibling.style.display=\'none\'">')
        again_html = '<a class="again" id="againBtn" href="/order" style="display:none">Order again</a>'
    micro_html = f'<div class="micro">{MICRO.get(status, "")}</div>'
    received_ts = f.get("received_at", "")
    elapsed_html = (f'<div class="elapsed" id="elapsed" data-rcv="{_esc(received_ts)}"></div>'
                    if received_ts and active else "")
    body = (f'<body data-oid="{_esc(oid)}">'
            f'<div class="gw-bar"><img src="/static/logo-bar.png" alt="GateWay"><span class="surf">Tracking</span></div>'
            f'<div class="mark" style="display:none">GateWay <span>Delivery</span></div>'
            f'<div class="oid">{_esc(oid)}</div>'
            f'{celebrate_html}'
            f'<div class="status" style="text-align:{"center" if celebrate_html else "left"}">{HEADLINES.get(status, _esc(status))}</div>'
            f'{micro_html}{elapsed_html}'
            f'<div class="items">{items_line}</div>'
            f'{proof_html}{again_html}'
            f'{steps_html}')
    return HTMLResponse(_HEAD + body + _MAP_SCRIPT, status_code=200)
