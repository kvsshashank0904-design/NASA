"use client";
import Link from "next/link";
import { fmtDist, fmtEnergy, fmtHours, fmtPt, fmtWhen } from "@/lib/format";
import { useStore } from "@/lib/store";
import { CachedNote, KindBadge, Notice, Page, Section, Spinner, Stat, useApi } from "@/components/ui";

type Sol = { sol: number; terrestrial_date: string; min_air_temp_c: number | null; max_air_temp_c: number | null; pressure_pa: number | null; atmo_opacity?: string | null; uv_index?: string | null; ls?: number | null; age_days?: number | null; kind?: string };
type Station = {
  station: string; location: string; provenance: string; retrieved: string; error?: string;
  latest: Sol; unavailable: string[];
  solar_context: { top_of_atmosphere_w_m2: number; note: string } | null;
  risk: { value: number | null; factors: { factor: string; input: string; score: number }[]; note: string };
};
type Env = { stations: Record<string, Station>; radiation: { surface_gcr_dose_equivalent_mSv_per_day: { value: number; uncertainty: number }; period: string; limitations: string } };
type Health = { database: { dialect: string; locations: number }; ai: { mode: string; model: string }; cache: { mola_bands_cached: number; mola_cache_mb: number; ctx_dtm_cached: boolean } };
type Missions = { total: number; missions: { id: number; name: string; status: string; objectives: string[]; route_count: number; created_at: string }[] };
type Rovers = { retrieved: string; rovers: Record<string, { name: string; latest_sol: number; latest: { lon: number; lat: number; elev_m: number; dist_total_m: number } }> };
type Images = { source: string; images: { sol: number; camera: string; title: string; image: string; link: string; date: string }[] };

