"use client";
import Link from "next/link";
import { useState } from "react";
import { Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { apiSend } from "@/lib/api";
import { fmtDist, fmtEnergy, fmtHours, fmtPt, fmtWhen, haversine, pct } from "@/lib/format";
import { PROFILE_COLORS, useStore } from "@/lib/store";
import type { Plan, Pt, RouteCandidate } from "@/lib/types";
import { KindBadge, Notice, Page, Section, Spinner, Stat } from "@/components/ui";

const WEIGHT_INFO: [string, string, string][] = [
  ["distance", "Distance (w_d)", "Penalty per metre driven"],
  ["slope", "Slope (w_s)", "Penalty for steep cells, (slope/limit)²"],
  ["roughness", "Roughness (w_r)", "Penalty for relief at the DEM pixel scale"],
  ["hazard", "Hazard (w_h)", "Penalty for caution/high classes and interpolated cells"],
  ["energy", "Energy (w_e)", "Penalty for traction energy (uphill costs more)"],
];
const PRESETS: Record<string, Record<string, number>> = {
  Balanced: { distance: 1, slope: 1.5, roughness: 1, hazard: 2, energy: 1 },
  "Safety first": { distance: 0.5, slope: 3, roughness: 1.5, hazard: 4, energy: 0.5 },
  "Save energy": { distance: 0.5, slope: 1, roughness: 0.5, hazard: 1.5, energy: 3 },
  "Fast transit": { distance: 1, slope: 0.5, roughness: 0.3, hazard: 1, energy: 0.2 },
};

export default function PlannerPage() {
  const start = useStore((s) => s.start);
  const goal = useStore((s) => s.goal);
  const habitat = useStore((s) => s.habitat);
  const selected = useStore((s) => s.selected);
  const pickMode = useStore((s) => s.pickMode);
  const plan = useStore((s) => s.plan);
  const profile = useStore((s) => s.selectedProfile);
  const showAll = useStore((s) => s.showAllCandidates);
  const planSavedAt = useStore((s) => s.planSavedAt);
  const missionTargets = useStore((s) => s.missionTargets);
  const missionId = useStore((s) => s.missionId);
  const set = useStore((s) => s.set);

  const [weights, setWeights] = useState(PRESETS.Balanced);
  const [maxSlope, setMaxSlope] = useState(25);
  const [margin, setMargin] = useState(20);
  const [mass, setMass] = useState(3000);
  const [speed, setSpeed] = useState(8);
  const [battery, setBattery] = useState(40);
  const [useBattery, setUseBattery] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [adv, setAdv] = useState(false);

  const straight = start && goal ? haversine(start, goal) : null;

  const run = async () => {
    if (!start || !goal) return;
    setBusy(true); setError(null); setSaveMsg(null);
    try {
      const p = await apiSend<Plan>("POST", "/api/v1/routes/plan", {
        start: { lon: start.lon, lat: start.lat }, goal: { lon: goal.lon, lat: goal.lat }, weights, max_slope_deg: maxSlope,
        caution_deg: Math.min(10, maxSlope), high_deg: Math.min(20, maxSlope), safety_margin: margin / 100,
        vehicle: { mass_kg: mass, speed_kmh: speed, battery_wh: useBattery ? battery * 1000 : null },
      });
      const st = useStore.getState();
      st.setPlan(p);
      st.toggleLayer("mx_routes", true);
      const [w, s, e, n] = p.analysis_bbox;
      st.set({ overlay: { kind: "hazard", url: `/api/v1/terrain/overlay.png?kind=hazard&west=${w}&south=${s}&east=${e}&north=${n}`, bbox: p.analysis_bbox }, missionId: null });
      st.fly((start.lon + goal.lon) / 2, (start.lat + goal.lat) / 2, Math.max(5000, p.straight_line_m * 3.2));
    } catch (e) { setError((e as Error).message); }
    setBusy(false);
  };

  const cand = plan?.candidates.find((c) => c.profile === profile) || plan?.candidates[0] || null;

  const save = async () => {
    if (!plan || !cand) return;
    setSaveMsg(null);
    try {
      const m = await apiSend<{ id: number }>("POST", "/api/v1/missions", {
        name: `Traverse to ${goal?.name || fmtPt(plan.goal, 3)}`, start: plan.start, goal: plan.goal,
        objectives: missionTargets.map((t) => `Investigate ${t.name}`), target_ids: missionTargets.map((t) => t.id), constraints: plan.constraints,
      });
      const body: Record<string, unknown> = {};
      if (cand.route_id) body.selected_route_id = cand.route_id;
      if (plan.return_route?.route_id) body.return_route_id = plan.return_route.route_id;
      if (Object.keys(body).length) await apiSend("PATCH", `/api/v1/missions/${m.id}`, body);
      set({ missionId: m.id });
      setSaveMsg(`Saved as mission #${m.id} with the ${cand.profile} route${plan.return_route ? " and its return route" : ""}.`);
    } catch (e) { setSaveMsg(`Could not save: ${(e as Error).message}`); }
  };

  return (
    <Page title="Mission Planner" kicker="Terrain-aware route planning · A* on real elevation data">
      <Section title="Start and destination">
        <div className="flex flex-col gap-2">
          <Endpoint label="Start" color="#3ecf8e" pt={start} picking={pickMode === "start"} onPick={() => set({ pickMode: pickMode === "start" ? null : "start" })}
            options={[habitat && ["Habitat", habitat], selected && ["Selection", selected]].filter(Boolean) as [string, Pt][]} onSet={(p) => set({ start: p })} />
          <Endpoint label="Destination" color="#e2603a" pt={goal} picking={pickMode === "goal"} onPick={() => set({ pickMode: pickMode === "goal" ? null : "goal" })}
            options={[selected && ["Selection", selected], ...missionTargets.slice(0, 2).map((t) => [t.name.slice(0, 18), t] as [string, Pt])].filter(Boolean) as [string, Pt][]} onSet={(p) => set({ goal: p })} />
          {start && goal && <button className="btn btn-ghost btn-sm self-start" onClick={() => set({ start: goal, goal: start })}>⇅ Swap</button>}
          {straight != null && <div className="text-[11px] text-dim">Straight-line distance <span className="num text-text">{fmtDist(straight)}</span>{straight > 550_000 && <span className="text-warn"> · exceeds the 10° analysis window; the planner will refuse this</span>}</div>}
          {!start && !goal && <div className="text-[11px] text-faint">Tip: for 20 m terrain, plan inside Jezero crater (search “Perseverance”). Elsewhere the planner uses 463 m MOLA.</div>}
        </div>
      </Section>

      <Section title="Mission constraints" right={<button className="btn btn-ghost btn-sm" onClick={() => setAdv((a) => !a)}>{adv ? "Hide weights" : "Edit weights"}</button>}>
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(PRESETS).map(([name, w]) => (
            <button key={name} className={`btn btn-sm ${JSON.stringify(w) === JSON.stringify(weights) ? "btn-on" : ""}`} onClick={() => setWeights(w)}>{name}</button>
          ))}
        </div>
        {adv && (
          <div className="mt-2 flex flex-col gap-1.5 fade-in">
            <div className="num rounded bg-ink px-2 py-1 text-[11px] text-dim">C = d · (w_d + w_s·S + w_r·R + w_h·H + w_e·E)</div>
            {WEIGHT_INFO.map(([k, name, tip]) => (
              <label key={k} className="flex items-center gap-2 text-[11px]" title={tip}>
                <span className="w-28 text-dim">{name}</span>
                <input type="range" min={0} max={6} step={0.1} value={weights[k]} onChange={(e) => setWeights({ ...weights, [k]: +e.target.value })} className="flex-1" />
                <span className="num w-7 text-right">{weights[k].toFixed(1)}</span>
              </label>
            ))}
            <div className="text-[10.5px] text-faint">These weights drive the “balanced” candidate. “Safest” and “shortest” use fixed weights so the comparison stays meaningful.</div>
          </div>
        )}
        <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2">
          <Slider label="Hard slope limit" value={maxSlope} min={5} max={35} unit="°" onChange={setMaxSlope} />
          <Slider label="Safety margin" value={margin} min={0} max={50} step={5} unit="%" onChange={setMargin} />
          <Slider label="Rover mass" value={mass} min={500} max={8000} step={100} unit=" kg" onChange={setMass} />
          <Slider label="Drive speed" value={speed} min={1} max={20} unit=" km/h" onChange={setSpeed} />
        </div>
        <label className="mt-2 flex items-center gap-2 text-[11px]">
          <input type="checkbox" checked={useBattery} onChange={(e) => setUseBattery(e.target.checked)} />
          <span className="text-dim">Energy budget</span>
          <input type="range" min={5} max={120} step={5} value={battery} disabled={!useBattery} onChange={(e) => setBattery(+e.target.value)} className="flex-1" />
          <span className="num w-14 text-right">{battery} kWh</span>
        </label>
        <div className="mt-1 text-[10.5px] text-faint">Vehicle values are planning assumptions (rolling resistance 0.15, drivetrain efficiency 0.7, 600 W hotel load). Safest and return routes use a slope limit of {(maxSlope * (1 - margin / 100)).toFixed(1)}°.</div>
        <button className="btn btn-primary mt-3 w-full" disabled={!start || !goal || busy} onClick={run}>
          {busy ? "Running A* on the traversability grid…" : !start || !goal ? "Set a start and a destination" : "Generate candidate routes"}
        </button>
        {busy && <Spinner text="Fetching elevation, computing slope/hazard grid, searching 4 routes" />}
        {error && <div className="mt-2"><Notice tone="danger">{error}</Notice></div>}
      </Section>

      {plan && (
        <>
          <Section title="Candidate routes" right={
            <label className="flex items-center gap-1.5 text-[10.5px] text-dim"><input type="checkbox" checked={showAll} onChange={(e) => set({ showAllCandidates: e.target.checked })} />show all on map</label>}>
            <div className="mb-2 text-[11px] text-dim">
              Plan <span className="num text-text">{plan.plan_id}</span> · {plan.dem.name} · <span className="num">{plan.dem.effective_resolution_m} m</span> cells · {plan.grid_cells.toLocaleString()} cells searched · saved {fmtWhen(planSavedAt)}
            </div>
            {plan.warnings.map((w, i) => <div key={i} className="mb-2"><Notice tone="warn">{w}</Notice></div>)}
            <div className="flex flex-col gap-1.5">
              {plan.candidates.map((c) => <CandidateRow key={c.profile} c={c} active={c.profile === cand?.profile} recommended={plan.comparison?.recommendation?.profile === c.profile} onSelect={() => set({ selectedProfile: c.profile, sim: null, simIndex: 0 })} />)}
              {plan.failures.map((f) => <Notice key={f.profile} tone="danger"><b>{f.profile}</b>: {f.reason}</Notice>)}
              {plan.candidates.length === 0 && <Notice tone="danger">No traversable route exists under these constraints. Raise the slope limit, lower the safety margin or choose a different destination.</Notice>}
            </div>
            {plan.comparison?.recommendation && <div className="mt-2 rounded-md border border-[#1f6b4a] bg-[#0a2419] px-3 py-2 text-[12px] text-[#bdf0d8]"><b>Recommended:</b> {plan.comparison.recommendation.reason}</div>}
          </Section>

          {cand && <RouteDetail c={cand} plan={plan} />}
          {plan.candidates.length > 1 && <Compare plan={plan} />}

          <Section title="Return journey">
            {plan.return_route ? (
              <div className="flex flex-col gap-2">
                <div className="grid grid-cols-4 gap-3">
                  <Stat label="Distance" value={fmtDist(plan.return_route.distance_m)} />
                  <Stat label="Energy" value={fmtEnergy(plan.return_route.energy.total_wh)} sub="derived" />
                  <Stat label="Mean slope" value={`${plan.return_route.mean_slope_deg}°`} />
                  <Stat label="Steepest cell" value={`${plan.return_route.max_cell_slope_deg}°`} />
                </div>
                <div className="text-[11px] text-dim"><span className="mr-1 inline-block h-0.5 w-5 align-middle" style={{ borderTop: `2px dashed ${PROFILE_COLORS.return}` }} />{plan.return_route.description}</div>
                {cand?.return_feasibility && (
                  <Notice tone={cand.return_feasibility.feasible ? "info" : "danger"}>
                    <b className={cand.return_feasibility.feasible ? "text-ok" : ""}>{cand.return_feasibility.feasible ? "Return feasible" : "Return NOT feasible"}</b> with the {cand.profile} outbound: round trip {fmtDist(cand.return_feasibility.round_trip_distance_m)}, {fmtHours(cand.return_feasibility.round_trip_duration_h)}, {fmtEnergy(cand.return_feasibility.round_trip_energy_wh_with_margin)} including the {pct(cand.return_feasibility.safety_margin || 0)} margin
                    {cand.return_feasibility.battery_wh ? ` against a ${fmtEnergy(cand.return_feasibility.battery_wh)} budget` : ""}. {cand.return_feasibility.reason}.
                  </Notice>
                )}
              </div>
            ) : <Notice tone="danger">No traversable return route was found. Do not commit to this traverse.</Notice>}
          </Section>

          {!!plan.science_nearby?.length && (
            <Section title="Science opportunities within 1.5 km of the route">
              {plan.science_nearby.map((t) => (
                <button key={t.id} className="flex w-full items-center justify-between gap-2 rounded px-1 py-1 text-left hover:bg-raised" onClick={() => useStore.getState().fly(t.lon, t.lat, 6000)}>
                  <span className="min-w-0"><span className="block truncate">{t.name}</span><span className="block truncate text-[10.5px] text-faint">{t.category}</span></span>
                  <span className="num shrink-0 text-[11px] text-dim">{t.offset_m} m off route · score {t.score}</span>
                </button>
              ))}
              <div className="mt-1 text-[10.5px] text-faint">Distance to the recommended route only; not a detour plan.</div>
            </Section>
          )}

          <Section title="Next steps">
            <div className="flex flex-wrap gap-1.5">
              <button className="btn btn-sm" disabled={!cand || missionId != null} onClick={save}>{missionId != null ? `Saved · mission #${missionId}` : "Save as mission"}</button>
              <Link href="/simulation" className="btn btn-mars btn-sm">Simulate this traverse →</Link>
              <Link href="/ai" className="btn btn-sm">Ask MARS AI about it</Link>
              <button className="btn btn-ghost btn-sm" onClick={() => useStore.getState().setPlan(null)}>Clear plan</button>
            </div>
            {saveMsg && <div className="mt-2 text-[11px] text-dim">{saveMsg}</div>}
            <div className="mt-2 text-[10.5px] text-faint">{plan.algorithm}. {plan.hazard_basis}</div>
          </Section>
        </>
      )}
    </Page>
  );
}

