"""Feature-inventory guard: every shipped capability, grep-pinned per surface.
Template rewrites have silently dropped features THREE times (Navigate button,
field escaping, assignment buzz + live-ping activation). Page JS is invisible
to API tests — this inventory is the tripwire. Add a line when you ship a feature."""
import os
import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")

CHECKS = {
 "app/ui/home.html": [
   "/static/logo.png", "gw-bar", "gw_last_partner", "gw_last_order",
   "Driver day code", "Kitchen code", "Dispatch key", "/v0/partners", "manifest.json",
   "Local kitchens", "Paused right now", "<details", "gw-profile.js", "/me",
   "YOUR USUAL", "og:title", "localImpact", "quickReorder",
 ],
 "app/ui/order-form.html": [
   "gw-bar", "menuZone", "pausedBanner", "setWhen", "tip_cents", "cartbar",
   "Almost done", "recipientRow", "gw_last_partner", "total_cents",
   "payment_method", "Pay at the door", "gw-profile.js", "gwProfile.addAddress",
   "Place order ·", "og:title", "Welcome to GateWay",
 ],
 "app/track.py": [
   "gw-bar", 'cls = "now"', "MICRO", "elapsed", "celebrate", "againBtn",
   "Photo from your driver", "livebadge", "pollStatus", "gw_last_order", "subtotal",
   "recordOrder", "thank_you_note", "driver_first", "milestone", "og:title", "pollHeadsUp",
 ],
 "app/ui/driver.html": [
   "gw-ui.js", "runline", "maps.apple.com", "headsUp", "esc(o.pickup)", "Kitchen says READY",
   "SCHEDULED", "tel:", "tips_today_cents", "shiftBtn", "navigator.vibrate",
   "HAS_ACTIVE = (d.orders", "/guide/driver", "netDown", "skel",
 ],
 "app/ui/kitchen.html": [
   "gateBtn", "DRIVER COMING", "AudioContext", "slidein",
   "markReady", "/guide/kitchen", "netDown", "skel", "esc(o.items)",
   "pride", "in_kitchen_now", "pauseFifteen", "loadBanner",
 ],
 "app/ui/board.html": [
   "gwPrompt", "paintFilters", "ageChip", "o.partner?", "URGENCY", "/snapshot",
   "editField", "Statement", "shareLink", "showDigest", "toggleTrend",
   "logq", "relTime", "editSummary", "setAccepting", "requeue", "notifyO",
   "netDown", "skel", "maybeDayOpen", "closeAllDelivered", "gw_dayopen_",
   "demoOrder", "editThanks",
 ],
 "app/ui/static/sw.js": ["offline.html", "logo-bar.png"],
 "app/ui/static/offline.html": ["logo-bar.png", "refresh"],
 "app/main.py": ["branded_http_errors", "branded_server_errors", "system.error", "guides_router"],
 "app/kitchen.py": ["requested_for", "ACTIVE", "picked_up_today",
                     "kitchen_accepting", "different kitchen",
                     "delivered_today", "peak_hour", "revenue_today", "load"],
 "app/dispatch.py": ["TRANSITIONS", "_fq", "not on your sheet", "_TTL_CACHE",
                      "partner_statement", "track_status", "STATUS_PRIORITY", "subtotal_usd",
                      "stripe_configured", "retention_sweep", "demo-order", "local_impact", "heads_up"],
 "app/ui/me.html": ["only on this device", "kept in local kitchens", "Erase my profile"],
 "app/ui/static/gw-profile.js": ["recordOrder", "localImpactCents", "greeting", "topKitchen", "setFavorite"],
 "app/payments.py": ["configured", "normalize_method", "cod"],
 "app/intake.py": ["order.payment_method", "payments.normalize_method"],
}


@pytest.mark.parametrize("path,needles", CHECKS.items())
def test_surface_inventory(path, needles):
    src = open(os.path.join(ROOT, path)).read()
    gone = [n for n in needles if n not in src]
    assert not gone, f"{path} lost features: {gone}"
