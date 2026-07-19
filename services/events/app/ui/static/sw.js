// GateWay service worker v3: network-first navigation with branded offline
// fallback. APIs are never cached — live dispatch data must stay live.
const CACHE = 'gw-v4';
const SHELL = ['/static/offline.html', '/static/logo-bar.png'];

// Last-resort offline page, inlined. If the Cache Storage entry is ever
// missing — evicted under storage pressure, or a precache fetch failed on a
// flaky connection during install — respondWith(undefined) would throw and the
// customer would get the browser's raw error page instead of ours.
const FALLBACK_HTML = `<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="8"><title>GateWay — Offline</title>
<style>body{font-family:system-ui,sans-serif;background:#0e1526;color:#e8eaf0;
display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;
text-align:center;padding:20px}h1{font-size:1.2rem}
p{color:#8b93a7;max-width:300px;line-height:1.6}</style></head>
<body><div><h1>You're offline</h1>
<p>No connection right now. This page retries automatically.</p>
</div></body></html>`;

function offlineResponse() {
  return new Response(FALLBACK_HTML, {
    status: 503,
    headers: { 'Content-Type': 'text/html; charset=utf-8' },
  });
}

self.addEventListener('install', e => {
  // Cache assets individually: one failed fetch must not abort the whole
  // install and leave the worker never activating.
  e.waitUntil(
    caches.open(CACHE)
      .then(c => Promise.all(SHELL.map(url => c.add(url).catch(() => null))))
      .then(() => self.skipWaiting())
      .catch(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
      .catch(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  if (e.request.mode !== 'navigate') return;
  e.respondWith(
    fetch(e.request).catch(() =>
      caches.match('/static/offline.html').then(r => r || offlineResponse())
    )
  );
});
