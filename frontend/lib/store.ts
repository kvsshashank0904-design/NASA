"use client";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { ChatAction, ChatMsg, Layer, Plan, Pt, Sim, Target } from "./types";

export type LayerState = { visible: boolean; opacity: number };
export type Overlay = { kind: string; url: string; bbox: number[]; summary?: Record<string, unknown> };
export type PickMode = null | "start" | "goal" | "habitat";

type State = {
  hydrated: boolean;
  layerDefs: Layer[];
  layers: Record<string, LayerState>;
  selected: Pt | null;
  habitat: Pt | null;
  start: Pt | null;
  goal: Pt | null;
  pickMode: PickMode;
  plan: Plan | null;
  selectedProfile: string | null;
  showAllCandidates: boolean;
  targets: Target[];
  missionTargets: Target[];
  overlay: Overlay | null;
  sim: Sim | null;
  simIndex: number;
  flyTo: { lon: number; lat: number; height?: number; nonce: number } | null;
  sceneMode: "3D" | "2D";
  backend: "unknown" | "up" | "down";
  browserOnline: boolean;
  chat: ChatMsg[];
  missionId: number | null;
  planSavedAt: string | null;

  setLayerDefs: (d: Layer[]) => void;
  toggleLayer: (id: string, on?: boolean) => void;
  setOpacity: (id: string, o: number) => void;
  set: (p: Partial<State>) => void;
  setPlan: (p: Plan | null, profile?: string | null) => void;
  fly: (lon: number, lat: number, height?: number) => void;
  pick: (p: Pt) => void;
  addMissionTarget: (t: Target) => void;
  removeMissionTarget: (id: string) => void;
  applyActions: (a: ChatAction[]) => void;
  pushChat: (m: ChatMsg) => void;
  clearChat: () => void;
};

const DEFAULT_ON = ["Mars_Viking_MDIM21_ClrMosaic_global_232m", "mx_targets", "mx_rovers", "mx_routes"];

export const useStore = create<State>()(
  persist(
    (set, get) => ({
      hydrated: false,
      layerDefs: [], layers: {},
      selected: null, habitat: null, start: null, goal: null, pickMode: null,
      plan: null, selectedProfile: null, showAllCandidates: true,
      targets: [], missionTargets: [], overlay: null, sim: null, simIndex: 0,
      flyTo: null, sceneMode: "3D", backend: "unknown", browserOnline: true, chat: [], missionId: null, planSavedAt: null,

      setLayerDefs: (defs) => set((s) => {
        const layers = { ...s.layers };
        for (const d of defs) if (!layers[d.id]) layers[d.id] = { visible: DEFAULT_ON.includes(d.id), opacity: d.kind === "wmts" && d.category !== "base" ? 0.85 : 1 };
        layers["Mars_Viking_MDIM21_ClrMosaic_global_232m"] = { ...layers["Mars_Viking_MDIM21_ClrMosaic_global_232m"], visible: layers["Mars_Viking_MDIM21_ClrMosaic_global_232m"]?.visible ?? true };
        return { layerDefs: defs, layers };
      }),
      toggleLayer: (id, on) => set((s) => ({ layers: { ...s.layers, [id]: { ...(s.layers[id] || { opacity: 1 }), visible: on ?? !s.layers[id]?.visible } } })),
      setOpacity: (id, o) => set((s) => ({ layers: { ...s.layers, [id]: { ...(s.layers[id] || { visible: true }), opacity: o } } })),
      set: (p) => set(p),
      setPlan: (plan, profile) => set(() => ({
        plan, sim: null, simIndex: 0, planSavedAt: plan ? new Date().toISOString() : null,
        selectedProfile: plan ? (profile ?? plan.comparison?.recommendation?.profile ?? plan.candidates[0]?.profile ?? null) : null,
        ...(plan ? { start: plan.start, goal: plan.goal } : {}),
      })),
      fly: (lon, lat, height) => set({ flyTo: { lon, lat, height, nonce: Date.now() + Math.random() } }),
      pick: (p) => {
        const mode = get().pickMode;
        if (mode === "start") set({ start: p, pickMode: null, selected: p });
        else if (mode === "goal") set({ goal: p, pickMode: null, selected: p });
        else if (mode === "habitat") set({ habitat: p, pickMode: null, selected: p });
        else set({ selected: p });
      },
      addMissionTarget: (t) => set((s) => (s.missionTargets.some((x) => x.id === t.id) ? s : { missionTargets: [...s.missionTargets, t] })),
      removeMissionTarget: (id) => set((s) => ({ missionTargets: s.missionTargets.filter((t) => t.id !== id) })),
      applyActions: (actions) => {
        for (const a of actions) {
          if (a.type === "show_plan") {
            get().setPlan(a.plan);
            get().toggleLayer("mx_routes", true);
            const mid = a.plan.candidates[0]?.geometry.coordinates;
            if (mid?.length) {
              const c = mid[Math.floor(mid.length / 2)];
              get().fly(c[0], c[1], Math.max(4000, a.plan.straight_line_m * 3.2));
            }
          } else if (a.type === "fly_to") get().fly(a.lon, a.lat);
          else if (a.type === "show_targets") { set({ targets: a.targets }); get().toggleLayer("mx_targets", true); }
          else if (a.type === "show_simulation") set({ sim: a.simulation, simIndex: 0, selectedProfile: a.profile });
          else if (a.type === "show_overlay") {
            const [w, s, e, n] = a.bbox;
            set({ overlay: { kind: a.kind, bbox: a.bbox, url: `/api/v1/terrain/overlay.png?kind=${a.kind}&west=${w}&south=${s}&east=${e}&north=${n}` } });
            get().toggleLayer("mx_hazard", true);
          }
        }
      },
      pushChat: (m) => set((s) => ({ chat: [...s.chat, m].slice(-60) })),
      clearChat: () => set({ chat: [] }),
    }),
    {
      name: "marsx-state-v1",
      skipHydration: true,   // rehydrated from Shell after mount, so server and first client render match
      // what survives a reload / loss of signal: the mission plan, not transient UI
      partialize: (s) => ({ layers: s.layers, habitat: s.habitat, start: s.start, goal: s.goal, plan: s.plan, selectedProfile: s.selectedProfile,
        missionTargets: s.missionTargets, chat: s.chat.slice(-30), missionId: s.missionId, planSavedAt: s.planSavedAt }),
      onRehydrateStorage: () => (state) => { state?.set({ hydrated: true }); },
    },
  ),
);

export const PROFILE_COLORS: Record<string, string> = { safest: "#3ecf8e", shortest: "#f0a13a", balanced: "#3b9eff", return: "#c9b6ff" };
