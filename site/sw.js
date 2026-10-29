// Nishpaksh offline support (nishpaksh_version_1.0). The page itself and its icons are kept for
// offline use; news (the feed, articles) is always asked for fresh and the last copy is used offline;
// fonts are kept once loaded.
const VERSION = "np-main-91";
const IMGS = "np-pictures";           // the outlets' share pictures: linked, shown from this device's own cache (owner, Oct 29 2026)
const IMG_MAX = 80;
const SHELL = ["./", "./index.html", "./manifest.webmanifest", "./icon-192.png", "./icon-512.png", "./icon-maskable-192.png",
               "./icon-maskable-512.png", "./apple-touch-icon.png", "./mark.png", "./notif-icon-256.png", "./notif-badge-96.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(VERSION).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== VERSION && k !== IMGS).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
// The feed's files are asked for with a changing address (?m=<minute>, ?v=<time>) so a CDN never answers with an old
// copy. Kept under one fixed address instead, so the offline copy is found again and the cache does not fill with a
// new entry every minute (owner, Oct 11 2026).
function keyOf(req) {
  const u = new URL(req.url);
  return u.hostname === "raw.githubusercontent.com" ? u.origin + u.pathname : req;
}
async function fresh(req) {           // network first, the saved copy when offline
  const cache = await caches.open(VERSION);
  const key = keyOf(req);
  try {
    const r = await fetch(req);
    if (r.ok) cache.put(key, r.clone());
    return r;
  } catch (err) {
    const hit = await cache.match(key, {ignoreSearch: req.mode === "navigate"});
    if (hit) return hit;
    throw err;
  }
}
async function keptPicture(req) {     // saved copy first; a new picture is kept, the oldest are let go
  const cache = await caches.open(IMGS);
  const hit = await cache.match(req);
  if (hit) return hit;
  const r = await fetch(req);
  if (r.ok || r.type === "opaque") {
    cache.put(req, r.clone()).then(() => cache.keys()).then(ks => Promise.all(ks.slice(0, Math.max(0, ks.length - IMG_MAX)).map(k => cache.delete(k)))).catch(() => {});
  }
  return r;
}
async function kept(req) {            // saved copy first (fonts never change)
  const cache = await caches.open(VERSION);
  const hit = await cache.match(req);
  if (hit) return hit;
  const r = await fetch(req);
  if (r.ok || r.type === "opaque") cache.put(req, r.clone());
  return r;
}
self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;
  const u = new URL(req.url);
  if (u.pathname.includes("/audio/")) return;          // audio is read in ranges: straight to the network
  if (u.hostname === "fonts.gstatic.com" || u.hostname === "fonts.googleapis.com") { e.respondWith(kept(req)); return; }
  if (req.destination === "image" && u.origin !== self.location.origin && u.hostname !== "raw.githubusercontent.com" && u.protocol === "https:") { e.respondWith(keptPicture(req)); return; }
  if (u.hostname === "raw.githubusercontent.com" || u.origin === self.location.origin) { e.respondWith(fresh(req)); return; }
  // Supabase and anything else: straight to the network
});

// notifications (nishpaksh/notify.py sends them: audio ready, the daily recap)
self.addEventListener("push", e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (err) { d = {title: "Nishpaksh", body: e.data ? e.data.text() : ""}; }
  // Tell every open page that there is news: a page that was put aside (a phone keeps it frozen, not closed) drops
  // what it holds and asks again when it is looked at, so the article the notification is about is on the home page
  // the moment the reader opens it, not after a few opens (owner, Oct 11 2026).
  e.waitUntil(Promise.all([
    self.registration.showNotification(d.title || "Nishpaksh",
      {body: d.body || "", tag: d.tag, data: {url: d.url || "./", story: d.story || null},
       icon: "notif-icon-256.png", badge: "notif-badge-96.png"}),
    self.clients.matchAll({type: "window", includeUncontrolled: true}).then(cs =>
      cs.forEach(c => c.postMessage({np: "fresh", story: d.story || null}))),
  ]));
});
self.addEventListener("notificationclick", e => {
  e.notification.close();
  const target = new URL((e.notification.data && e.notification.data.url) || "./", self.registration.scope);
  e.waitUntil((async () => {
    for (const c of await self.clients.matchAll({type: "window", includeUncontrolled: true})) {
      if (!("focus" in c) || !c.url.startsWith(self.registration.scope)) continue;
      const here = new URL(c.url);
      await c.focus();
      // same page and language: the open page is told which link to open (a bare navigate() to a new #hash did
      // nothing in the page, so the recap and article never opened); otherwise load the link
      if (here.origin === target.origin && here.pathname === target.pathname && here.search === target.search) {
        c.postMessage({np: "open", hash: target.hash || "", story: (e.notification.data || {}).story || null});
        return;
      }
      if ("navigate" in c) { try { await c.navigate(target.href); return; } catch (err) { /* open a new window */ } }
    }
    return self.clients.openWindow(target.href);
  })());
});
