"use client";
import { useCallback, useEffect, useState } from "react";
import { apiGet, cachedApiEntries } from "@/lib/api";
import { fmtPt, fmtWhen } from "@/lib/format";
import { useStore } from "@/lib/store";
import type { Layer } from "@/lib/types";
import { Notice, Section, Stat } from "./ui";

const TILE_CACHE = "marsx-tiles-v1";
const META = "marsx:offline-regions";
const MAX_TILES = 900;

type Region = { lon: number; lat: number; radius_km: number; at: string; tiles: number; failed: number; layers: string[] };

function tilesFor(layer: Layer, w: number, s: number, e: number, n: number, budget: number): string[] {
  const urls: string[] = [];
  for (let z = 0; z <= (layer.max_level ?? 8); z++) {
    const nx = 2 * 2 ** z, ny = 2 ** z;
    const x0 = Math.floor(((w + 180) / 360) * nx), x1 = Math.floor(((e + 180) / 360) * nx);
    const y0 = Math.floor(((90 - n) / 180) * ny), y1 = Math.floor(((90 - s) / 180) * ny);
    const count = (x1 - x0 + 1) * (y1 - y0 + 1);
    if (urls.length + count > budget) break;
    for (let x = x0; x <= x1; x++) for (let y = y0; y <= y1; y++) urls.push(layer.tile_url!.replace("{z}", String(z)).replace("{y}", String(y)).replace("{x}", String(x)));
  }
  return urls;
}

export default function OfflinePanel() {
  const selected = useStore((s) => s.selected);
  const habitat = useStore((s) => s.habitat);
  const layerDefs = useStore((s) => s.layerDefs);
  const layers = useStore((s) => s.layers);
  const plan = useStore((s) => s.plan);
  const planSavedAt = useStore((s) => s.planSavedAt);
  const missionTargets = useStore((s) => s.missionTargets);
  const [radius, setRadius] = useState(15);
  const [tileCount, setTileCount] = useState<number | null>(null);
  const [apiCount, setApiCount] = useState(0);
  const [regions, setRegions] = useState<Region[]>([]);
  const [busy, setBusy] = useState<{ done: number; total: number } | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [supported, setSupported] = useState<boolean | null>(null);   // decided after mount so server and client markup agree
  useEffect(() => { setSupported("caches" in window); }, []);

  const refresh = useCallback(async () => {
    if (!supported) return;
    setTileCount((await (await caches.open(TILE_CACHE)).keys()).length);
    setApiCount((await cachedApiEntries()).length);
    try { setRegions(JSON.parse(localStorage.getItem(META) || "[]")); } catch { setRegions([]); }
  }, [supported]);
  useEffect(() => { refresh(); }, [refresh]);

  const center = selected || habitat;

  const cacheRegion = async () => {
    if (!center || !supported) return;
    setMsg(null);
    const dlat = (radius * 1000) / 3396190 * (180 / Math.PI);
    const dlon = dlat / Math.max(0.05, Math.cos((center.lat * Math.PI) / 180));
    const [w, s, e, n] = [center.lon - dlon, center.lat - dlat, center.lon + dlon, center.lat + dlat];
    const active = layerDefs.filter((l) => l.kind === "wmts" && layers[l.id]?.visible);
    const per = Math.floor(MAX_TILES / Math.max(1, active.length));
    const urls = active.flatMap((l) => tilesFor(l, w, s, e, n, per));
    const cache = await caches.open(TILE_CACHE);
    let done = 0, failed = 0;
    setBusy({ done: 0, total: urls.length });
    const worker = async () => {
      while (urls.length) {
        const u = urls.pop()!;
        try {
          if (!(await cache.match(u))) {
            const r = await fetch(u, { mode: "cors" });
            if (r.ok) await cache.put(u, r); else failed++;
          }
        } catch { failed++; }
        done++;
        if (done % 10 === 0) setBusy((b) => (b ? { ...b, done } : b));
      }
    };
    await Promise.all(Array.from({ length: 6 }, worker));
    let bundleOk = true;
    try { await apiGet(`/api/v1/offline/bundle?lon=${center.lon.toFixed(5)}&lat=${center.lat.toFixed(5)}&radius_km=${radius}`); } catch { bundleOk = false; }
    const rec: Region = { lon: center.lon, lat: center.lat, radius_km: radius, at: new Date().toISOString(), tiles: done - failed, failed, layers: active.map((l) => l.title) };
    const all = [rec, ...regions].slice(0, 8);
    localStorage.setItem(META, JSON.stringify(all));
    setBusy(null);
    setMsg(`${done - failed} tiles stored${failed ? `, ${failed} unavailable (outside layer coverage or network error)` : ""}. ` +
      (bundleOk ? "Science targets, terrain summary, environment snapshot and dataset provenance for the region are saved." : "Region data bundle could NOT be saved (backend unreachable)."));
    refresh();
  };

  const clear = async () => {
    await caches.delete(TILE_CACHE);
    localStorage.removeItem(META);
    setMsg("Cached map tiles cleared.");
    refresh();
  };

  return (
    <Section title="Offline mission mode (prototype)">
      {supported === null ? null : !supported ? <Notice tone="warn">This browser does not expose Cache Storage; offline caching is unavailable.</Notice> : (
        <div className="flex flex-col gap-2.5">
          <div className="grid grid-cols-3 gap-3">
            <Stat label="Map tiles cached" value={tileCount ?? "…"} />
            <Stat label="API responses" value={apiCount} sub="with timestamps" />
            <Stat label="Mission plan" value={plan ? "saved" : "none"} tone={plan ? "ok" : undefined} sub={plan ? fmtWhen(planSavedAt) : "plan a route first"} />
          </div>
          <div className="text-[11px] text-dim">
            Saved on this device and usable without a link: viewed/pre-cached map tiles, the active route plan with its return route, {missionTargets.length} mission target(s), hazard summaries and every API answer already fetched.
            Route planning, terrain analysis and MARS AI need the backend.
          </div>
          <div className="flex items-center gap-2">
            <span className="text-dim">Radius</span>
            <input type="range" min={5} max={80} step={5} value={radius} onChange={(e) => setRadius(+e.target.value)} className="flex-1" aria-label="Offline region radius" />
            <span className="num w-12 text-right">{radius} km</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            <button className="btn btn-primary btn-sm" disabled={!center || !!busy} onClick={cacheRegion}>
              {busy ? `Caching ${busy.done}/${busy.total}…` : center ? `Cache region around ${selected ? "selection" : "habitat"}` : "Select a point first"}
            </button>
            <button className="btn btn-sm btn-ghost" disabled={!tileCount || !!busy} onClick={clear}>Clear tiles</button>
          </div>
          <div className="text-[10.5px] text-faint">Caches the currently enabled imagery layers, up to {MAX_TILES} tiles per request (deepest zoom levels are skipped when the budget is reached).</div>
          {msg && <Notice>{msg}</Notice>}
          {regions.length > 0 && (
            <div>
              <div className="label mb-1">Cached regions</div>
              {regions.map((r, i) => (
                <button key={i} className="flex w-full justify-between gap-2 rounded px-1 py-0.5 text-left text-[11px] hover:bg-raised" onClick={() => useStore.getState().fly(r.lon, r.lat, r.radius_km * 4000)}>
                  <span className="num">{fmtPt(r, 3)} · {r.radius_km} km · {r.tiles} tiles</span><span className="text-faint">{fmtWhen(r.at)}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </Section>
  );
}
