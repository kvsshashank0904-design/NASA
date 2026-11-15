"use client";
import { useEffect, useState } from "react";
import { apiGet, type Fetched } from "@/lib/api";
import { fmtWhen } from "@/lib/format";

export function Page({ title, kicker, children, actions }: { title: string; kicker?: string; children: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="flex min-h-full flex-col">
      <div className="sticky top-0 z-10 flex items-center justify-between gap-2 border-b border-line bg-ink/95 px-4 py-3 backdrop-blur">
        <div className="min-w-0">
          {kicker && <div className="label">{kicker}</div>}
          <h1 className="truncate text-[15px] font-semibold text-white">{title}</h1>
        </div>
        {actions}
      </div>
      <div className="flex flex-col gap-3 p-4">{children}</div>
    </div>
  );
}

export function Section({ title, right, children, className = "" }: { title?: string; right?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={`card p-3 ${className}`}>
      {(title || right) && (
        <div className="mb-2 flex items-center justify-between gap-2">
          {title && <h2 className="label">{title}</h2>}
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, sub, tone }: { label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: "ok" | "warn" | "danger" | "blue" }) {
  const col = tone === "ok" ? "text-ok" : tone === "warn" ? "text-warn" : tone === "danger" ? "text-danger" : tone === "blue" ? "text-blue" : "text-white";
  return (
    <div className="min-w-0">
      <div className="label">{label}</div>
      <div className={`num truncate text-[15px] font-semibold ${col}`}>{value}</div>
      {sub && <div className="truncate text-[10.5px] text-faint">{sub}</div>}
    </div>
  );
}

export function Switch({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return <button role="switch" aria-checked={checked} aria-label={label} className="switch" onClick={() => onChange(!checked)} />;
}

const KIND: Record<string, [string, string]> = {
  latest_observation: ["Latest observation", "badge-blue"],
  historical_observation: ["Historical observation", ""],
  derived_estimate: ["Derived estimate", "badge-warn"],
  "derived estimate": ["Derived estimate", "badge-warn"],
  simulated: ["Simulated", "badge-sim"],
  inferred: ["Inferred", "badge-warn"],
};
export function KindBadge({ kind }: { kind: string }) {
  const k = KIND[kind] || KIND[Object.keys(KIND).find((x) => kind?.startsWith(x)) || ""] || [kind, ""];
  return <span className={`badge ${k[1]}`}>{k[0]}</span>;
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warn" | "danger"; children: React.ReactNode }) {
  const c = tone === "warn" ? "border-[#7a6016] bg-[#221b07] text-[#f3d776]" : tone === "danger" ? "border-[#7d2b29] bg-[#260d0c] text-[#ffb3b0]" : "border-line bg-panel text-dim";
  return <div className={`rounded-md border px-3 py-2 text-[12px] leading-snug ${c}`}>{children}</div>;
}

export function CachedNote({ f }: { f: { cached: boolean; cachedAt?: string } | null }) {
  if (!f?.cached) return null;
  return <span className="badge badge-warn" title="The backend was unreachable; this is the last copy saved on this device.">Cached · {fmtWhen(f.cachedAt)}</span>;
}

export function Spinner({ text = "Loading" }: { text?: string }) {
  return <div className="flex items-center gap-2 py-2 text-dim"><span className="h-1.5 w-1.5 rounded-full bg-blue pulse" />{text}…</div>;
}

/** GET with loading / error / cached-copy state. `path` null disables the request. */
export function useApi<T>(path: string | null, deps: unknown[] = []) {
  const [state, setState] = useState<{ res: Fetched<T> | null; error: string | null; loading: boolean }>({ res: null, error: null, loading: !!path });
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    if (!path) { setState({ res: null, error: null, loading: false }); return; }
    let alive = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    apiGet<T>(path).then((res) => alive && setState({ res, error: null, loading: false }))
      .catch((e) => alive && setState({ res: null, error: e.message, loading: false }));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, nonce, ...deps]);
  return { data: state.res?.data ?? null, res: state.res, error: state.error, loading: state.loading, reload: () => setNonce((n) => n + 1) };
}

export function Bar({ value, color = "#3b9eff", height = 5 }: { value: number; color?: string; height?: number }) {
  return (
    <div className="w-full overflow-hidden rounded-full bg-[#16203a]" style={{ height }}>
      <div style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%`, background: color, height: "100%" }} />
    </div>
  );
}
