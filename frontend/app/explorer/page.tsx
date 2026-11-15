"use client";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { apiSend } from "@/lib/api";
import { fmtPt, pct } from "@/lib/format";
import { useStore } from "@/lib/store";
import type { Layer } from "@/lib/types";
import { CachedNote, KindBadge, Notice, Page, Section, Spinner, Stat, Switch, useApi } from "@/components/ui";
import OfflinePanel from "@/components/OfflinePanel";

type LocInfo = {
  lon: number; lat: number; crs: string;
  elevation: { value_m: number | null; datum?: string; quality?: string; dataset?: string; resolution_m?: number; limitations?: string; unavailable?: string };
  nearest_named_features: { name: string; type: string; distance_km: number; lon: number; lat: number }[];
  hydrous_mineral_detections_within_50km: { count: number; nearest_km: number | null; dataset: string };
  rovers_nearby: { rover: string; distance_km: number; latest_sol: number }[];
  regional_imagery_available: { id: string; title: string }[];
};
type Analysis = {
  bbox: number[]; dem: { name: string; effective_resolution_m: number; limitations: string };
  slope_deg: { mean: number; p95: number; max: number } | null; elevation_m: { min: number; max: number; mean: number } | null;
  hazard_fraction: Record<string, number>; quality_fraction: Record<string, number>; hazard_basis: string; overlays: Record<string, string>;
};

const CATEGORY_ORDER = ["base", "orbital", "regional", "elevation", "slope", "roughness", "thermal", "mineral", "geology", "hazard", "rover", "science", "route"];

