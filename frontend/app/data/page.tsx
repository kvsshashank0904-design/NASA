"use client";
import { useEffect, useState } from "react";
import { fmtWhen } from "@/lib/format";
import { useStore } from "@/lib/store";
import { CachedNote, Notice, Page, Section, Spinner, useApi } from "@/components/ui";

type Dataset = { id: string; name: string; mission: string | null; instrument: string | null; category: string; source: string; source_url: string;
  observation_time: string; coverage: string; resolution: string; data_format: string; processing: string; limitations: string; integration: string; retrieved_at: string };
type Datasets = { count: number; datasets: Dataset[]; missions: string[] };
type Trek = { retrieved: string; total: number; offset: number; limit: number; products: { productLabel: string; title: string; mission: string | null; instrument: string | null; productCat1: string | null; bbox: string | null; data_created_date: string | null; integrated_as_layer: boolean }[] };
type Refs = { references: { id: string; citation: string; url: string | null }[] };

const INTEGRATION: Record<string, [string, string, string]> = {
  live: ["Live", "badge-ok", "Fetched from the NASA service at request time (with a local fallback copy)"],
  "lazy-cache": ["On-demand + cached", "badge-blue", "Only the needed part is downloaded on first use, then cached"],
  snapshot: ["Snapshot", "", "Catalogue-sized copy taken by scripts/ingest_nasa.py"],
  reference: ["Published constants", "badge-warn", "Values quoted from the peer-reviewed paper; the raw archive is not processed"],
};
const PAGE = 12;