function Endpoint({ label, color, pt, picking, onPick, options, onSet }: { label: string; color: string; pt: Pt | null; picking: boolean; onPick: () => void; options: [string, Pt][]; onSet: (p: Pt) => void }) {
  return (
    <div className="flex items-center gap-2 rounded-md border border-line bg-ink px-2.5 py-2">
      <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: color }} />
      <div className="min-w-0 flex-1">
        <div className="label">{label}</div>
        <div className="num truncate text-[12px] text-text">{pt ? `${pt.name ? pt.name + " · " : ""}${fmtPt(pt, 4)}` : "not set"}</div>
      </div>
      {options.map(([n, p]) => <button key={n} className="btn btn-sm btn-ghost" onClick={() => onSet(p)} title={`Use ${n}`}>{n}</button>)}
      <button className={`btn btn-sm ${picking ? "btn-on" : ""}`} onClick={onPick}>{picking ? "Click globe…" : "Pick on map"}</button>
    </div>
  );
}

function Slider({ label, value, min, max, step = 1, unit, onChange }: { label: string; value: number; min: number; max: number; step?: number; unit: string; onChange: (v: number) => void }) {
  return (
    <label className="text-[11px]">
      <span className="flex justify-between text-dim"><span>{label}</span><span className="num text-text">{value}{unit}</span></span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(+e.target.value)} className="w-full" />
    </label>
  );
}