export default function ExplorerPage() {
  const selected = useStore((s) => s.selected);
  const layerDefs = useStore((s) => s.layerDefs);
  const set = useStore((s) => s.set);
  const router = useRouter();
  const info = useApi<LocInfo>(selected ? `/api/v1/planet/location-info?lon=${selected.lon.toFixed(6)}&lat=${selected.lat.toFixed(6)}` : null);
  const [radius, setRadius] = useState(6);
  const [an, setAn] = useState<{ loading: boolean; error: string | null; data: Analysis | null }>({ loading: false, error: null, data: null });

  const analyze = async () => {
    if (!selected) return;
    setAn({ loading: true, error: null, data: null });
    try {
      const data = await apiSend<Analysis>("POST", "/api/v1/hazards/analyze", { center: { lon: selected.lon, lat: selected.lat }, radius_km: radius });
      setAn({ loading: false, error: null, data });
      const st = useStore.getState();
      st.set({ overlay: { kind: "hazard", url: data.overlays.hazard, bbox: data.bbox } });
      if (!["mx_slope", "mx_hazard", "mx_quality"].some((id) => st.layers[id]?.visible)) st.toggleLayer("mx_hazard", true);
      st.fly(selected.lon, selected.lat, radius * 1000 * 4.5);
    } catch (e) { setAn({ loading: false, error: (e as Error).message, data: null }); }
  };

  const groups = useMemo(() => {
    const m = new Map<string, Layer[]>();
    for (const l of layerDefs) m.set(l.category, [...(m.get(l.category) || []), l]);
    return CATEGORY_ORDER.filter((c) => m.has(c)).map((c) => ({ id: c, title: m.get(c)![0].category_title, layers: m.get(c)! }));
  }, [layerDefs]);

  return (
    <Page title="Mars Explorer" kicker="3D globe · layers · location intelligence">
      <Section title="Selected location" right={<CachedNote f={info.res} />}>
        {!selected && <p className="text-dim">Click anywhere on the globe, or use the search box, to inspect a location.</p>}
        {selected && (
          <div className="flex flex-col gap-2.5">
            <div>
              {selected.name && <div className="text-[14px] font-semibold text-white">{selected.name}</div>}
              <div className="num text-[13px] text-text">{fmtPt(selected, 5)}</div>
            </div>
            {info.loading && <Spinner text="Querying elevation and nearby data" />}
            {info.error && <Notice tone="danger">{info.error}</Notice>}
            {info.data && (
              <>
                <div className="grid grid-cols-2 gap-3">
                  <Stat label="Elevation" value={info.data.elevation.value_m != null ? `${info.data.elevation.value_m.toLocaleString()} m` : "unavailable"}
                    sub={info.data.elevation.value_m != null ? `${info.data.elevation.datum}` : info.data.elevation.unavailable} />
                  <Stat label="Data quality" value={info.data.elevation.quality || "n/a"} tone={info.data.elevation.quality === "measured" ? "ok" : "warn"}
                    sub={info.data.elevation.resolution_m ? `${info.data.elevation.resolution_m} m/px DEM` : undefined} />
                </div>
                {info.data.elevation.dataset && <div className="text-[11px] text-dim"><span className="text-faint">Source · </span>{info.data.elevation.dataset}. {info.data.elevation.limitations}</div>}
                <div className="divider" />
                <div className="text-[12px]">
                  <div className="label mb-1">Nearest named features (IAU)</div>
                  {info.data.nearest_named_features.length === 0 && <span className="text-dim">None within 300 km in the index.</span>}
                  {info.data.nearest_named_features.slice(0, 4).map((f) => (
                    <button key={f.name} className="flex w-full justify-between rounded px-1 py-0.5 text-left hover:bg-raised" onClick={() => { useStore.getState().pick({ lon: f.lon, lat: f.lat, name: f.name }); useStore.getState().fly(f.lon, f.lat); }}>
                      <span>{f.name} <span className="text-faint">· {f.type}</span></span><span className="num text-dim">{f.distance_km} km</span>
                    </button>
                  ))}
                </div>
                <div className="flex flex-wrap gap-1.5 text-[11px]">
                  <span className="badge">{info.data.hydrous_mineral_detections_within_50km.count} CRISM/OMEGA hydrous detections ≤ 50 km</span>
                  {info.data.rovers_nearby.map((r) => <span key={r.rover} className="badge badge-blue">{r.rover.split(" (")[0]} {r.distance_km} km</span>)}
                  {info.data.regional_imagery_available.map((r) => <span key={r.id} className="badge badge-ok" title="High-resolution imagery layer covers this point">{r.title.replace("MRO ", "")}</span>)}
                </div>
              </>
            )}
            <div className="flex flex-wrap gap-1.5">
              <button className="btn btn-sm" onClick={() => set({ habitat: selected })}>Set as habitat</button>
              <button className="btn btn-sm" onClick={() => set({ start: selected })}>Route start</button>
              <button className="btn btn-sm" onClick={() => { set({ goal: selected }); router.push("/planner"); }}>Route destination →</button>
              <button className="btn btn-sm" onClick={() => router.push("/science")}>Science nearby →</button>
            </div>
          </div>
        )}
      </Section>

      <Section title="Terrain analysis around selection">
        <div className="flex items-center gap-2">
          <label className="text-dim" htmlFor="rad">Radius</label>
          <input id="rad" type="range" min={1} max={60} value={radius} onChange={(e) => setRadius(+e.target.value)} className="flex-1" />
          <span className="num w-12 text-right">{radius} km</span>
          <button className="btn btn-primary btn-sm" disabled={!selected || an.loading} onClick={analyze}>{an.loading ? "Computing…" : "Analyze"}</button>
        </div>
        {an.loading && <Spinner text="Reading DEM and computing slope" />}
        {an.error && <div className="mt-2"><Notice tone="danger">{an.error}</Notice></div>}
        {an.data && (
          <div className="mt-3 flex flex-col gap-2 fade-in">
            <div className="grid grid-cols-3 gap-3">
              <Stat label="Mean slope" value={`${an.data.slope_deg?.mean ?? "n/a"}°`} />
              <Stat label="95th pct slope" value={`${an.data.slope_deg?.p95 ?? "n/a"}°`} />
              <Stat label="Relief" value={an.data.elevation_m ? `${(an.data.elevation_m.max - an.data.elevation_m.min).toFixed(0)} m` : "n/a"} />
            </div>
            <HazardBar f={an.data.hazard_fraction} />
            <div className="text-[11px] text-dim">
              <KindBadge kind="inferred" /> {an.data.dem.name} at {an.data.dem.effective_resolution_m} m cells. Measured {pct(an.data.quality_fraction["measured"] || 0)}, interpolated {pct(an.data.quality_fraction["interpolated between measurements"] || 0)}, no data {pct(an.data.quality_fraction["no data"] || 0)}.
            </div>
            <Notice tone="warn">{an.data.hazard_basis}</Notice>
            <div className="text-[11px] text-faint">Toggle the Slope, Inferred hazard or Data quality layers below to view this region&apos;s overlays.</div>
          </div>
        )}
      </Section>

      <Section title="Map layers" right={<span className="text-[10.5px] text-faint">{layerDefs.length} layers</span>}>
        {layerDefs.length === 0 && <Notice tone="warn">Layer catalogue unavailable: the backend is unreachable and no cached copy exists yet.</Notice>}
        <div className="flex flex-col gap-3">
          {groups.map((g) => (
            <div key={g.id}>
              <div className="mb-1 text-[11px] font-semibold text-dim">{g.title}</div>
              <div className="flex flex-col">{g.layers.map((l) => <LayerRow key={l.id} layer={l} />)}</div>
            </div>
          ))}
        </div>
      </Section>

      <OfflinePanel />
    </Page>
  );
}