export default function Dashboard() {
  const plan = useStore((s) => s.plan);
  const profile = useStore((s) => s.selectedProfile);
  const habitat = useStore((s) => s.habitat);
  const sim = useStore((s) => s.sim);
  const missionTargets = useStore((s) => s.missionTargets);
  const backend = useStore((s) => s.backend);
  const env = useApi<Env>("/api/v1/environment/summary", [backend]);
  const health = useApi<Health>("/api/v1/health", [backend]);
  const missions = useApi<Missions>("/api/v1/missions?limit=6", [backend]);
  const rovers = useApi<Rovers>("/api/v1/planet/rovers", [backend]);
  const images = useApi<Images>("/api/v1/planet/rover-images?rover=perseverance&limit=6", [backend]);
  const cand = plan?.candidates.find((c) => c.profile === profile) || plan?.candidates[0];

  return (
    <Page title="Mission Dashboard" kicker="Overview">
      <Section title="Current exploration status">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Habitat" value={habitat ? "set" : "not set"} sub={habitat ? fmtPt(habitat, 3) : "set it in Explorer"} tone={habitat ? "ok" : undefined} />
          <Stat label="Active plan" value={plan ? plan.plan_id : "none"} sub={plan ? `${plan.candidates.length} candidates` : "use Planner or MARS AI"} tone={plan ? "blue" : undefined} />
          <Stat label="Mission targets" value={missionTargets.length} sub="added from Science" />
          <Stat label="Simulation" value={sim ? sim.outcome.replace(/_/g, " ") : "not run"} sub={sim ? sim.scenario : undefined} />
        </div>
        {cand && plan && (
          <div className="mt-3 rounded-md border border-line bg-ink p-2.5">
            <div className="mb-1.5 flex items-center justify-between">
              <span className="text-[12px] font-semibold text-white">Selected route · {cand.profile}</span>
              <Link href="/planner" className="btn btn-sm">Open planner</Link>
            </div>
            <div className="grid grid-cols-4 gap-3">
              <Stat label="Distance" value={fmtDist(cand.distance_m)} />
              <Stat label="Duration" value={fmtHours(cand.duration_h.value)} sub="derived" />
              <Stat label="Energy" value={fmtEnergy(cand.energy.total_wh)} sub="derived" />
              <Stat label="Return" value={cand.return_feasibility?.feasible ? "feasible" : "not shown"} tone={cand.return_feasibility?.feasible ? "ok" : "danger"} />
            </div>
            <div className="mt-1.5 text-[11px] text-dim">{plan.dem.name} · {plan.dem.effective_resolution_m} m cells · confidence {cand.confidence.level}</div>
          </div>
        )}
        {!plan && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            <Link href="/explorer" className="btn btn-sm">1 · Explore and set a habitat</Link>
            <Link href="/science" className="btn btn-sm">2 · Find science targets</Link>
            <Link href="/planner" className="btn btn-sm">3 · Plan a route</Link>
            <Link href="/ai" className="btn btn-mars btn-sm">or ask MARS AI</Link>
          </div>
        )}
      </Section>

      <Section title="Environmental summary" right={<CachedNote f={env.res} />}>
        {env.loading && <Spinner />}
        {env.error && <Notice tone="danger">{env.error}</Notice>}
        {env.data && (
          <div className="flex flex-col gap-2.5">
            <div className="grid gap-2.5 sm:grid-cols-2">
              {Object.entries(env.data.stations).map(([k, s]) => s.error ? <Notice key={k} tone="warn">{s.station}: {s.error}</Notice> : (
                <div key={k} className="rounded-md border border-line bg-ink p-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[12px] font-semibold text-white">{s.station}</span>
                    <KindBadge kind="latest_observation" />
                  </div>
                  <div className="text-[10.5px] text-faint">{s.location}</div>
                  <div className="mt-2 grid grid-cols-3 gap-2">
                    <Stat label="Air min" value={s.latest.min_air_temp_c != null ? `${s.latest.min_air_temp_c}°C` : "n/a"} />
                    <Stat label="Air max" value={s.latest.max_air_temp_c != null ? `${s.latest.max_air_temp_c}°C` : "n/a"} />
                    <Stat label="Pressure" value={s.latest.pressure_pa != null ? `${s.latest.pressure_pa} Pa` : "n/a"} />
                  </div>
                  <div className="mt-1.5 text-[11px] text-dim">
                    Sol {s.latest.sol} · {s.latest.terrestrial_date} · <span className={(s.latest.age_days ?? 0) > 30 ? "text-warn" : ""}>{s.latest.age_days} days old</span>
                    {s.latest.atmo_opacity ? ` · opacity ${s.latest.atmo_opacity}` : ""}{s.latest.uv_index ? ` · UV ${s.latest.uv_index.replace("_", " ")}` : ""}
                  </div>
                  <div className="mt-1 text-[10.5px] text-faint">Not live weather. {s.provenance}. Unavailable: {s.unavailable[0]}.</div>
                  {s.risk.value != null && (
                    <div className="mt-2 flex items-center gap-2 border-t border-line pt-2">
                      <KindBadge kind="derived_estimate" />
                      <span className="text-[11px] text-dim">EVA environmental risk index</span>
                      <span className={`num ml-auto text-[13px] font-semibold ${s.risk.value > 60 ? "text-danger" : s.risk.value > 40 ? "text-warn" : "text-ok"}`}>{s.risk.value}/100</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
            <div className="rounded-md border border-line bg-ink p-2.5">
              <div className="flex items-center justify-between"><span className="text-[12px] font-semibold text-white">Surface radiation · MSL RAD</span><KindBadge kind="historical_observation" /></div>
              <div className="mt-1 flex items-baseline gap-2">
                <span className="num text-[18px] font-semibold text-white">{env.data.radiation.surface_gcr_dose_equivalent_mSv_per_day.value} ± {env.data.radiation.surface_gcr_dose_equivalent_mSv_per_day.uncertainty}</span>
                <span className="text-dim">mSv/day GCR dose equivalent</span>
              </div>
              <div className="text-[10.5px] text-faint">{env.data.radiation.period}. {env.data.radiation.limitations}</div>
            </div>
          </div>
        )}
      </Section>

      <Section title="Recent rover observations" right={<CachedNote f={rovers.res} />}>
        {rovers.data && (
          <div className="mb-2 grid gap-2 sm:grid-cols-2">
            {Object.entries(rovers.data.rovers).map(([k, r]) => (
              <button key={k} className="rounded-md border border-line bg-ink p-2.5 text-left hover:border-line-strong" onClick={() => { useStore.getState().toggleLayer("mx_rovers", true); useStore.getState().fly(r.latest.lon, r.latest.lat, 25000); }}>
                <div className="text-[12px] font-semibold text-white">{r.name}</div>
                <div className="num text-[11px] text-dim">sol {r.latest_sol} · {fmtPt(r.latest, 4)}</div>
                <div className="text-[10.5px] text-faint">{fmtDist(r.latest.dist_total_m)} driven · elevation {r.latest.elev_m} m · snapshot {fmtWhen(rovers.data!.retrieved)}</div>
              </button>
            ))}
          </div>
        )}
        {images.loading && <Spinner text="Fetching latest Perseverance raw images from NASA" />}
        {images.error && <Notice tone="warn">Latest raw images are unavailable: {images.error} (live NASA feed; not cached for offline use).</Notice>}
        {images.data && (
          <>
            <div className="grid grid-cols-3 gap-1.5">
              {images.data.images.filter((i) => i.image).slice(0, 6).map((i, n) => (
                <a key={n} href={i.link} target="_blank" rel="noreferrer" className="group relative block aspect-[4/3] overflow-hidden rounded border border-line bg-ink" title={i.title}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={i.image} alt={i.title || "Rover raw image"} loading="lazy" className="h-full w-full object-cover opacity-90 transition group-hover:opacity-100" />
                  <span className="absolute inset-x-0 bottom-0 bg-black/70 px-1 py-0.5 text-[9.5px] text-dim">sol {i.sol} · {i.camera}</span>
                </a>
              ))}
            </div>
            <div className="mt-1 text-[10.5px] text-faint">{images.data.source}</div>
          </>
        )}
      </Section>

      <Section title="Saved missions" right={<CachedNote f={missions.res} />}>
        {missions.loading && <Spinner />}
        {missions.error && <Notice tone="warn">{missions.error}</Notice>}
        {missions.data && missions.data.missions.length === 0 && <p className="text-dim">No missions saved yet. Plan a route and choose “Save as mission”.</p>}
        {missions.data?.missions.map((m) => (
          <div key={m.id} className="flex items-center justify-between gap-2 border-b border-line py-1.5 last:border-0">
            <div className="min-w-0"><div className="truncate text-text">{m.name}</div><div className="text-[10.5px] text-faint">{fmtWhen(m.created_at)} · {m.route_count} routes · {m.objectives.length} objectives</div></div>
            <span className={`badge ${m.status === "active" ? "badge-ok" : m.status === "aborted" ? "badge-danger" : ""}`}>{m.status}</span>
          </div>
        ))}
      </Section>

      <Section title="System" right={<CachedNote f={health.res} />}>
        {health.error && <Notice tone="warn">Backend unreachable. Showing saved mission data and cached map tiles only.</Notice>}
        {health.data && (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="MARS AI" value={health.data.ai.mode === "llm" ? "Claude" : "Planner"} sub={health.data.ai.mode === "llm" ? health.data.ai.model : "deterministic, no API key"} />
            <Stat label="Database" value={health.data.database.dialect} sub={`${health.data.database.locations} locations`} />
            <Stat label="MOLA cache" value={`${health.data.cache.mola_cache_mb} MB`} sub={`${health.data.cache.mola_bands_cached} bands`} />
            <Stat label="CTX DTM" value={health.data.cache.ctx_dtm_cached ? "cached" : "not cached"} tone={health.data.cache.ctx_dtm_cached ? "ok" : "warn"} />
          </div>
        )}
      </Section>
    </Page>
  );
}
