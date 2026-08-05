/* LucidDive service worker — the app shell is served from cache immediately
   and refreshed in the background. The API is never intercepted: chat must
   always be live.

   Network-first was the obvious shape and the wrong one for where this runs.
   The free tier spins the instance down after ~15 minutes idle, and the page
   itself is served by that sleeping server, so network-first meant a returning
   visitor waited out the whole ~30s cold start staring at a blank tab before
   the cache was ever consulted — the cache could only help once the network
   had already failed, and a slow server never fails, it just takes half a
   minute. Serving the cached shell first turns that into a painted interface
   with a spinner in the composer while the server wakes. It costs being at
   most one load behind on a deploy, which is the standard PWA trade and a
   good one here.

   The background revalidate still hits the server, so its Set-Cookie (the
   `sid` session cookie) lands as usual and the keep-warm effect of a real
   visit is unchanged. */
const CACHE = "luciddive-v2";

self.addEventListener("install", (e) => {
  // The landing page doubles as the offline fallback for a bot page this
  // browser has never opened. Failing to reach it must not fail the install.
  e.waitUntil(caches.open(CACHE).then((c) => c.add("/")).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
      .then(() => self.clients.matchAll({ type: "window" }))
      .then((windows) => caches.open(CACHE).then((cache) =>
        // The page that registered us loaded before we existed, so it never
        // passed through the fetch handler and isn't cached. Without this,
        // a visitor's *second* visit still pays the cold start and only the
        // third is instant — which on an instance that sleeps every 15
        // minutes is most of the visits that matter. One extra request for
        // a page we already know they want.
        Promise.all(windows.map((w) => cache.add(w.url).catch(() => {})))))
  );
});

self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  const url = new URL(e.request.url);
  if (url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  e.respondWith(shell(e));
});

async function shell(e) {
  const cache = await caches.open(CACHE);
  const hit = await cache.match(e.request);

  const fresh = fetch(e.request)
    .then((res) => {
      if (res.ok) cache.put(e.request, res.clone());
      return res;
    })
    .catch(() => null);

  if (hit) {
    // Don't await it — that would give back the cold start we just removed.
    // waitUntil keeps the worker alive long enough for the write to land.
    e.waitUntil(fresh);
    return hit;
  }

  // Nothing cached for this URL: the network is the only answer, and if it
  // can't give one, a bot page falls back to the shell we cached on install
  // rather than the browser's offline error.
  return (await fresh)
    || (e.request.mode === "navigate" ? await cache.match("/") : undefined)
    || Response.error();
}