export default function DataPage() {
  const backend = useStore((s) => s.backend);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [tq, setTq] = useState("");
  const [tqd, setTqd] = useState("");
  const [page, setPage] = useState(0);
  const ds = useApi<Datasets>("/api/v1/datasets", [backend]);
  const trek = useApi<Trek>(`/api/v1/datasets/trek-catalog?limit=${PAGE}&offset=${page * PAGE}${tqd ? `&q=${encodeURIComponent(tqd)}` : ""}`);
  const refs = useApi<Refs>("/api/v1/science/references");
  useEffect(() => { const t = setTimeout(() => { setTqd(tq.trim()); setPage(0); }, 250); return () => clearTimeout(t); }, [tq]);

  const list = (ds.data?.datasets || []).filter((d) => !q || `${d.name} ${d.mission} ${d.instrument} ${d.category} ${d.id}`.toLowerCase().includes(q.toLowerCase()));

  return (
    <Page title="Data Explorer" kicker="NASA datasets · provenance · limitations">
      <Section title="Integrated datasets" right={<CachedNote f={ds.res} />}>
        <input className="input" placeholder="Filter by mission, instrument or keyword (MOLA, CRISM, REMS…)" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Filter datasets" />
        {ds.data && <div className="mt-2 flex flex-wrap gap-1">{ds.data.missions.map((m) => <button key={m} className={`badge hover:text-text ${q === m ? "badge-blue" : ""}`} onClick={() => setQ(q === m ? "" : m)}>{m}</button>)}</div>}
      </Section>
      {ds.loading && <Spinner />}
      {ds.error && <Notice tone="danger">{ds.error}</Notice>}
      {ds.data && list.length === 0 && <Notice tone="warn">No integrated dataset matches “{q}”.</Notice>}
      {list.map((d) => {
        const ig = INTEGRATION[d.integration] || [d.integration, "", ""];
        const isOpen = open === d.id;
        return (
          <section key={d.id} className="card p-3">
            <button className="flex w-full items-start justify-between gap-3 text-left" onClick={() => setOpen(isOpen ? null : d.id)} aria-expanded={isOpen}>
              <span className="min-w-0">
                <span className="block text-[13px] font-semibold text-white">{d.name}</span>
                <span className="block text-[11px] text-dim">{[d.mission, d.instrument].filter(Boolean).join(" · ") || "Reference database"}</span>
              </span>
              <span className="flex shrink-0 flex-col items-end gap-1"><span className={`badge ${ig[1]}`} title={ig[2]}>{ig[0]}</span><span className="badge">{d.category}</span></span>
            </button>
            <dl className="mt-2 grid grid-cols-[92px_1fr] gap-x-3 gap-y-1 text-[11.5px]">
              <dt className="text-faint">Observed</dt><dd>{d.observation_time}</dd>
              <dt className="text-faint">Coverage</dt><dd>{d.coverage}</dd>
              <dt className="text-faint">Resolution</dt><dd>{d.resolution}</dd>
              {isOpen && (
                <>
                  <dt className="text-faint">Source</dt><dd>{d.source} · <a href={d.source_url} target="_blank" rel="noreferrer" className="break-all text-blue hover:underline">{d.source_url}</a></dd>
                  <dt className="text-faint">Format</dt><dd>{d.data_format}</dd>
                  <dt className="text-faint">Processing</dt><dd className="text-dim">{d.processing}</dd>
                  <dt className="text-faint">Access</dt><dd className="text-dim">{ig[2]}. Catalogue retrieved {fmtWhen(d.retrieved_at)}.</dd>
                </>
              )}
              <dt className="text-faint">Limitations</dt><dd className="text-[#f3d9a8]">{d.limitations}</dd>
            </dl>
            {!isOpen && <button className="mt-1.5 text-[11px] text-blue hover:underline" onClick={() => setOpen(d.id)}>Source, format and processing history</button>}
          </section>
        );
      })}

      <Section title="NASA Mars Trek product catalogue" right={<CachedNote f={trek.res} />}>
        <div className="mb-2 text-[11px] text-dim">Metadata for every product in the Mars Trek index{trek.data ? ` (snapshot ${fmtWhen(trek.data.retrieved)})` : ""}. MARS-X renders the ones marked “layer”; the rest are listed for reference only.</div>
        <input className="input" placeholder="Search the catalogue (HiRISE, CTX, CRISM, Gale…)" value={tq} onChange={(e) => setTq(e.target.value)} aria-label="Search Trek catalogue" />
        {trek.loading && <Spinner />}
        {trek.error && <div className="mt-2"><Notice tone="danger">{trek.error}</Notice></div>}
        {trek.data && (
          <>
            <div className="mt-2 overflow-x-auto">
              <table className="w-full text-[11px]">
                <thead><tr className="text-left text-faint"><th className="py-1 pr-2 font-medium">Product</th><th className="px-1 py-1 font-medium">Mission · instrument</th><th className="px-1 py-1 font-medium">Type</th><th className="py-1 pl-1 font-medium" /></tr></thead>
                <tbody>
                  {trek.data.products.map((p) => (
                    <tr key={p.productLabel} className="border-t border-line align-top">
                      <td className="py-1 pr-2 text-text">{p.title}</td>
                      <td className="px-1 py-1 text-dim">{[p.mission, p.instrument].filter(Boolean).join(" · ") || "—"}</td>
                      <td className="px-1 py-1 text-dim">{p.productCat1 || "—"}</td>
                      <td className="py-1 pl-1 text-right">{p.integrated_as_layer ? <span className="badge badge-ok">layer</span> : <span className="text-faint">listed</span>}</td>
                    </tr>
                  ))}
                  {trek.data.products.length === 0 && <tr><td colSpan={4} className="py-2 text-dim">No products match.</td></tr>}
                </tbody>
              </table>
            </div>
            <div className="mt-2 flex items-center justify-between text-[11px] text-dim">
              <span className="num">{trek.data.total === 0 ? 0 : page * PAGE + 1}–{Math.min(trek.data.total, (page + 1) * PAGE)} of {trek.data.total}</span>
              <span className="flex gap-1.5">
                <button className="btn btn-sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>Previous</button>
                <button className="btn btn-sm" disabled={(page + 1) * PAGE >= trek.data.total} onClick={() => setPage((p) => p + 1)}>Next</button>
              </span>
            </div>
          </>
        )}
      </Section>

      <Section title="Scientific references" right={<CachedNote f={refs.res} />}>
        {refs.error && <Notice tone="warn">{refs.error}</Notice>}
        <ul className="flex flex-col gap-1.5 text-[11px] text-dim">
          {refs.data?.references.map((r) => <li key={r.id}>{r.citation} {r.url && <a href={r.url} target="_blank" rel="noreferrer" className="text-blue hover:underline">link</a>}</li>)}
        </ul>
      </Section>
    </Page>
  );
}
