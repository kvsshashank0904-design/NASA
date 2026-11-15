"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { fmtDist, fmtPt } from "@/lib/format";
import { useStore } from "@/lib/store";
import type { Target } from "@/lib/types";
import { Bar, CachedNote, Notice, Page, Section, Spinner, useApi } from "@/components/ui";

type Res = {
  origin: { lon: number; lat: number } | null; radius_km: number | null; count: number; targets: Target[];
  scoring: { weights: Record<string, number>; components: Record<string, string>; note: string }; disclaimer: string;
};
type Refs = { references: { id: string; citation: string; url: string | null }[] };

const KIND_LABEL: Record<string, [string, string]> = {
  curated: ["Referenced site", "badge-mars"], rover_waypoint: ["Rover observation", "badge-blue"],
  mineral_detection: ["Orbital mineral detection", "badge-ok"], gazetteer: ["Named feature", ""],
};
const COMP_COLORS: Record<string, string> = { relevance: "#e2603a", mineralogy: "#5ee0d0", geology: "#f0a13a", accessibility: "#3b9eff", confidence: "#9db4d6" };

export default function SciencePage() {
  const habitat = useStore((s) => s.habitat);
  const selected = useStore((s) => s.selected);
  const missionTargets = useStore((s) => s.missionTargets);
  const [originKind, setOriginKind] = useState<"global" | "habitat" | "selected">("global");
  const [radius, setRadius] = useState(10);
  const [q, setQ] = useState("");
  const [qd, setQd] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const router = useRouter();

  useEffect(() => { const t = setTimeout(() => setQd(q.trim()), 250); return () => clearTimeout(t); }, [q]);
  useEffect(() => { if (originKind === "habitat" && !habitat) setOriginKind("global"); if (originKind === "selected" && !selected) setOriginKind("global"); }, [originKind, habitat, selected]);

  const origin = originKind === "habitat" ? habitat : originKind === "selected" ? selected : null;
  const path = `/api/v1/science/targets?limit=40${origin ? `&lon=${origin.lon.toFixed(5)}&lat=${origin.lat.toFixed(5)}&radius_km=${radius}` : ""}${qd ? `&q=${encodeURIComponent(qd)}` : ""}`;
  const res = useApi<Res>(path);
  const refs = useApi<Refs>("/api/v1/science/references");
  const refMap = Object.fromEntries((refs.data?.references || []).map((r) => [r.id, r]));

  useEffect(() => {
    if (res.data) { useStore.getState().set({ targets: res.data.targets }); useStore.getState().toggleLayer("mx_targets", true); }
  }, [res.data]);

  return (
    <Page title="Science Discovery" kicker="Targets · evidence · scoring">
      <Section title="Search area" right={<CachedNote f={res.res} />}>
        <div className="flex flex-wrap gap-1.5">
          <button className={`btn btn-sm ${originKind === "global" ? "btn-on" : ""}`} onClick={() => setOriginKind("global")}>All of Mars (curated)</button>
          <button className={`btn btn-sm ${originKind === "habitat" ? "btn-on" : ""}`} disabled={!habitat} onClick={() => setOriginKind("habitat")} title={habitat ? fmtPt(habitat) : "Set a habitat in Explorer first"}>Around habitat</button>
          <button className={`btn btn-sm ${originKind === "selected" ? "btn-on" : ""}`} disabled={!selected} onClick={() => setOriginKind("selected")} title={selected ? fmtPt(selected) : "Select a point on the globe first"}>Around selection</button>
        </div>
        {origin && (
          <div className="mt-2 flex items-center gap-2">
            <span className="text-dim">Radius</span>
            <input type="range" min={1} max={300} value={radius} onChange={(e) => setRadius(+e.target.value)} className="flex-1" aria-label="Search radius" />
            <span className="num w-14 text-right">{radius} km</span>
          </div>
        )}
        <input className="input mt-2" placeholder="Filter: delta, clay, carbonate, channel, sulfate…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Filter targets" />
        <div className="mt-2 text-[10.5px] text-faint">
          {origin ? `Searching curated sites, rover waypoints (≤ 50 km), CRISM/OMEGA detections and IAU named features within ${radius} km of ${fmtPt(origin, 3)}.`
            : "Showing the curated, literature-referenced catalogue. Choose an origin to add rover waypoints, mineral detections and named features nearby."}
        </div>
      </Section>

      <Notice>{res.data?.disclaimer || "No target here constitutes evidence of past or present life."} Scores rank exploration interest; they are heuristics, not measurements.</Notice>

      {res.loading && <Spinner text="Scoring targets" />}
      {res.error && <Notice tone="danger">{res.error}</Notice>}
      {res.data && res.data.targets.length === 0 && <Notice tone="warn">No targets match. Widen the radius or clear the filter.</Notice>}
      {res.data && res.data.targets.length > 0 && <div className="text-[11px] text-dim">{res.data.count} target(s) found{res.data.count > res.data.targets.length ? `, top ${res.data.targets.length} shown` : ""} · all are plotted on the globe</div>}

      {res.data?.targets.map((t) => {
        const open = openId === t.id;
        const inMission = missionTargets.some((m) => m.id === t.id);
        const kl = KIND_LABEL[t.kind || "curated"] || [t.kind || "", ""];
        return (
          <section key={t.id} className={`card p-3 ${inMission ? "border-mars" : ""}`}>
            <div className="flex items-start gap-3">
              <div className="grid h-11 w-11 shrink-0 place-items-center rounded-md border border-line-strong bg-ink">
                <span className="num text-[14px] font-semibold text-white">{Math.round(t.score)}</span>
              </div>
              <div className="min-w-0 flex-1">
                <button className="block w-full truncate text-left text-[13px] font-semibold text-white hover:underline" onClick={() => { useStore.getState().pick({ lon: t.lon, lat: t.lat, name: t.name }); useStore.getState().fly(t.lon, t.lat, t.kind === "gazetteer" ? 200000 : 12000); }}>{t.name}</button>
                <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-dim">
                  <span className={`badge ${kl[1]}`}>{kl[0]}</span><span>{t.category}</span>
                  {t.distance_m != null && <span className="num">· {fmtDist(t.distance_m)}</span>}
                </div>
              </div>
            </div>
            <p className="mt-2 text-[12px] text-text">{t.summary}</p>
            {t.score_components && (
              <div className="mt-2 grid grid-cols-5 gap-2">
                {Object.entries(t.score_components).map(([k, v]) => (
                  <div key={k} title={res.data!.scoring.components[k]}>
                    <div className="mb-0.5 flex justify-between text-[9.5px] capitalize text-faint"><span>{k.slice(0, 7)}</span><span className="num">{v.toFixed(2)}</span></div>
                    <Bar value={v} color={COMP_COLORS[k]} height={4} />
                  </div>
                ))}
              </div>
            )}
            {open && (
              <div className="mt-3 flex flex-col gap-2 border-t border-line pt-2 text-[11.5px] fade-in">
                {t.evidence && <div><span className="badge badge-blue mr-1.5">Observed evidence</span><span className="text-text">{t.evidence}</span></div>}
                {t.hypothesis && <div><span className="badge badge-warn mr-1.5">Hypothesis</span><span className="text-[#f3d9a8]">{t.hypothesis}</span></div>}
                {!!t.minerals?.length && <div className="flex flex-wrap gap-1"><span className="text-faint">Minerals reported:</span>{t.minerals.map((m) => <span key={m} className="badge">{m}</span>)}</div>}
                {t.mineral_context && <div className="text-dim">CRISM/OMEGA hydrous detections within 25 km: <span className="num text-text">{t.mineral_context.detections_within_25km}</span>{t.mineral_context.nearest_m != null ? ` (nearest ${fmtDist(t.mineral_context.nearest_m)})` : ""}</div>}
                <div className="text-dim"><span className="text-faint">Coordinates · </span><span className="num">{fmtPt(t, 5)}</span> — {t.coordinate_source}</div>
                {!!t.reference_ids?.length && (
                  <div><div className="label mb-0.5">References</div>
                    {t.reference_ids.map((id) => refMap[id] ? (
                      <div key={id} className="text-dim">{refMap[id].citation} {refMap[id].url && <a className="text-blue hover:underline" href={refMap[id].url!} target="_blank" rel="noreferrer">link</a>}</div>
                    ) : <div key={id} className="text-faint">{id}</div>)}
                  </div>
                )}
                {!!t.datasets?.length && <div className="flex flex-wrap gap-1"><span className="text-faint">Datasets:</span>{t.datasets.map((d) => <span key={d} className="badge">{d}</span>)}</div>}
              </div>
            )}
            <div className="mt-2.5 flex flex-wrap gap-1.5">
              <button className="btn btn-sm" onClick={() => setOpenId(open ? null : t.id)} aria-expanded={open}>{open ? "Hide evidence" : "Evidence & sources"}</button>
              <button className={`btn btn-sm ${inMission ? "btn-on" : ""}`} onClick={() => (inMission ? useStore.getState().removeMissionTarget(t.id) : useStore.getState().addMissionTarget(t))}>{inMission ? "✓ In mission plan" : "Add to mission plan"}</button>
              <button className="btn btn-sm" onClick={() => { const st = useStore.getState(); st.set({ goal: { lon: t.lon, lat: t.lat, name: t.name }, ...(st.start ? {} : st.habitat ? { start: st.habitat } : {}) }); router.push("/planner"); }}>Plan route here →</button>
            </div>
          </section>
        );
      })}

      {res.data && (
        <Section title="How targets are scored">
          <div className="flex flex-col gap-1.5 text-[11px]">
            {Object.entries(res.data.scoring.weights).map(([k, w]) => (
              <div key={k} className="grid grid-cols-[92px_34px_1fr] gap-2">
                <span className="flex items-center gap-1.5 capitalize text-text"><i className="inline-block h-2 w-2 rounded-sm" style={{ background: COMP_COLORS[k] }} />{k}</span>
                <span className="num text-dim">{Math.round(w * 100)}%</span>
                <span className="text-dim">{res.data!.scoring.components[k]}</span>
              </div>
            ))}
          </div>
        </Section>
      )}
    </Page>
  );
}