function HazardBar({ f }: { f: Record<string, number> }) {
  const parts: [string, string, string][] = [["nominal", "#3ecf8e", "Nominal"], ["caution", "#f0c33a", "Caution"], ["high", "#e67e22", "High"], ["impassable", "#e74c3c", "Impassable"], ["unknown (no elevation data)", "#78788c", "No data"]];
  return (
    <div>
      <div className="flex h-2.5 overflow-hidden rounded-full bg-[#16203a]">
        {parts.map(([k, c]) => <div key={k} style={{ width: `${(f[k] || 0) * 100}%`, background: c }} />)}
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[10.5px] text-dim">
        {parts.map(([k, c, n]) => <span key={k} className="flex items-center gap-1"><i className="inline-block h-2 w-2 rounded-sm" style={{ background: c }} />{n} <span className="num">{pct(f[k] || 0, 1)}</span></span>)}
      </div>
    </div>
  );
}

function LayerRow({ layer }: { layer: Layer }) {
  const st = useStore((s) => s.layers[layer.id]);
  const toggle = useStore((s) => s.toggleLayer);
  const setOpacity = useStore((s) => s.setOpacity);
  const overlay = useStore((s) => s.overlay);
  const [open, setOpen] = useState(false);
  const on = !!st?.visible;
  const needsRegion = layer.kind === "overlay" && !overlay;
  const regional = layer.kind === "wmts" && layer.bbox && layer.bbox[2] - layer.bbox[0] < 300;
  useEffect(() => { if (!on) setOpen(false); }, [on]);
  return (
    <div className={`rounded-md border px-2 py-1.5 ${on ? "border-line-strong bg-panel" : "border-transparent"}`}>
      <div className="flex items-center gap-2">
        <Switch checked={on} onChange={(v) => toggle(layer.id, v)} label={`Toggle ${layer.title}`} />
        <button className="min-w-0 flex-1 text-left" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          <span className={`block truncate text-[12px] ${on ? "text-white" : "text-text"}`}>{layer.title}</span>
          <span className="block truncate text-[10.5px] text-faint">{[layer.instrument, layer.resolution].filter(Boolean).join(" · ")}</span>
        </button>
        {regional && <button className="btn btn-ghost btn-sm" title="Fly to this layer's coverage" onClick={() => { const b = layer.bbox!; useStore.getState().fly((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, Math.max(15000, (b[3] - b[1]) * 59000 * 2.2)); if (!on) toggle(layer.id, true); }}>Go</button>}
        <button className="btn btn-ghost btn-sm" onClick={() => setOpen((o) => !o)} aria-label={`Details for ${layer.title}`}>{open ? "−" : "i"}</button>
      </div>
      {on && needsRegion && <div className="mt-1 text-[10.5px] text-warn">Select a point and run “Analyze” (or plan a route) to compute this overlay for a region.</div>}
      {on && (layer.kind === "wmts" || layer.kind === "overlay") && (
        <div className="mt-1 flex items-center gap-2 pl-[38px]">
          <span className="text-[10px] text-faint">Opacity</span>
          <input type="range" min={0} max={1} step={0.05} value={st?.opacity ?? 1} onChange={(e) => setOpacity(layer.id, +e.target.value)} className="flex-1" aria-label={`${layer.title} opacity`} />
          <span className="num w-8 text-right text-[10px] text-dim">{Math.round((st?.opacity ?? 1) * 100)}%</span>
        </div>
      )}
      {open && (
        <dl className="mt-2 grid grid-cols-[86px_1fr] gap-x-2 gap-y-1 border-t border-line pt-2 text-[11px] fade-in">
          <dt className="text-faint">Description</dt><dd className="text-dim">{(layer.description || "No description in the source catalogue.").slice(0, 420)}{(layer.description || "").length > 420 ? "…" : ""}</dd>
          <dt className="text-faint">Mission</dt><dd>{layer.mission || "n/a"}{layer.instrument ? ` · ${layer.instrument}` : ""}</dd>
          <dt className="text-faint">Source</dt><dd>{layer.source}</dd>
          <dt className="text-faint">Observed</dt><dd>{layer.timestamp || "not stated by source"}</dd>
          <dt className="text-faint">Resolution</dt><dd>{layer.resolution || "not stated"}{layer.max_level != null ? ` · tile levels 0–${layer.max_level}` : ""}</dd>
          {layer.bbox && <><dt className="text-faint">Coverage</dt><dd className="num">{layer.bbox.map((v) => v.toFixed(2)).join(", ")}</dd></>}
          <dt className="text-faint">Limitations</dt><dd className="text-[#f3d9a8]">{layer.limitations}</dd>
        </dl>
      )}
    </div>
  );
}

