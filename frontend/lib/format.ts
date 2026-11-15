export const fmtLat = (v: number, d = 4) => `${Math.abs(v).toFixed(d)}°${v >= 0 ? "N" : "S"}`;
export const fmtLon = (v: number, d = 4) => `${Math.abs(v).toFixed(d)}°${v >= 0 ? "E" : "W"}`;
export const fmtPt = (p: { lon: number; lat: number }, d = 4) => `${fmtLat(p.lat, d)} ${fmtLon(p.lon, d)}`;
export const fmtDist = (m: number | null | undefined) => (m == null ? "n/a" : m >= 10000 ? `${(m / 1000).toFixed(1)} km` : m >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${m.toFixed(0)} m`);
export const fmtEnergy = (wh: number | null | undefined) => (wh == null ? "n/a" : wh >= 1000 ? `${(wh / 1000).toFixed(2)} kWh` : `${wh.toFixed(0)} Wh`);
export const fmtHours = (h: number | null | undefined) => {
  if (h == null) return "n/a";
  const m = Math.round(h * 60);
  return m >= 60 ? `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min` : `${m} min`;
};
export const fmtClock = (s: number) => `${String(Math.floor(s / 3600)).padStart(2, "0")}:${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
export const pct = (f: number, d = 0) => `${(100 * f).toFixed(d)}%`;
export const fmtWhen = (iso?: string | null) => {
  if (!iso) return "unknown time";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
};

/** Mars sphere great-circle distance in metres (mirrors backend app/mars.py). */
export function haversine(a: { lon: number; lat: number }, b: { lon: number; lat: number }) {
  const R = 3396190, r = Math.PI / 180;
  const dp = (b.lat - a.lat) * r, dl = (b.lon - a.lon) * r;
  const h = Math.sin(dp / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** Minimal, safe markdown: bold, italics, code, bullet lists, blockquotes, paragraphs. Escapes HTML first. */
export function mdToHtml(src: string): string {
  const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const inline = (s: string) => esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s).,;:!?]|$)/g, "$1<em>$2</em>")
    .replace(/(^|[\s(])_([^_\n]+)_(?=[\s).,;:!?]|$)/g, "$1<em>$2</em>");
  const out: string[] = [];
  let list: string[] = [];
  let para: string[] = [];
  const flush = () => {
    if (list.length) { out.push(`<ul>${list.map((l) => `<li>${l}</li>`).join("")}</ul>`); list = []; }
    if (para.length) { out.push(`<p>${para.join("<br/>")}</p>`); para = []; }
  };
  for (const raw of src.split("\n")) {
    const line = raw.trimEnd();
    if (!line.trim()) { flush(); continue; }
    const li = line.match(/^\s*[-*]\s+(.*)$/);
    if (li) { if (para.length) flush(); list.push(inline(li[1])); continue; }
    if (list.length) flush();
    const bq = line.match(/^>\s?(.*)$/);
    if (bq) { flush(); out.push(`<blockquote>${inline(bq[1])}</blockquote>`); continue; }
    const h = line.match(/^#{1,4}\s+(.*)$/);
    if (h) { flush(); out.push(`<p><strong>${inline(h[1])}</strong></p>`); continue; }
    para.push(inline(line));
  }
  flush();
  return out.join("");
}