function CandidateRow({ c, active, recommended, onSelect }: { c: RouteCandidate; active: boolean; recommended: boolean; onSelect: () => void }) {
  const hz = c.hazard_exposure.caution + c.hazard_exposure.high;
  return (
    <button onClick={onSelect} aria-pressed={active} className={`rounded-md border px-2.5 py-2 text-left transition-colors ${active ? "border-blue bg-[#0c1c33]" : "border-line bg-ink hover:border-line-strong"}`}>
      <div className="flex items-center gap-2">
        <span className="h-1 w-6 rounded" style={{ background: PROFILE_COLORS[c.profile] }} />
        <span className="text-[13px] font-semibold capitalize text-white">{c.profile}</span>
        {recommended && <span className="badge badge-ok">Recommended</span>}
        {c.identical_to && <span className="badge" title="The search produced the same path as another profile">same path as {c.identical_to}</span>}
        <span className={`badge ml-auto ${c.confidence.level === "moderate" ? "badge-blue" : "badge-warn"}`}>{c.confidence.level} confidence</span>
      </div>
      <div className="mt-1.5 grid grid-cols-5 gap-2">
        <Stat label="Distance" value={fmtDist(c.distance_m)} />
        <Stat label="Duration" value={fmtHours(c.duration_h.value)} />
        <Stat label="Energy" value={fmtEnergy(c.energy.total_wh)} />
        <Stat label="Hazard" value={pct(hz, 1)} tone={hz > 0.2 ? "danger" : hz > 0.05 ? "warn" : "ok"} />
        <Stat label="Difficulty" value={`${c.difficulty_index.value}`} sub="/100" />
      </div>
    </button>
  );
}

