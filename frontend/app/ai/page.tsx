"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { apiSend } from "@/lib/api";
import { fmtPt, mdToHtml } from "@/lib/format";
import { useStore } from "@/lib/store";
import type { ChatAction, ChatMsg } from "@/lib/types";
import { Notice, Page, useApi } from "@/components/ui";

type Status = { mode: "llm" | "planner"; model: string | null; note: string | null; tools: { name: string; description: string }[] };
type Reply = { reply: string; mode: string; note: string | null; model: string | null; tool_trace: ChatMsg["tool_trace"]; actions: ChatAction[]; sources: ChatMsg["sources"] };

const SUGGESTIONS = [
  "Find an interesting geological research location within 2 km of my habitat. Prioritize safe terrain and make sure I can return.",
  "Plan a route from the Perseverance landing site to the delta front.",
  "What are the terrain hazards within 8 km of my habitat?",
  "What is the weather at Jezero, and how much radiation should I expect?",
  "Simulate a dust storm on this route.",
  "How accurate is the MOLA elevation data?",
];

export default function AiPage() {
  const chat = useStore((s) => s.chat);
  const habitat = useStore((s) => s.habitat);
  const selected = useStore((s) => s.selected);
  const plan = useStore((s) => s.plan);
  const backend = useStore((s) => s.backend);
  const status = useApi<Status>("/api/v1/ai/status", [backend]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [showTools, setShowTools] = useState(false);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [chat.length, busy]);

  const send = async (msg: string) => {
    const m = msg.trim();
    if (!m || busy) return;
    const st = useStore.getState();
    const history = st.chat.filter((c) => !c.error).slice(-10).map((c) => ({ role: c.role, content: c.content }));
    st.pushChat({ role: "user", content: m });
    setText(""); setBusy(true);
    try {
      const r = await apiSend<Reply>("POST", "/api/v1/ai/chat", {
        message: m, history,
        context: { habitat: st.habitat, selected: st.selected, start: st.start, goal: st.goal, plan_id: st.plan?.plan_id, selected_profile: st.selectedProfile },
      });
      st.applyActions(r.actions || []);
      st.pushChat({ role: "assistant", content: r.reply, mode: r.mode, note: r.note, model: r.model, tool_trace: r.tool_trace, sources: r.sources });
    } catch (e) {
      st.pushChat({ role: "assistant", content: `MARS AI could not answer: ${(e as Error).message}`, error: true });
    }
    setBusy(false);
  };

  return (
    <Page title="MARS AI" kicker="Mission assistant · answers from backend tools"
      actions={chat.length > 0 ? <button className="btn btn-ghost btn-sm" onClick={() => useStore.getState().clearChat()}>Clear</button> : undefined}>
      <div className="card flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-[11px]">
        {status.data ? (
          <>
            <span className={`badge ${status.data.mode === "llm" ? "badge-mars" : "badge-blue"}`}>{status.data.mode === "llm" ? `Claude · ${status.data.model}` : "Deterministic tool planner"}</span>
            <button className="text-dim underline decoration-dotted" onClick={() => setShowTools((s) => !s)}>{status.data.tools.length} backend tools</button>
            {status.data.note && <span className="basis-full text-faint">{status.data.note}</span>}
          </>
        ) : status.error ? <span className="text-warn">MARS AI needs the backend, which is unreachable. Saved conversations stay readable.</span> : <span className="text-dim">Checking assistant status…</span>}
        {showTools && status.data && (
          <ul className="basis-full list-disc pl-4 text-dim fade-in">{status.data.tools.map((t) => <li key={t.name}><span className="num text-text">{t.name}</span> — {t.description.split(". ")[0]}.</li>)}</ul>
        )}
      </div>

      <div className="flex flex-wrap gap-1.5 text-[10.5px]">
        <span className="label self-center">Context sent</span>
        <span className={`badge ${habitat ? "badge-blue" : ""}`}>{habitat ? `Habitat ${fmtPt(habitat, 3)}` : "No habitat"}</span>
        {selected && <span className="badge">Selection {fmtPt(selected, 3)}</span>}
        <span className={`badge ${plan ? "badge-ok" : ""}`}>{plan ? `Plan ${plan.plan_id}` : "No active plan"}</span>
        {!habitat && <Link href="/explorer" className="text-blue hover:underline">set a habitat →</Link>}
      </div>

      {chat.length === 0 && (
        <div className="flex flex-col gap-1.5">
          <div className="label">Try</div>
          {SUGGESTIONS.map((s) => (
            <button key={s} className="card px-3 py-2 text-left text-[12px] text-text hover:border-line-strong" disabled={busy} onClick={() => send(s)}>{s}</button>
          ))}
          {!habitat && <Notice>Requests that mention “my habitat” need one: open Explorer, click a point (for example search “Perseverance”), then “Set as habitat”.</Notice>}
        </div>
      )}

      <div className="flex flex-col gap-3">
        {chat.map((m, i) => <Bubble key={i} m={m} />)}
        {busy && <div className="card flex items-center gap-2 self-start px-3 py-2 text-dim"><span className="h-1.5 w-1.5 rounded-full bg-mars pulse" />Calling backend tools (terrain, routing, science)…</div>}
        <div ref={end} />
      </div>

      <form className="sticky bottom-0 -mx-4 -mb-4 mt-auto flex gap-2 border-t border-line bg-ink/95 p-3 backdrop-blur" onSubmit={(e) => { e.preventDefault(); send(text); }}>
        <textarea className="input flex-1" rows={2} placeholder="Describe the mission you want to plan…" value={text} aria-label="Message MARS AI"
          onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(text); } }} />
        <button className="btn btn-mars h-auto" disabled={busy || !text.trim()}>Send</button>
      </form>
    </Page>
  );
}

