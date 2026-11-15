"use client";
/** API client. Successful GETs are mirrored into Cache Storage so the same call answers
 *  from the local copy (with its timestamp) when the backend or network is unreachable. */

export const API_BASE = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
const CACHE = "marsx-api-v1";
const STAMPS = "marsx:api-stamps";

export type Fetched<T> = { data: T; cached: boolean; cachedAt?: string };

export class ApiError extends Error {
  status: number; detail: unknown;
  constructor(status: number, message: string, detail?: unknown) { super(message); this.status = status; this.detail = detail; }
}

function stamps(): Record<string, string> {
  try { return JSON.parse(localStorage.getItem(STAMPS) || "{}"); } catch { return {}; }
}
function setStamp(url: string) {
  try { const s = stamps(); s[url] = new Date().toISOString(); localStorage.setItem(STAMPS, JSON.stringify(s)); } catch { /* quota */ }
}

async function errorFrom(r: Response): Promise<ApiError> {
  let detail: unknown = null;
  try { detail = (await r.json()).detail; } catch { /* not json */ }
  let msg = `Request failed (${r.status})`;
  if (typeof detail === "string") msg = detail;
  else if (Array.isArray(detail)) msg = detail.map((d: { loc?: string[]; msg?: string }) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ");
  else if (detail && typeof detail === "object") msg = (detail as { message?: string; error?: string }).message || (detail as { error?: string }).error || msg;
  return new ApiError(r.status, msg, detail);
}

export async function apiGet<T>(path: string, opts: { cache?: boolean } = {}): Promise<Fetched<T>> {
  const url = API_BASE + path;
  const useCache = opts.cache !== false && typeof caches !== "undefined";
  try {
    const r = await fetch(url, { headers: { Accept: "application/json" } });
    if (!r.ok) throw await errorFrom(r);
    if (useCache) {
      try { (await caches.open(CACHE)).put(url, r.clone()); setStamp(url); } catch { /* storage unavailable */ }
    }
    return { data: (await r.json()) as T, cached: false };
  } catch (e) {
    if (e instanceof ApiError && e.status < 500) throw e;       // a real answer from the server, not an outage
    if (useCache) {
      const hit = await (await caches.open(CACHE)).match(url);
      if (hit) return { data: (await hit.json()) as T, cached: true, cachedAt: stamps()[url] };
    }
    if (e instanceof ApiError) throw e;
    throw new ApiError(0, "MARS-X backend is unreachable and no cached copy exists for this request.");
  }
}

export async function apiSend<T>(method: "POST" | "PATCH" | "DELETE", path: string, body?: unknown): Promise<T> {
  let r: Response;
  try {
    r = await fetch(API_BASE + path, { method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "MARS-X backend is unreachable. This action needs the backend (it runs real computations).");
  }
  if (!r.ok) throw await errorFrom(r);
  return r.status === 204 ? (undefined as T) : ((await r.json()) as T);
}

export async function cachedApiEntries(): Promise<{ url: string; at?: string }[]> {
  if (typeof caches === "undefined") return [];
  const keys = await (await caches.open(CACHE)).keys();
  const s = stamps();
  return keys.map((k) => ({ url: k.url.replace(API_BASE, ""), at: s[k.url] }));
}
