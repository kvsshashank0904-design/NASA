"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { apiGet } from "@/lib/api";
import { fmtPt } from "@/lib/format";
import { useStore } from "@/lib/store";
import type { Layer } from "@/lib/types";
import MarsGlobe from "./MarsGlobe";

const NAV = [
  { href: "/", label: "Dashboard", d: "M3 12l9-8 9 8M5 10v10h5v-6h4v6h5V10" },
  { href: "/explorer", label: "Explorer", d: "M12 21a9 9 0 100-18 9 9 0 000 18zM3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18" },
  { href: "/planner", label: "Planner", d: "M5 19a2 2 0 100-4 2 2 0 000 4zM19 9a2 2 0 100-4 2 2 0 000 4zM7 17h6a4 4 0 004-4v-4" },
  { href: "/science", label: "Science", d: "M9 3h6M10 3v6l-5 9a2 2 0 002 3h10a2 2 0 002-3l-5-9V3M7.5 15h9" },
  { href: "/ai", label: "MARS AI", d: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z" },
  { href: "/simulation", label: "Simulation", d: "M5 4l14 8-14 8z" },
  { href: "/data", label: "Data", d: "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" },
];
const WIDE = new Set(["/", "/data"]);

type SearchHit = { name: string; type: string; kind: string; lon: number; lat: number };

export default function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const set = useStore((s) => s.set);
  const backend = useStore((s) => s.backend);
  const browserOnline = useStore((s) => s.browserOnline);
  const sceneMode = useStore((s) => s.sceneMode);
  const pickMode = useStore((s) => s.pickMode);
  const sim = useStore((s) => s.sim);
  const layerDefs = useStore((s) => s.layerDefs);
  const layers = useStore((s) => s.layers);
  const [layersFromCache, setLayersFromCache] = useState<string | null>(null);

  useEffect(() => { useStore.persist.rehydrate(); }, []);

  useEffect(() => {
    let alive = true;
    const check = async () => {
      try {
        await apiGet("/api/v1/health", { cache: false });
        if (alive) set({ backend: "up" });
      } catch { if (alive) set({ backend: "down" }); }
    };
    check();
    const t = setInterval(check, 20000);
    const on = () => set({ browserOnline: navigator.onLine });
    on();
    window.addEventListener("online", on); window.addEventListener("offline", on);
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
    return () => { alive = false; clearInterval(t); window.removeEventListener("online", on); window.removeEventListener("offline", on); };
  }, [set]);

  useEffect(() => {
    apiGet<{ layers: Layer[] }>("/api/v1/planet/layers").then((r) => {
      useStore.getState().setLayerDefs(r.data.layers);
      setLayersFromCache(r.cached ? r.cachedAt || "earlier" : null);
    }).catch(() => {});
  }, [backend]);

  const offline = backend === "down" || !browserOnline;
  const activeImagery = layerDefs.filter((l) => l.kind === "wmts" && layers[l.id]?.visible);

  return (
    <div className="frame" style={{ ["--panel-w" as string]: WIDE.has(path) ? "560px" : "440px" }}>
      <header className="flex items-center gap-3 border-b border-line bg-ink px-3">
        <Link href="/" className="flex items-center gap-2 pr-2">
          <span className="grid h-7 w-7 place-items-center rounded-full" style={{ background: "radial-gradient(circle at 35% 30%, #f08a5d, #b23a1e 60%, #5a1a0c)" }} aria-hidden />
          <span className="text-[15px] font-semibold tracking-[0.18em] text-white">MARS-X</span>
          <span className="hide-narrow label ml-1">Exploration &amp; Mission Planning</span>
        </Link>
        <div className="flex-1" />
        <Search />
        <StatusPill offline={offline} backend={backend} browserOnline={browserOnline} />
      </header>

      <nav className="flex flex-col gap-0.5 border-r border-line bg-ink py-2">
        {NAV.map((n) => {
          const active = n.href === "/" ? path === "/" : path.startsWith(n.href);
          return (
            <Link key={n.href} href={n.href} aria-current={active ? "page" : undefined}
              className={`relative flex flex-col items-center gap-1 px-1 py-2.5 text-[10px] font-medium tracking-wide transition-colors ${active ? "text-white" : "text-faint hover:text-text"}`}>
              {active && <span className="absolute left-0 top-2 bottom-2 w-[2px] rounded bg-blue hide-narrow" />}
              <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke={active ? (n.href === "/ai" ? "#e2603a" : "#3b9eff") : "currentColor"} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d={n.d} /></svg>
              {n.label}
            </Link>
          );
        })}
      </nav>

      <div className="globe-wrap bg-void">
        <MarsGlobe />
        {/* HUD */}
        <div className="pointer-events-none absolute left-3 top-3 flex flex-col gap-2">
          {pickMode && (
            <div className="pointer-events-auto card fade-in flex items-center gap-2 border-blue px-3 py-2 text-[12px]">
              <span className="h-2 w-2 rounded-full bg-blue pulse" /> Click the globe to set the <b className="text-white">{pickMode}</b>
              <button className="btn btn-sm btn-ghost" onClick={() => set({ pickMode: null })}>Cancel</button>
            </div>
          )}
          {sim && <div className="badge badge-sim !h-6 !px-2.5 !text-[11px]">Simulation mode · values are not measurements</div>}
          {offline && <div className="badge badge-warn !h-6 !px-2.5 !text-[11px]">Offline · showing cached map tiles and saved mission data</div>}
        </div>
        <div className="absolute right-3 top-3 flex gap-1.5">
          <div className="card flex overflow-hidden p-0.5">
            {(["3D", "2D"] as const).map((m) => (
              <button key={m} className={`btn btn-sm ${sceneMode === m ? "btn-on" : "btn-ghost"}`} onClick={() => set({ sceneMode: m })} aria-pressed={sceneMode === m}>{m}</button>
            ))}
          </div>
          <button className="btn btn-sm" title="Reset to global view" onClick={() => useStore.getState().fly(77.45, 12, 1.15e7)}>Global view</button>
        </div>
        <div className="pointer-events-none absolute bottom-7 left-3 right-3 flex flex-wrap items-end justify-between gap-2">
          <div className="card flex items-center gap-3 px-2.5 py-1.5 text-[11px]">
            <span className="label">Cursor</span><span id="cursor-readout" className="num text-text">move over the globe</span>
            <span className="label hide-narrow">Altitude</span><span id="camera-altitude" className="num hide-narrow text-text">11500 km</span>
            <span className="hide-narrow text-faint">planetocentric · east-positive · Mars 2000 sphere</span>
          </div>
          <div className="card hide-narrow max-w-[46%] truncate px-2.5 py-1.5 text-[10.5px] text-dim" title={activeImagery.map((l) => l.attribution).join(" | ")}>
            {activeImagery.length ? activeImagery.map((l) => `${l.title}`).join("  ·  ") : "No imagery layer enabled"}
            {layersFromCache && <span className="text-warn"> · layer list from cache</span>}
          </div>
        </div>
      </div>

      <aside className="overflow-y-auto border-l border-line bg-ink">{children}</aside>
    </div>
  );
}

