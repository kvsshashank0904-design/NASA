"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { apiSend } from "@/lib/api";
import { fmtClock, fmtDist, fmtEnergy, fmtHours } from "@/lib/format";
import { useStore } from "@/lib/store";
import type { Sim } from "@/lib/types";
import { Bar, Notice, Page, Section, Stat, useApi } from "@/components/ui";

type Scen = { scenarios: { id: string; description: string }[]; defaults: { battery_wh: number; reserve_fraction: number } };
const NAMES: Record<string, string> = { nominal: "Normal exploration", terrain_hazard: "Unexpected terrain hazard", energy_overrun: "Increased energy use", dust_storm: "Dust storm", comm_degradation: "Communication degradation", emergency_return: "Emergency return" };
const PHASE: Record<string, [string, string]> = { outbound: ["Outbound", "badge-blue"], at_target: ["At target", "badge-ok"], return: ["Returning", "badge-mars"], emergency_return: ["Emergency return", "badge-danger"] };
const OUTCOME: Record<string, [string, string]> = {
  completed: ["Completed", "ok"], aborted_emergency: ["Aborted · emergency", "warn"], aborted_energy: ["Aborted · energy rule", "warn"],
  aborted_no_detour: ["Aborted · no detour", "warn"], failed_energy: ["Failed · energy exhausted", "danger"],
};

