// GateWay minimal service worker: network-first passthrough (installability only).
// Deliberately no caching of API responses — live dispatch data must stay live.
self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => self.clients.claim());
self.addEventListener('fetch', e => {});