function StatusPill({ offline, backend, browserOnline }: { offline: boolean; backend: string; browserOnline: boolean }) {
  const txt = backend === "unknown" ? "Connecting" : !browserOnline ? "No network" : backend === "down" ? "Backend unreachable" : "Backend online";
  return (
    <div className={`badge ${backend === "unknown" ? "" : offline ? "badge-warn" : "badge-ok"} !h-6 !px-2`} title="Backend health is polled every 20 s">
      <span className={`h-1.5 w-1.5 rounded-full ${offline ? "bg-warn" : "bg-ok"} ${backend === "unknown" ? "pulse" : ""}`} />{txt}
    </div>
  );
}

function Search() {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const router = useRouter();

  useEffect(() => {
    if (q.trim().length < 2) { setHits(null); setErr(null); return; }
    const coord = parseCoord(q);
    if (coord) { setHits([{ name: `Go to ${fmtPt(coord)}`, type: "Coordinate", kind: "coordinate", ...coord }]); return; }
    const t = setTimeout(() => {
      apiGet<{ results: SearchHit[] }>(`/api/v1/planet/locations?q=${encodeURIComponent(q.trim())}&limit=10`)
        .then((r) => { setHits(r.data.results); setErr(null); })
        .catch((e) => { setHits([]); setErr(e.message); });
    }, 220);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    const f = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", f);
    return () => document.removeEventListener("mousedown", f);
  }, []);

  const go = (h: SearchHit) => {
    const st = useStore.getState();
    st.pick({ lon: h.lon, lat: h.lat, name: h.kind === "coordinate" ? undefined : h.name });
    st.fly(h.lon, h.lat, h.kind === "nomenclature" ? 400000 : 30000);
    setOpen(false); setQ("");
    router.push("/explorer");
  };

  return (
    <div ref={box} className="relative w-[min(340px,42vw)]">
      <input className="input pl-8" placeholder="Search features, landing sites, or 18.44N 77.45E" value={q} aria-label="Search Mars locations"
        onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
          if (e.key !== "Enter") return;
          // resolve from the text itself so Enter works even before the debounced lookup has returned
          const coord = parseCoord(q);
          if (coord) return go({ name: "", type: "Coordinate", kind: "coordinate", ...coord });
          if (hits?.[0]) return go(hits[0]);
          if (q.trim().length >= 2) apiGet<{ results: SearchHit[] }>(`/api/v1/planet/locations?q=${encodeURIComponent(q.trim())}&limit=1`).then((r) => { if (r.data.results[0]) go(r.data.results[0]); else { setHits([]); setOpen(true); } }).catch((er) => { setHits([]); setErr(er.message); setOpen(true); });
        }} />
      <svg className="absolute left-2.5 top-[8px] text-faint" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></svg>
      {open && hits && (
        <div className="card fade-in absolute right-0 top-9 z-30 max-h-[60vh] w-full overflow-y-auto p-1 shadow-2xl">
          {hits.length === 0 && <div className="px-2 py-2 text-dim">{err || "No named feature matches. The index holds 1,783 IAU names plus landing sites and science targets."}</div>}
          {hits.map((h, i) => (
            <button key={i} className="flex w-full items-center justify-between gap-2 rounded px-2 py-1.5 text-left hover:bg-raised" onClick={() => go(h)}>
              <span className="min-w-0"><span className="block truncate text-text">{h.name}</span><span className="block truncate text-[11px] text-faint">{h.type}</span></span>
              <span className="num shrink-0 text-[10.5px] text-dim">{fmtPt(h, 2)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function parseCoord(s: string): { lon: number; lat: number } | null {
  const m = s.match(/^\s*(-?\d{1,2}(?:\.\d+)?)\s*°?\s*([NSns])?[,\s]+(-?\d{1,3}(?:\.\d+)?)\s*°?\s*([EWew])?\s*$/);
  if (!m) return null;
  let lat = parseFloat(m[1]), lon = parseFloat(m[3]);
  if (m[2]?.toUpperCase() === "S") lat = -lat;
  if (m[4]?.toUpperCase() === "W") lon = -lon;
  if (Math.abs(lat) > 90 || Math.abs(lon) > 360) return null;
  if (lon > 180) lon -= 360;
  return { lon, lat };
}