const HZ_COLORS: Record<string, string> = { nominal: "#3ecf8e", caution: "#f0c33a", high: "#e67e22", impassable: "#e74c3c" };

function RouteDetail({ c, plan }: { c: RouteCandidate; plan: Plan }) {
  const data = c.elevation_profile.map((p) => ({ d: p.distance_m / 1000, z: p.elevation_m, slope: p.slope_deg, hazard: p.hazard, quality: p.quality }));
  const total = c.distance_m || 1;
  const segs = c.segments || [];
  return (
    <Section title={`${c.profile} route · terrain`} right={<KindBadge kind="derived estimate" />}>
      <div className="h-[150px]">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 6, right: 6, left: -8, bottom: 0 }}>
            <defs><linearGradient id="elev" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={PROFILE_COLORS[c.profile] || "#3b9eff"} stopOpacity={0.45} /><stop offset="1" stopColor={PROFILE_COLORS[c.profile] || "#3b9eff"} stopOpacity={0.03} /></linearGradient></defs>
            <CartesianGrid stroke="#1d2940" strokeDasharray="2 4" vertical={false} />
            <XAxis dataKey="d" type="number" domain={[0, "dataMax"]} tick={{ fill: "#5b6b86", fontSize: 10 }} tickFormatter={(v) => `${(+v).toFixed(1)}`} stroke="#1d2940" unit=" km" />
            <YAxis domain={["dataMin - 5", "dataMax + 5"]} tick={{ fill: "#5b6b86", fontSize: 10 }} stroke="#1d2940" width={52} tickFormatter={(v) => `${Math.round(+v)}`} />
            <Tooltip contentStyle={{ background: "#0d1422", border: "1px solid #2a3a59", borderRadius: 6, fontSize: 11 }} labelFormatter={(v) => `${Number(v).toFixed(2)} km`}
              formatter={(v, _n, item) => [`${v} m · slope ${item.payload.slope}° · ${item.payload.hazard} · ${item.payload.quality}`, "Elevation"]} />
            <ReferenceLine y={data[0]?.z} stroke="#5b6b86" strokeDasharray="3 3" />
            <Area type="monotone" dataKey="z" stroke={PROFILE_COLORS[c.profile] || "#3b9eff"} strokeWidth={1.6} fill="url(#elev)" isAnimationActive={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-1 text-[10px] text-faint">Elevation (m, MOLA areoid) along the route. Hazard class and DEM quality along track:</div>
      <div className="mt-1 flex h-2 overflow-hidden rounded-full bg-[#16203a]" title="Hazard class along the route">
        {segs.length ? segs.map((s, i) => <div key={i} style={{ width: `${((s.end_m - s.start_m) / total) * 100}%`, background: HZ_COLORS[s.hazard] || "#78788c", opacity: s.quality === "measured" ? 1 : 0.45 }} title={`${fmtDist(s.start_m)}–${fmtDist(s.end_m)} · ${s.hazard} · ${s.quality}`} />)
          : <div style={{ width: "100%", background: "#3ecf8e" }} />}
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 text-[10.5px] text-dim">
        <span>nominal <b className="num text-ok">{pct(c.hazard_exposure.nominal, 1)}</b></span>
        <span>caution <b className="num text-warn">{pct(c.hazard_exposure.caution, 1)}</b></span>
        <span>high <b className="num text-[#e67e22]">{pct(c.hazard_exposure.high, 1)}</b></span>
        <span>interpolated DEM (unknown terrain) <b className="num text-text">{pct(c.interpolated_fraction, 1)}</b></span>
      </div>
      <div className="mt-3 grid grid-cols-4 gap-3">
        <Stat label="Ascent" value={`${c.ascent_m} m`} />
        <Stat label="Descent" value={`${c.descent_m} m`} />
        <Stat label="Mean slope" value={`${c.mean_slope_deg}°`} />
        <Stat label="Steepest cell" value={`${c.max_cell_slope_deg}°`} sub={`limit ${c.slope_limit_deg}°`} />
        <Stat label="Traction" value={fmtEnergy(c.energy.traction_wh)} sub="derived" />
        <Stat label="Hotel load" value={fmtEnergy(c.energy.hotel_wh)} sub="derived" />
        <Stat label="Roughness" value={`${c.mean_roughness_m} m`} sub="RMS at DEM scale" />
        <Stat label="vs straight" value={`+${pct(c.distance_m / c.straight_line_m - 1, 0)}`} />
      </div>
      <div className="mt-2 text-[11px] text-dim">{c.description}</div>
      <div className="mt-2 rounded-md border border-line bg-ink p-2 text-[11px]">
        <div className="label mb-1">Data confidence · {c.confidence.level}</div>
        <ul className="list-disc pl-4 text-dim">{c.confidence.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
        <div className="mt-1 text-faint">Source: {plan.dem.mission} / {plan.dem.instrument}. {plan.dem.limitations}</div>
      </div>
    </Section>
  );
}

