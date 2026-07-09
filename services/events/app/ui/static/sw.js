// GateWay service worker v2: network-first navigation with branded offline fallback.
// APIs are never cached — live dispatch data must stay live.
const CACHE = 'gw-v2';
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.add('/static/offline.html')).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
  ).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  if (e.request.mode === 'navigate') {
    e.respondWith(fetch(e.request).catch(() => caches.match('/static/offline.html')));
  }
});