export default function SimulationPage() {
  const plan = useStore((s) => s.plan);
  const profile = useStore((s) => s.selectedProfile);
  const sim = useStore((s) => s.sim);
  const simIndex = useStore((s) => s.simIndex);
  const missionTargets = useStore((s) => s.missionTargets);
  const missionId = useStore((s) => s.missionId);
  const set = useStore((s) => s.set);
  const scen = useApi<Scen>("/api/v1/simulation/scenarios");
  const [scenario, setScenario] = useState("nominal");
  const [battery, setBattery] = useState(40);
  const [dwell, setDwell] = useState(30);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const cand = plan?.candidates.find((c) => c.profile === profile) || plan?.candidates[0];
  const objectives = missionTargets.map((t) => `Investigate ${t.name}`);

  const run = async () => {
    if (!plan || !cand) return;
    setBusy(true); setError(null); setPlaying(false);
    const body = { scenario, battery_wh: battery * 1000, dwell_min: dwell, safety_margin: plan.constraints.safety_margin ?? 0.2, objectives, mission_id: missionId ?? undefined };
    try {
      let s: Sim;
      try {
        s = await apiSend<Sim>("POST", "/api/v1/simulation", { ...body, plan_id: plan.plan_id, profile: cand.profile });
      } catch (e) {
        // the server keeps plans in memory; after a restart fall back to the geometry saved on this device
        if ((e as { status?: number }).status !== 404) throw e;
        s = await apiSend<Sim>("POST", "/api/v1/simulation", { ...body, route: cand.geometry.coordinates, return_route: plan.return_route?.geometry.coordinates });
      }
      set({ sim: s, simIndex: 0 });
      setPlaying(true);
    } catch (e) { setError((e as Error).message); }
    setBusy(false);
  };

  useEffect(() => {
    if (timer.current) clearInterval(timer.current);
    if (!playing || !sim) return;
    timer.current = setInterval(() => {
      const st = useStore.getState();
      const next = st.simIndex + Math.max(1, Math.round((sim.frames.length / 240) * speed));
      if (next >= sim.frames.length - 1) { st.set({ simIndex: sim.frames.length - 1 }); setPlaying(false); }
      else st.set({ simIndex: next });
    }, 80);
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [playing, sim, speed]);

  const f = sim ? sim.frames[Math.min(simIndex, sim.frames.length - 1)] : null;
  const total = sim ? sim.frames[sim.frames.length - 1].t_s : 0;
  const pastEvents = sim && f ? sim.events.filter((e) => e.t_s <= f.t_s) : [];
  const upcoming = sim && f ? sim.frames.slice(simIndex + 1).find((x) => x.phase !== f.phase) : null;
  const chart = sim ? sim.frames.map((x) => ({ t: x.t_s / 3600, e: x.energy_pct })) : [];

  return (
    <Page title="Mission Simulation" kicker="Digital twin · what-if scenarios">
      <div className="badge badge-sim !h-7 w-full justify-center !text-[11px]">SIMULATION MODE — model output on real terrain; nothing here is a measurement</div>

      {!plan || !cand ? (
        <Notice tone="warn">There is no route plan to simulate. <Link href="/planner" className="text-blue underline">Plan a route</Link> or ask <Link href="/ai" className="text-blue underline">MARS AI</Link> to plan a mission first.</Notice>
      ) : (
        <Section title="Scenario">
          <div className="mb-2 text-[11px] text-dim">Route: <b className="capitalize text-white">{cand.profile}</b> · {fmtDist(cand.distance_m)} outbound{plan.return_route ? ` · ${fmtDist(plan.return_route.distance_m)} planned return` : " · no planned return"} · plan <span className="num">{plan.plan_id}</span></div>
          <div className="grid grid-cols-2 gap-1.5">
            {(scen.data?.scenarios || Object.keys(NAMES).map((id) => ({ id, description: "" }))).map((s) => (
              <button key={s.id} className={`rounded-md border px-2.5 py-1.5 text-left text-[12px] ${scenario === s.id ? "border-mars bg-[#2a120b] text-white" : "border-line bg-ink text-text hover:border-line-strong"}`} onClick={() => setScenario(s.id)} aria-pressed={scenario === s.id}>
                {NAMES[s.id] || s.id}
              </button>
            ))}
          </div>
          <p className="mt-2 text-[11px] text-dim">{scen.data?.scenarios.find((s) => s.id === scenario)?.description}</p>
          <div className="mt-2 grid grid-cols-2 gap-x-4">
            <label className="text-[11px]"><span className="flex justify-between text-dim"><span>Battery capacity</span><span className="num text-text">{battery} kWh</span></span>
              <input type="range" min={2} max={120} step={1} value={battery} onChange={(e) => setBattery(+e.target.value)} className="w-full" /></label>
            <label className="text-[11px]"><span className="flex justify-between text-dim"><span>Time at target</span><span className="num text-text">{dwell} min</span></span>
              <input type="range" min={0} max={240} step={10} value={dwell} onChange={(e) => setDwell(+e.target.value)} className="w-full" /></label>
          </div>
          <button className="btn btn-mars mt-3 w-full" disabled={busy} onClick={run}>{busy ? "Simulating…" : sim ? "Run again" : "Run simulation"}</button>
          {error && <div className="mt-2"><Notice tone="danger">{error}</Notice></div>}
        </Section>
      )}

      {sim && f && (
        <>
          <Section title="Playback" right={<span className={`badge ${OUTCOME[sim.outcome]?.[1] === "ok" ? "badge-ok" : OUTCOME[sim.outcome]?.[1] === "danger" ? "badge-danger" : "badge-warn"}`}>{OUTCOME[sim.outcome]?.[0] || sim.outcome}</span>}>
            <div className="flex items-center gap-2">
              <button className="btn btn-primary btn-sm w-16" onClick={() => { if (simIndex >= sim.frames.length - 1) set({ simIndex: 0 }); setPlaying((p) => !p); }}>{playing ? "Pause" : simIndex >= sim.frames.length - 1 ? "Replay" : "Play"}</button>
              <input type="range" min={0} max={sim.frames.length - 1} value={simIndex} onChange={(e) => { setPlaying(false); set({ simIndex: +e.target.value }); }} className="flex-1" aria-label="Mission timeline" />
              {[1, 3, 8].map((s) => <button key={s} className={`btn btn-sm ${speed === s ? "btn-on" : "btn-ghost"}`} onClick={() => setSpeed(s)}>{s}×</button>)}
            </div>
            <div className="mt-3 grid grid-cols-4 gap-3">
              <Stat label="Elapsed" value={fmtClock(f.t_s)} sub={`of ${fmtClock(total)}`} />
              <Stat label="Phase" value={<span className={`badge ${PHASE[f.phase]?.[1] || ""}`}>{PHASE[f.phase]?.[0] || f.phase}</span>} />
              <Stat label="Distance" value={fmtDist(f.distance_m)} />
              <Stat label="Comm link" value={f.comm} tone={f.comm === "nominal" ? "ok" : f.comm === "lost" ? "danger" : "warn"} />
            </div>
            <div className="mt-3">
              <div className="mb-1 flex justify-between text-[11px]"><span className="text-dim">Estimated remaining energy</span><span className="num text-white">{fmtEnergy(f.energy_wh)} · {f.energy_pct}%</span></div>
              <Bar value={f.energy_pct / 100} height={8} color={f.energy_pct < 15 ? "#ef5350" : f.energy_pct < 35 ? "#f0c33a" : "#3ecf8e"} />
              <div className="mt-0.5 text-[10px] text-faint">Reserve line at {Math.round((sim.summary.reserve_wh / sim.summary.battery_wh) * 100)}% ({fmtEnergy(sim.summary.reserve_wh)})</div>
            </div>
            <div className="mt-2 grid grid-cols-3 gap-3 text-[11px]">
              <Stat label="Position" value={`${f.lat.toFixed(4)}°, ${f.lon.toFixed(4)}°`} sub={f.elev_m != null ? `${f.elev_m} m (real DEM)` : undefined} />
              <Stat label="Speed" value={`${f.speed_kmh} km/h`} />
              <Stat label="Next phase" value={upcoming ? (PHASE[upcoming.phase]?.[0] || upcoming.phase) : "end"} sub={upcoming ? `in ${fmtHours((upcoming.t_s - f.t_s) / 3600)}` : undefined} />
            </div>
            <button className="btn btn-ghost btn-sm mt-2" onClick={() => useStore.getState().fly(f.lon, f.lat, 5000)}>Follow crew on map</button>
          </Section>

          <Section title="Energy over mission time">
            <div className="h-[120px]">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chart} margin={{ top: 4, right: 6, left: -22, bottom: 0 }}>
                  <CartesianGrid stroke="#1d2940" strokeDasharray="2 4" vertical={false} />
                  <XAxis dataKey="t" type="number" domain={[0, "dataMax"]} tick={{ fill: "#5b6b86", fontSize: 10 }} stroke="#1d2940" tickFormatter={(v) => `${(+v).toFixed(1)}h`} />
                  <YAxis domain={[0, 100]} tick={{ fill: "#5b6b86", fontSize: 10 }} stroke="#1d2940" unit="%" />
                  <Tooltip contentStyle={{ background: "#0d1422", border: "1px solid #2a3a59", borderRadius: 6, fontSize: 11 }} labelFormatter={(v) => `t+${fmtHours(Number(v))}`} formatter={(v) => [`${v}%`, "Energy (simulated)"]} />
                  <ReferenceLine y={(sim.summary.reserve_wh / sim.summary.battery_wh) * 100} stroke="#ef5350" strokeDasharray="4 3" />
                  <ReferenceLine x={f.t_s / 3600} stroke="#ffffff" />
                  <Area type="monotone" dataKey="e" stroke="#e2603a" strokeWidth={1.6} fill="#e2603a" fillOpacity={0.14} isAnimationActive={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </Section>

          <Section title="Mission timeline" right={<span className="text-[10.5px] text-faint">{pastEvents.length}/{sim.events.length} events</span>}>
            <ol className="flex flex-col gap-1.5">
              {sim.events.map((e, i) => {
                const past = e.t_s <= f.t_s;
                const col = e.kind === "critical" ? "bg-danger" : e.kind === "warning" ? "bg-warn" : e.kind === "objective" ? "bg-ok" : "bg-blue";
                return (
                  <li key={i} className={`flex gap-2 text-[11.5px] transition-opacity ${past ? "" : "opacity-35"}`}>
                    <button className="num w-14 shrink-0 text-right text-faint hover:text-text" onClick={() => { setPlaying(false); set({ simIndex: Math.max(0, sim.frames.findIndex((x) => x.t_s >= e.t_s)) }); }} title="Jump to this moment">{fmtClock(e.t_s).slice(0, 5)}</button>
                    <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${col}`} />
                    <span className={e.kind === "critical" ? "text-[#ffb3b0]" : e.kind === "warning" ? "text-[#f3d776]" : "text-text"}>{e.message}</span>
                  </li>
                );
              })}
            </ol>
          </Section>

          <Section title="Objectives and result">
            {objectives.length === 0 ? <p className="text-[11px] text-dim">No mission objectives. Add targets in <Link href="/science" className="text-blue underline">Science Discovery</Link> to track them here.</p> : (
              <ul className="mb-2 flex flex-col gap-1 text-[12px]">
                {objectives.map((o) => { const done = sim.target_reached && pastEvents.some((e) => e.kind === "objective" && e.message.includes(o)); return <li key={o} className="flex items-center gap-2"><span className={`badge ${done ? "badge-ok" : ""}`}>{done ? "addressed" : sim.target_reached ? "pending" : "not reached"}</span>{o}</li>; })}
              </ul>
            )}
            <div className="grid grid-cols-4 gap-3">
              <Stat label="Total time" value={fmtHours(sim.summary.duration_h)} />
              <Stat label="Driven" value={fmtDist(sim.summary.distance_m)} />
              <Stat label="Energy used" value={fmtEnergy(sim.summary.energy_used_wh)} />
              <Stat label="Remaining" value={`${sim.summary.energy_remaining_pct}%`} tone={sim.summary.energy_remaining_pct < 15 ? "danger" : "ok"} />
            </div>
            <div className="mt-2 text-[10.5px] text-faint">
              Assumptions: {String(sim.assumptions.mass_kg)} kg rover, {String(sim.assumptions.speed_kmh)} km/h, rolling resistance {String(sim.assumptions.rolling_resistance)}, hotel load {String(sim.assumptions.hotel_power_w)} W. Terrain: {String(sim.assumptions.terrain)}. {String(sim.assumptions.disturbances)}.
              {missionId != null && ` Result logged to mission #${missionId}.`}
            </div>
          </Section>
        </>
      )}
    </Page>
  );
}