function Compare({ plan }: { plan: Plan }) {
  const rows = plan.comparison?.rows || [];
  const cols: [string, string, (v: number) => string][] = [
    ["distance_m", "Distance", (v) => fmtDist(v)], ["duration_h", "Time", (v) => fmtHours(v)], ["energy_wh", "Energy", (v) => fmtEnergy(v)],
    ["mean_slope_deg", "Mean slope", (v) => `${v}°`], ["max_cell_slope_deg", "Max slope", (v) => `${v}°`],
    ["hazard_exposure_pct", "Hazard", (v) => `${v}%`], ["interpolated_pct", "Unknown", (v) => `${v}%`], ["difficulty", "Difficulty", (v) => `${v}`],
  ];
  const best = (k: string) => Math.min(...rows.map((r) => r[k] as number));
  return (
    <Section title="Route comparison">
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead><tr className="text-faint"><th className="py-1 pr-2 text-left font-medium">Metric</th>{rows.map((r) => <th key={String(r.profile)} className="px-1 py-1 text-right font-medium capitalize" style={{ color: PROFILE_COLORS[String(r.profile)] }}>{String(r.profile)}</th>)}</tr></thead>
          <tbody>
            {cols.map(([k, name, f]) => (
              <tr key={k} className="border-t border-line">
                <td className="py-1 pr-2 text-dim">{name}</td>
                {rows.map((r) => <td key={String(r.profile)} className={`num px-1 py-1 text-right ${r[k] === best(k) ? "font-semibold text-white" : "text-dim"}`}>{f(r[k] as number)}</td>)}
              </tr>
            ))}
            <tr className="border-t border-line"><td className="py-1 pr-2 text-dim">Return</td>{rows.map((r) => <td key={String(r.profile)} className={`px-1 py-1 text-right ${r.return_feasible ? "text-ok" : "text-danger"}`}>{r.return_feasible ? "feasible" : "no"}</td>)}</tr>
            <tr className="border-t border-line"><td className="py-1 pr-2 text-dim">Confidence</td>{rows.map((r) => <td key={String(r.profile)} className="px-1 py-1 text-right text-dim">{String(r.confidence)}</td>)}</tr>
          </tbody>
        </table>
      </div>
      <div className="mt-1 text-[10.5px] text-faint">Bold = best value in the row. Time and energy are derived estimates; “Unknown” is the share of the route over interpolated DEM cells.</div>
    </Section>
  );
}