function Bubble({ m }: { m: ChatMsg }) {
  const [open, setOpen] = useState(false);
  if (m.role === "user") return <div className="max-w-[88%] self-end rounded-lg rounded-br-sm border border-blue-dim bg-[#0e2340] px-3 py-2 text-[12.5px] text-white">{m.content}</div>;
  return (
    <div className={`card fade-in max-w-full self-start rounded-bl-sm px-3 py-2.5 ${m.error ? "border-[#7d2b29]" : ""}`}>
      <div className="md text-[12.5px] text-text" dangerouslySetInnerHTML={{ __html: mdToHtml(m.content) }} />
      {(m.tool_trace?.length || m.sources?.length || m.note) ? (
        <div className="mt-2 border-t border-line pt-2">
          <div className="flex flex-wrap items-center gap-1.5">
            {m.mode && <span className={`badge ${m.mode === "llm" ? "badge-mars" : "badge-blue"}`}>{m.mode === "llm" ? m.model || "Claude" : "Tool planner"}</span>}
            {!!m.tool_trace?.length && <button className="badge hover:text-text" onClick={() => setOpen((o) => !o)} aria-expanded={open}>{m.tool_trace.length} tool call{m.tool_trace.length > 1 ? "s" : ""} {open ? "▴" : "▾"}</button>}
            {m.sources?.map((s) => <a key={s.id} href={s.url} target="_blank" rel="noreferrer" className="badge badge-ok hover:underline" title={`${s.name} — ${s.mission || ""} ${s.instrument || ""}`}>{s.instrument?.split(";")[0] || s.id}</a>)}
          </div>
          {open && (
            <ol className="mt-2 flex flex-col gap-1 text-[11px] fade-in">
              {m.tool_trace!.map((t, i) => (
                <li key={i} className="rounded border border-line bg-ink px-2 py-1">
                  <div className="flex items-center gap-1.5"><span className={`h-1.5 w-1.5 rounded-full ${t.ok ? "bg-ok" : "bg-danger"}`} /><span className="num text-text">{t.tool}</span><span className="truncate text-dim">→ {t.summary}</span></div>
                  <div className="num truncate text-[10px] text-faint">{JSON.stringify(t.input)}</div>
                </li>
              ))}
            </ol>
          )}
          {m.note && <div className="mt-1.5 text-[10.5px] text-faint">{m.note}</div>}
        </div>
      ) : null}
    </div>
  );
}
