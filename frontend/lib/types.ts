export type Pt = { lon: number; lat: number; name?: string };

export type Layer = {
  id: string; category: string; category_title: string; title: string; description: string;
  mission?: string | null; instrument?: string | null; source?: string; source_url?: string;
  kind: "wmts" | "overlay" | "points" | "rovers" | "targets" | "routes";
  tile_url?: string; format?: string; max_level?: number; bbox?: number[];
  timestamp?: string | null; resolution?: string | null; attribution: string; limitations: string;
  overlay?: string; endpoint?: string;
};

export type RouteCandidate = {
  profile: string; description: string; route_id?: number;
  geometry: { type: "LineString"; coordinates: number[][] };
  distance_m: number; straight_line_m: number; ascent_m: number; descent_m: number;
  max_along_track_grade_deg: number; max_cell_slope_deg: number; mean_slope_deg: number; mean_roughness_m: number;
  hazard_exposure: { nominal: number; caution: number; high: number };
  interpolated_fraction: number;
  energy: { traction_wh: number; hotel_wh: number; total_wh: number; kind: string };
  duration_h: { value: number; kind: string };
  difficulty_index: { value: number; kind: string; formula: string };
  elevation_profile: { distance_m: number; elevation_m: number; slope_deg: number; hazard: string; quality: string }[];
  confidence: { level: string; reasons: string[] };
  weights: Record<string, number>; slope_limit_deg: number; identical_to?: string;
  return_feasibility?: { feasible: boolean; reason: string; round_trip_energy_wh_with_margin?: number; round_trip_distance_m?: number; round_trip_duration_h?: number; battery_wh?: number; safety_margin?: number };
  segments?: { start_m: number; end_m: number; hazard: string; quality: string }[];
};

export type Plan = {
  plan_id: string; start: Pt; goal: Pt; straight_line_m: number;
  dem: { id: string; name: string; mission: string; instrument: string; resolution_m: number; effective_resolution_m: number; limitations: string; source_url: string };
  analysis_bbox: number[]; grid_cells: number;
  constraints: Record<string, number>; vehicle: Record<string, number | string | null>;
  candidates: RouteCandidate[]; return_route: RouteCandidate | null;
  failures: { profile: string; reason: string }[]; warnings: string[];
  algorithm: string; hazard_basis: string;
  comparison?: { rows: Record<string, number | string | boolean | null>[]; recommendation: { profile: string; reason: string } | null };
  science_nearby?: { id: string; name: string; category: string; lon: number; lat: number; offset_m: number; score: number }[];
};

export type Target = {
  id: string; name: string; category: string; lon: number; lat: number; kind?: string;
  summary?: string; evidence?: string | null; hypothesis?: string | null; minerals?: string[];
  coordinate_source?: string; datasets?: string[]; reference_ids?: string[];
  distance_m?: number | null; score: number; score_components?: Record<string, number>;
  mineral_context?: { detections_within_25km: number; nearest_m: number | null };
};

export type SimFrame = { t_s: number; phase: string; lon: number; lat: number; elev_m: number | null; distance_m: number; energy_wh: number; energy_pct: number; comm: string; speed_kmh: number };
export type Sim = {
  simulated: true; label: string; scenario: string; scenario_description: string; outcome: string; target_reached: boolean;
  summary: { duration_h: number; distance_m: number; energy_used_wh: number; energy_remaining_wh: number; energy_remaining_pct: number; battery_wh: number; reserve_wh: number };
  assumptions: Record<string, unknown>; frames: SimFrame[]; events: { t_s: number; kind: string; message: string }[];
};

export type ChatAction =
  | { type: "show_plan"; plan_id: string; plan: Plan }
  | { type: "fly_to"; lon: number; lat: number }
  | { type: "show_targets"; targets: Target[] }
  | { type: "show_overlay"; kind: string; bbox: number[] }
  | { type: "highlight_return"; plan_id: string }
  | { type: "show_simulation"; plan_id: string; profile: string; simulation: Sim };

export type ChatMsg = {
  role: "user" | "assistant"; content: string; mode?: string; note?: string | null; model?: string | null;
  tool_trace?: { tool: string; input: Record<string, unknown>; ok: boolean; summary: string }[];
  sources?: { id: string; name: string; mission: string | null; instrument: string | null; url: string }[];
  error?: boolean;
};
