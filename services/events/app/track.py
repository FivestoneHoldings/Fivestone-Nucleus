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
<link rel="icon" type="image/png" href="/static/icon-192.png">
<meta property="og:site_name" content="GateWay Delivery">
<meta property="og:title" content="Track your GateWay delivery">
<meta property="og:description" content="Live tracking, delivered by your neighbors.">
<meta property="og:image" content="https://fivestone-nucleus-production.up.railway.app/static/logo.png">
<link rel="manifest" href="/static/manifest.json">
<link rel="apple-touch-icon" href="/static/apple-touch-icon.png">
<meta name="theme-color" content="#0e1526">
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;600;800&family=IBM+Plex+Mono:wght@500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="/static/gw-profile.js"></script>
<script src="/static/gw-ui.js"></script>
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
.prog{display:flex;gap:5px;margin:10px 0 4px}
.prog i{flex:1;height:6px;border-radius:8px;background:#e2e7f1}
.prog i.go{background:linear-gradient(90deg,#2f6fe0,#16337a)}
.prog i.pulse{animation:progPulse 1.6s ease-in-out infinite}
@keyframes progPulse{0%,100%{opacity:1}50%{opacity:.45}}
@media (prefers-reduced-motion:reduce){.prog i.pulse{animation:none}}
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
.tipb{flex:1;padding:12px;border-radius:11px;border:1.5px solid #c3d0f0;background:#fff;
color:#16337a;font-weight:800;font-family:inherit;font-size:.88rem;cursor:pointer}
.tipb:active{background:#eef2fc}
.again{display:block;text-align:center;background:linear-gradient(135deg,#16337a,#1e4292);color:#fff;
text-decoration:none;font-weight:800;padding:15px;border-radius:14px;margin:18px 0 8px;
box-shadow:0 8px 22px rgba(22,51,122,.3)}
.livebadge{display:inline-flex;align-items:center;gap:6px;font-family:'IBM Plex Mono',monospace;
font-size:.62rem;color:#d81f2a;font-weight:700;letter-spacing:.1em}
.livebadge i{width:8px;height:8px;border-radius:50%;background:#d81f2a;animation:pulse 1.4s infinite}
.gwd-powered{display:flex;align-items:center;justify-content:center;gap:10px;margin:26px auto 8px;
padding:12px 18px;border-radius:16px;background:#0e1526;max-width:300px}
.gwd-powered img{height:34px;width:34px;object-fit:contain;border-radius:8px}
.gwd-powered div{text-align:left;line-height:1.25}
.gwd-powered span{display:block;font-family:'IBM Plex Mono',monospace;font-size:.52rem;
letter-spacing:.14em;text-transform:uppercase;color:#8b93a7}
.gwd-powered b{display:block;font-size:.86rem;color:#e8eaf0;font-weight:800}
@media (prefers-reduced-motion: reduce){.step.now .dot,.livebadge i,.celebrate{animation:none}}
/* v0.49 viewport guard — nothing may exceed the phone's width */
html,body{max-width:100%;overflow-x:hidden}
img,svg,video{max-width:100%;height:auto}
*{min-width:0}
.gw-bar{box-sizing:border-box;max-width:100vw}
.catnav{max-width:100%}
pre,code{white-space:pre-wrap;word-break:break-word}
.gw-back{display:inline-flex;align-items:center;gap:6px;color:#16337a;text-decoration:none;
font-weight:800;font-size:.86rem;background:none;border:none;cursor:pointer;padding:8px 0;
font-family:'Archivo';margin-bottom:10px}
</style>
<script>
/* BACK (v1.1): prefer real history so the customer keeps their place; fall back
   to home so a deep link from a text message never dead-ends. */
function gwBack(){
  if(document.referrer && new URL(document.referrer, location.href).origin === location.origin
     && history.length > 1){ history.back(); }
  else { location.href = '/'; }
}
</script>
</head>"""

_MAP_SCRIPT = """
<div id="drivercard" style="display:none;margin:18px 0"></div>
<div id="mapwrap" style="display:none;margin:20px 0">
  <div style="font-weight:800;font-size:.9rem;margin-bottom:8px">Your driver is on the way \U0001F69A
    <span class="livebadge" style="float:right;margin-top:3px"><i></i>LIVE</span></div>
  <div id="map" style="height:260px;border-radius:14px;overflow:hidden;border:1.5px solid #d9deea"></div>
</div>
<div style="display:flex;align-items:center;justify-content:center;gap:9px;margin-top:26px;padding-top:18px;border-top:1px solid #e4e8f2"><img src="/static/gwd-emblem.png" alt="GateWay Delivery" style="height:30px"><div style="text-align:left;line-height:1.25"><div style="font-family:monospace;font-size:.52rem;letter-spacing:.14em;text-transform:uppercase;color:#9a9ea5">Powered by</div><div style="font-weight:900;font-size:.82rem;color:#16337a">GateWay Delivery</div></div></div><div class="foot">Updates automatically \u00b7 Fivestone Holdings</div>
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
try{
  const lp = JSON.parse(localStorage.getItem('gw_last_partner')||'null') || {};
  let cents = 0;
  const tm = (document.body.textContent.match(/Total [$]([0-9]+[.][0-9]{2})/)||[])[1];
  if(tm) cents = Math.round(parseFloat(tm)*100);
  if(window.gwProfile) gwProfile.recordOrder({oid: OID, partner: lp.code||'',
    partnerName: lp.name||'', total_cents: cents, at: new Date().toISOString()});
  // milestone: your Nth order with this kitchen
  if(window.gwProfile && lp.code && document.querySelector('.celebrate')){
    const n = (gwProfile.get().history||[]).filter(h=>h.partner===lp.code).length;
    if(n > 1){
      const ord = n===2?'2nd':n===3?'3rd':n+'th';
      const big = [5,10,25,50].includes(n);
      const el = document.createElement('div');
      el.id = 'milestone';
      el.style.cssText = 'text-align:center;font-weight:800;color:#16337a;margin:-6px 0 12px;font-size:'+(big?'1rem':'.88rem');
      el.textContent = `Your ${ord} order with ${lp.name||'this kitchen'}${big?' — thank you for showing up for local 🧡':' 🧡'}`;
      document.querySelector('.celebrate').after(el);
    }
  }
}catch(e){}
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
// driver heads-up bubble (in-transit only)
async function pollHeadsUp(){
  try{
    const d = await (await fetch('/v0/track/' + encodeURIComponent(OID) + '/heads-up')).json();
    let el = document.getElementById('headsup');
    if(d.note){
      if(!el){
        el = document.createElement('div'); el.id = 'headsup';
        el.style.cssText = 'background:#eef2fc;border:1.5px solid #c3d0f0;border-radius:14px;padding:12px 16px;margin:0 0 14px;font-size:.9rem';
        const anchor = document.querySelector('.items');
        if(anchor) anchor.before(el); else document.body.prepend(el);
      }
      el.innerHTML = '<div style="font-family:monospace;font-size:.58rem;text-transform:uppercase;letter-spacing:.1em;color:#16337a;margin-bottom:4px">Message from your driver</div>' + esc(d.note);
    } else if(el){ el.remove(); }
  }catch(e){}
}
function esc(x){ const d=document.createElement('div'); d.textContent=x||''; return d.innerHTML; }
pollHeadsUp(); setInterval(pollHeadsUp, 15000);
// who's bringing your order — the face, name, and car, once a driver's assigned
async function pollDriver(){
  try{
    const d = await (await fetch('/v0/order/' + encodeURIComponent(OID) + '/driver')).json();
    const el = document.getElementById('drivercard');
    if(!el) return;
    if(!d || !d.assigned){ el.style.display='none'; return; }
    const face = d.photo_url
      ? '<img src="'+esc(d.photo_url)+'" alt="" style="width:56px;height:56px;border-radius:16px;object-fit:cover;flex:0 0 auto">'
      : '<div style="width:56px;height:56px;border-radius:16px;background:linear-gradient(135deg,#eef1f7,#e2e7f2);display:flex;align-items:center;justify-content:center;font-size:1.9rem;flex:0 0 auto;border:1.5px solid #dfe4ee">'+(esc(d.avatar)||'🧑')+'</div>';
    const car = [d.vehicle_color, d.vehicle].filter(Boolean).map(esc).join(' ');
    const verb = d.status === 'in_transit' ? 'is on the way to you' : 'has your order';
    el.innerHTML =
      '<div style="font-family:monospace;font-size:.56rem;letter-spacing:.13em;text-transform:uppercase;color:#16337a;margin-bottom:9px">Your driver</div>'
      + '<div style="display:flex;gap:13px;align-items:center;background:#fff;border:1.5px solid #e4e8f2;border-radius:16px;padding:14px 15px;box-shadow:0 3px 16px rgba(20,30,60,.06)">'
      + face
      + '<div style="min-width:0">'
      + '<div style="font-weight:800;font-size:1.02rem;line-height:1.2">'+esc(d.first_name||d.display_name)+' <span style="font-weight:600;color:#6b7280;font-size:.86rem">'+verb+'</span></div>'
      + (car ? '<div style="font-size:.82rem;color:#44474d;margin-top:3px">🚗 '+car+'</div>' : '')
      + (d.bio ? '<div style="font-size:.8rem;color:#6b7280;margin-top:6px;line-height:1.45">'+esc(d.bio)+'</div>' : '')
      + '</div></div>';
    el.style.display = '';
  }catch(e){}
}
pollDriver(); setInterval(pollDriver, 20000);
async function feedback(good){
  const note = await gwPrompt({title: good ? 'What did you love?' : 'What went wrong?',
    multiline: true, confirm: 'Send privately',
    placeholder: good ? 'The brisket was unreal.' : 'Order was cold when it arrived.',
    body: good ? 'The cook will read this. Nothing is posted publicly.'
               : "The kitchen and dispatch will see this and make it right. Nothing is posted publicly."});
  if(note === null) return;
  const r = await fetch('/v0/track/' + encodeURIComponent(OID) + '/feedback', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({good, note})});
  const box = document.getElementById('fbBox');
  if(r.ok && box){
    box.innerHTML = '<div style="text-align:center;font-weight:800;color:#16337a">' +
      (good ? 'Thank you \U0001F9E1 The kitchen will hear it.' : "Thank you \u2014 we're on it.") + '</div>';
  } else gwToast('Could not send.', false);
}
async function roundUp(cents){
  const r = await fetch('/v0/track/' + encodeURIComponent(OID) + '/round-up', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({cents})});
  const box = document.getElementById('roundBox');
  if(r.ok && box){
    box.innerHTML = '<div style="text-align:center;font-weight:800;color:#16337a">' +
      'Thank you \U0001F9E1 You just helped feed a neighbor.</div>';
  } else gwToast('Could not add that.', false);
}
async function addTip(cents){
  if(!cents){
    const v = await gwPrompt({title:'Tip your driver', inputmode:'decimal', placeholder:'5.00',
      confirm:'Send tip', body:'100% goes to the neighbor who brought your food.'});
    if(!v) return;
    cents = Math.round(parseFloat(v) * 100);
    if(isNaN(cents) || cents <= 0) return gwToast('Enter a valid amount.', false);
  }
  const r = await fetch('/v0/track/' + encodeURIComponent(OID) + '/tip', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({cents})});
  const box = document.getElementById('tipBox');
  if(r.ok){
    const d = await r.json();
    box.innerHTML = '<div style="text-align:center;font-weight:800;color:#16337a">' +
      'Thank you 🧡 $' + (d.tip_cents/100).toFixed(2) + ' tipped — 100% to your driver.</div>';
  } else gwToast('Could not add the tip.', false);
}
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
            f'<button class="gw-back" onclick="gwBack()">&lsaquo; Back to GateWay</button>'
            f'<div class="mark" style="display:none">GateWay <span>Delivery</span></div>'
                f'<div class="oid">{_esc(oid)}</div>'
                f'<div class="status">Order not found</div>'
                f'<div class="items">Double-check the tracking link, or call GateWay.</div>')
        return HTMLResponse(_HEAD + body + "</body></html>", status_code=404)

    f = recs[0]["fields"]
    status = f.get("status", "received")
    # the human layer: driver first name + the kitchen's own thank-you
    driver_first = ""
    if status in ("assigned", "in_transit") and (f.get("driver") or []):
        try:
            from .dispatch import _cget, _cput, _fq as _dfq
            _dref = f["driver"][0]
            cached = _cget(f"dname:{_dref}")
            if cached is None:
                _dr = await at.list_records(at.DRIVERS,
                                            formula=f"RECORD_ID()='{_dfq(_dref)}'", max_records=1)
                cached = (_dr[0]["fields"].get("display_name", "").split(" ")[0]
                          if _dr else "")
                _cput(f"dname:{_dref}", cached, 600)
            driver_first = cached
        except Exception:
            driver_first = ""
    anticipation = ""
    if status in ("received", "confirmed") and f.get("partner_code"):
        try:
            from .db import SessionLocal as _SL2
            from .models import Partner as _P2
            _db2 = _SL2(); _pp = _db2.get(_P2, f["partner_code"]); _db2.close()
            kname = _esc(_pp.display_name) if _pp else "your kitchen"
            blurb = (f'<div style="font-size:.9rem;line-height:1.55;color:#3a3f47;margin:6px 0 12px">'
                     f'{_esc(_pp.about_blurb)}</div>') if (_pp and _pp.about_blurb) else ""
            nxt = "confirming your order" if status == "received" else "preparing your food"
            anticipation = (
                f'<div style="background:#fff;border:1px solid #e4e8f2;border-radius:16px;'
                f'padding:16px 18px;margin:0 0 14px;box-shadow:0 3px 16px rgba(20,30,60,.06)">'
                f'<div style="font-family:\'IBM Plex Mono\',monospace;font-size:.58rem;'
                f'letter-spacing:.12em;text-transform:uppercase;color:#16337a;margin-bottom:6px">'
                f'From {kname}</div>{blurb}'
                f'<div style="font-size:.82rem;color:#7a7f87">Right now: {nxt}. '
                f'We\'ll assign a neighbor to drive it the moment it\'s ready — '
                f'you\'ll see them on the map here.</div></div>')
        except Exception:
            anticipation = ""
    thanks = ""
    if status in ("delivered", "closed") and f.get("partner_code"):
        try:
            from .db import SessionLocal as _SL
            from .models import Partner as _P
            _db = _SL()
            _p = _db.get(_P, f["partner_code"])
            _db.close()
            if _p and _p.thank_you_note:
                thanks = (f'<div style="background:#fdf9ee;border:1.5px solid #eadfae;'
                          f'border-radius:14px;padding:14px 16px;margin:0 0 14px;'
                          f'font-size:.9rem;line-height:1.55">'
                          f'<div style="font-family:\'IBM Plex Mono\',monospace;font-size:.6rem;'
                          f'text-transform:uppercase;letter-spacing:.1em;color:#a8894a;margin-bottom:4px">'
                          f'A note from {_esc(_p.display_name)}</div>'
                          f'{_esc(_p.thank_you_note)}</div>')
        except Exception:
            thanks = ""
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
        again_html = ('<div id="tipBox" style="background:#fff;border:1px solid #e4e8f2;border-radius:16px;'
                      'padding:16px 18px;margin:0 0 14px;box-shadow:0 3px 16px rgba(20,30,60,.06)">'
                      '<div style="font-weight:800;font-size:.95rem;margin-bottom:3px">Add a tip for your driver?</div>'
                      '<div style="font-size:.8rem;color:#7a7f87;margin-bottom:11px">100% goes to them. No account needed.</div>'
                      '<div style="display:flex;gap:8px">'
                      '<button class="tipb" onclick="addTip(200)">$2</button>'
                      '<button class="tipb" onclick="addTip(300)">$3</button>'
                      '<button class="tipb" onclick="addTip(500)">$5</button>'
                      '<button class="tipb" onclick="addTip(0)">Other</button>'
                      '</div></div>'
                      '<div id="roundBox" style="background:#fff;border:1px solid #e4e8f2;border-radius:16px;'
                      'padding:16px 18px;margin:0 0 14px;box-shadow:0 3px 16px rgba(20,30,60,.06)">'
                      '<div style="font-weight:800;font-size:.95rem;margin-bottom:3px">Round up for the Neighbor Fund?</div>'
                      '<div style="font-size:.8rem;color:#7a7f87;margin-bottom:11px">'
                      'Every $5.99 you round up covers a delivery for a neighbor having a hard week. '
                      'GateWay takes nothing \\u2014 <a href="/neighbor-fund" style="color:#16337a;font-weight:700">how it works</a>.</div>'
                      '<div style="display:flex;gap:8px">'
                      '<button class="tipb" onclick="roundUp(100)">+$1</button>'
                      '<button class="tipb" onclick="roundUp(200)">+$2</button>'
                      '<button class="tipb" onclick="roundUp(500)">+$5</button>'
                      '</div></div>'
                      '<div id="fbBox" style="background:#fff;border:1px solid #e4e8f2;border-radius:16px;'
                      'padding:16px 18px;margin:0 0 14px;box-shadow:0 3px 16px rgba(20,30,60,.06)">'
                      '<div style="font-weight:800;font-size:.95rem;margin-bottom:3px">How was it?</div>'
                      '<div style="font-size:.8rem;color:#7a7f87;margin-bottom:11px">'
                      'This goes straight to the kitchen and to us \u2014 privately. '
                      'We don\'t run public star ratings that can sink a family restaurant.</div>'
                      '<div style="display:flex;gap:8px">'
                      '<button class="tipb" onclick="feedback(true)">\U0001F9E1 Loved it</button>'
                      '<button class="tipb" onclick="feedback(false)">Something was off</button>'
                      '</div></div>'
                      '<a class="again" id="againBtn" href="/order" style="display:none">Order again</a>')
    # compact progress bar under the headline — how far along, at a glance.
    # received=1/4, confirmed=2/4, assigned/in_transit=3/4, delivered=4/4.
    _PROG = {"received": 1, "confirmed": 2, "assigned": 3, "in_transit": 3,
             "delivered": 4, "closed": 4}
    seg = _PROG.get(status, 0)
    if seg:
        segs = "".join(
            f'<i class="{"go" if n < seg else ""}{" pulse" if n == seg - 1 and active else ""}"></i>'
            for n in range(4))
        prog_html = f'<div class="prog" aria-hidden="true">{segs}</div>'
    else:
        prog_html = ""
    micro_text = MICRO.get(status, "")
    if driver_first and status == "assigned":
        micro_text = f"Your neighbor {_esc(driver_first)} is heading to pick it up."
    elif driver_first and status == "in_transit":
        micro_text = f"{_esc(driver_first)} is on the way — watch the map."
    micro_html = f'<div class="micro">{micro_text}</div>'
    received_ts = f.get("received_at", "")
    elapsed_html = (f'<div class="elapsed" id="elapsed" data-rcv="{_esc(received_ts)}"></div>'
                    if received_ts and active else "")
    body = (f'<body data-oid="{_esc(oid)}">'
            f'<div class="gw-bar"><img src="/static/logo-bar.png" alt="GateWay"><span class="surf">Tracking</span></div>'
            f'<button class="gw-back" onclick="gwBack()">&lsaquo; Back to GateWay</button>'
            f'<div class="mark" style="display:none">GateWay <span>Delivery</span></div>'
            f'<div class="oid">{_esc(oid)}</div>'
            f'{celebrate_html}'
            f'<div class="status" style="text-align:{"center" if celebrate_html else "left"}">{HEADLINES.get(status, _esc(status))}</div>'
            f'{prog_html}'
            f'{micro_html}{elapsed_html}{anticipation}'
            f'<div class="items">{items_line}</div>'
            f'{thanks}{proof_html}{again_html}'
            f'{steps_html}')
    return HTMLResponse(_HEAD + body + _MAP_SCRIPT, status_code=200)
