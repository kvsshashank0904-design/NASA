/* MARS-X offline prototype service worker.
   - Map tiles (NASA Mars Trek / USGS-Esri OnMars): cache-first, so any region viewed or
     explicitly pre-cached keeps rendering without a link.
   - Cesium runtime and app shell (same origin): network-first with cache fallback.
   API responses are cached by the page itself (lib/api.ts) so they can carry timestamps. */
const TILES = "marsx-tiles-v1";
const SHELL = "marsx-shell-v1";
const TILE_HOSTS = ["trek.nasa.gov", "astro.arcgis.com"];

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

  if (TILE_HOSTS.includes(url.hostname)) {
    event.respondWith((async () => {
      const cache = await caches.open(TILES);
      const hit = await cache.match(req.url);
      if (hit) return hit;
      const res = await fetch(req);
      if (res.ok) cache.put(req.url, res.clone());
      return res;
    })());
    return;
  }

  if (url.origin === self.location.origin && !url.pathname.startsWith("/_next/webpack-hmr") && !url.pathname.includes("hot-update")) {
    event.respondWith((async () => {
      const cache = await caches.open(SHELL);
      try {
        const res = await fetch(req);
        if (res.ok && res.type === "basic") cache.put(req, res.clone());
        return res;
      } catch (err) {
        const hit = await cache.match(req, { ignoreSearch: url.pathname.startsWith("/_next/") ? false : true });
        if (hit) return hit;
        throw err;
      }
    })());
  }
});

self.addEventListener("message", async (event) => {
  if (event.data === "tile-stats") {
    const keys = await (await caches.open(TILES)).keys();
    event.source.postMessage({ type: "tile-stats", count: keys.length });
  }
  if (event.data === "clear-tiles") {
    await caches.delete(TILES);
    event.source.postMessage({ type: "tile-stats", count: 0 });
  }
});
