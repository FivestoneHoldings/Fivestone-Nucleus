"""Public how-it-works guides — shareable alongside driver/kitchen links. No secrets."""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_SHELL = """<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{title} — GateWay</title>
<link rel="manifest" href="/static/manifest.json">
<link rel="apple-touch-icon" href="/static/apple-touch-icon.png">
<meta name="theme-color" content="#0e1526">
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;600;800;900&display=swap" rel="stylesheet">
<style>body{{font-family:'Archivo',system-ui,sans-serif;background:#f7f8fb;color:#16181b;
max-width:520px;margin:0 auto;padding:30px 22px 60px;line-height:1.6}}
.mark{{font-weight:900;font-size:1.5rem}}.mark span{{color:#d81f2a}}
h1{{font-size:1.15rem;font-weight:800;margin:6px 0 20px;color:#16337a}}
.step{{display:flex;gap:14px;margin-bottom:18px}}
.n{{width:30px;height:30px;border-radius:50%;background:#16337a;color:#fff;font-weight:900;
text-align:center;line-height:30px;flex-shrink:0}}
.step p{{margin:3px 0 0;font-size:.94rem}}.step b{{color:#16337a}}
.foot{{font-size:.66rem;color:#9a9ea5;text-transform:uppercase;letter-spacing:.08em;
text-align:center;margin-top:30px;font-family:monospace}}</style></head>
<body><div class="mark">Gate<span>Way</span></div><h1>{title}</h1>{steps}
<div class="foot">GateWay Delivery · Fivestone Holdings</div></body></html>"""


def _steps(items):
    return "".join(f'<div class="step"><div class="n">{i+1}</div><p>{t}</p></div>'
                   for i, t in enumerate(items))


@router.get("/guide/driver", response_class=HTMLResponse)
def driver_guide():
    return _SHELL.format(title="Driving for GateWay", steps=_steps([
        "<b>Install the app:</b> open your day link → Share → <b>Add to Home Screen</b>.",
        "Tap <b>○ OFF SHIFT</b> to go <b>● ON SHIFT</b> when you start.",
        "New deliveries buzz your phone. <b>STOP 1, STOP 2…</b> is your run order.",
        "At the restaurant, wait for <b>🍳 Kitchen says READY</b>, then tap <b>Picked Up</b>.",
        "Tap <b>Navigate ▸</b> for turn-by-turn. The customer sees your dot move — only while you carry their order.",
        "At the door: <b>Delivered ✓</b> → snap the proof photo (or skip the camera).",
        "Trouble? Tap <b>Problem</b> — dispatch takes over. Use <b>Note</b> for anything worth remembering.",
        "Your header shows deliveries and tips today. <b>Tips are 100% yours.</b>",
        "Red strip = reconnecting. Wait for it to clear; nothing is lost."]))


@router.get("/guide/kitchen", response_class=HTMLResponse)
def kitchen_guide():
    return _SHELL.format(title="Your GateWay Kitchen Screen", steps=_steps([
        "<b>Install:</b> open your kitchen link on the counter device → Share → <b>Add to Home Screen</b>.",
        "New orders <b>ding and buzz</b>. Items show big; special requests are highlighted; scheduled orders say so.",
        "Bag it, then tap <b>READY FOR PICKUP ✓</b> — the driver and dispatch see it instantly.",
        "Slammed? Tap <b>⏸ Pause new orders</b>. Customers see you're paused. <b>▶ Resume</b> when ready.",
        "Questions about an order? Call GateWay — we can edit or cancel, and the customer is texted."]))
