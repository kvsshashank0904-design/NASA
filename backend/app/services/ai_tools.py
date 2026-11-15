"""MARS AI tool layer. Every tool is a thin wrapper over a real backend service; the
LLM (or the deterministic planner) never computes terrain, routes or observations itself.
"""
from __future__ import annotations

import math
import re
import uuid
from collections import OrderedDict

from ..mars import haversine_m, norm_lon
from . import catalog, environment, routing, science, simulation, terrain
from .dem import DemUnavailable

PLAN_STORE: "OrderedDict[str, dict]" = OrderedDict()


def store_plan(plan: dict) -> str:
    pid = uuid.uuid4().hex[:10]
    plan["plan_id"] = pid
    PLAN_STORE[pid] = plan
    while len(PLAN_STORE) > 40:
        PLAN_STORE.popitem(last=False)
    return pid


def _num(desc, **kw):
    return {"type": "number", "description": desc, **kw}


_LON = _num("East-positive longitude in degrees (-180..180 or 0..360)")
_LAT = _num("Planetocentric latitude in degrees (-90..90)", minimum=-90, maximum=90)

TOOL_SPECS = [
    {"name": "search_locations", "description": "Look up named Martian features, landing sites or science targets by name. Use this to turn a place name into coordinates - never guess coordinates.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "get_location_info", "description": "Elevation (with dataset, resolution and quality flag), nearest named features, nearby hydrous-mineral detections and rovers for a coordinate.",
     "input_schema": {"type": "object", "properties": {"lon": _LON, "lat": _LAT}, "required": ["lon", "lat"]}},
    {"name": "get_terrain_profile", "description": "Straight-line elevation profile between two points from the best available DEM.",
     "input_schema": {"type": "object", "properties": {"start_lon": _LON, "start_lat": _LAT, "end_lon": _LON, "end_lat": _LAT}, "required": ["start_lon", "start_lat", "end_lon", "end_lat"]}},
    {"name": "get_hazard_assessment", "description": "Slope/roughness statistics and inferred hazard-class fractions for a circular area. Hazards are inferred from DEM slope, not observed.",
     "input_schema": {"type": "object", "properties": {"lon": _LON, "lat": _LAT, "radius_km": _num("Radius in km (0.5-150)")}, "required": ["lon", "lat", "radius_km"]}},
    {"name": "find_science_targets", "description": "Ranked science targets near an origin (curated referenced sites, rover waypoints, CRISM/OMEGA hydrous mineral detections, named features), with score breakdowns.",
     "input_schema": {"type": "object", "properties": {"lon": _LON, "lat": _LAT, "radius_km": _num("Search radius in km"), "query": {"type": "string", "description": "Optional keyword filter, e.g. 'delta', 'clay'"}}, "required": ["lon", "lat", "radius_km"]}},
    {"name": "calculate_route", "description": "Run the A* terrain route planner between two points. Returns safest/shortest/balanced candidates plus an independent return route, each with distance, slope, hazard exposure, derived energy and duration, and data confidence. The plan is drawn on the map.",
     "input_schema": {"type": "object", "properties": {
         "start_lon": _LON, "start_lat": _LAT, "goal_lon": _LON, "goal_lat": _LAT,
         "priority": {"type": "string", "enum": ["safety", "speed", "energy", "balanced"], "description": "Mission priority used to set the balanced-profile weights"},
         "max_slope_deg": _num("Hard slope limit in degrees (default 25)"),
         "battery_wh": _num("Optional energy budget in Wh for return-feasibility checks")},
         "required": ["start_lon", "start_lat", "goal_lon", "goal_lat"]}},
    {"name": "compare_routes", "description": "Side-by-side comparison and metric-based recommendation for a previously calculated plan.",
     "input_schema": {"type": "object", "properties": {"plan_id": {"type": "string"}}, "required": ["plan_id"]}},
    {"name": "generate_return_route", "description": "Return-route details and round-trip feasibility for a previously calculated plan.",
     "input_schema": {"type": "object", "properties": {"plan_id": {"type": "string"}, "profile": {"type": "string", "enum": ["safest", "shortest", "balanced"]}}, "required": ["plan_id"]}},
    {"name": "get_environmental_observations", "description": "Latest available and recent REMS (Curiosity, Gale) or MEDA (Perseverance, Jezero) sol summaries plus published RAD radiation dose. Observations are dated and are not live weather.",
     "input_schema": {"type": "object", "properties": {"station": {"type": "string", "enum": ["rems", "meda", "nearest"]}, "lon": _LON, "lat": _LAT}, "required": ["station"]}},
    {"name": "get_dataset_metadata", "description": "Provenance for the NASA datasets integrated in MARS-X: mission, instrument, source URL, observation time, coverage, resolution, format, processing, limitations.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string", "description": "Dataset id or keyword, e.g. 'MOLA', 'CRISM', 'thermal'. Empty lists all."}}}},
    {"name": "simulate_mission_scenario", "description": "Run the mission digital twin on a calculated plan under a scenario. Output is a simulation, not a measurement.",
     "input_schema": {"type": "object", "properties": {"plan_id": {"type": "string"}, "profile": {"type": "string", "enum": ["safest", "shortest", "balanced"]},
                                                       "scenario": {"type": "string", "enum": list(simulation.SCENARIOS)}, "battery_wh": _num("Battery capacity in Wh")}, "required": ["plan_id", "scenario"]}},
    {"name": "search_knowledge_base", "description": "Retrieve passages from the MARS-X scientific knowledge base (dataset documentation, instrument limitations, curated science findings with references).",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
]

PRIORITY_WEIGHTS = {
    "safety": {"distance": 0.5, "slope": 3.0, "roughness": 1.5, "hazard": 4.0, "energy": 0.5},
    "speed": {"distance": 1.0, "slope": 0.5, "roughness": 0.3, "hazard": 1.0, "energy": 0.2},
    "energy": {"distance": 0.5, "slope": 1.0, "roughness": 0.5, "hazard": 1.5, "energy": 3.0},
    "balanced": dict(routing.PROFILES["balanced"]),
}


def _route_brief(c: dict) -> dict:
    return {"profile": c["profile"], "distance_m": c["distance_m"], "ascent_m": c["ascent_m"], "descent_m": c["descent_m"],
            "mean_slope_deg": c["mean_slope_deg"], "max_cell_slope_deg": c["max_cell_slope_deg"],
            "hazard_exposure": c["hazard_exposure"], "interpolated_fraction": c["interpolated_fraction"],
            "energy_wh_derived": c["energy"]["total_wh"], "duration_h_derived": c["duration_h"]["value"],
            "difficulty_index": c["difficulty_index"]["value"], "confidence": c["confidence"],
            "identical_to": c.get("identical_to"), "return_feasibility": c.get("return_feasibility")}


# --------------------------------------------------------------------------- knowledge base (lexical RAG)

_KB: list[dict] | None = None
_STOP = set("the a an of and or to in on for with is are was were be by at from that this it as its what which how where does do can i me my about near any".split())


def _tokens(s: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", s.lower()) if t not in _STOP and len(t) > 1]


def knowledge_base() -> list[dict]:
    global _KB
    if _KB is not None:
        return _KB
    refs = {r[0]: r for r in catalog.REFERENCES}
    docs = []
    for d in catalog.DATASETS:
        docs.append({"id": f"dataset:{d['id']}", "title": d["name"], "source": d["source"], "url": d["source_url"],
                     "text": f"{d['name']}. Mission: {d['mission']}. Instrument: {d['instrument']}. Coverage: {d['coverage']}. "
                             f"Resolution: {d['resolution']}. Observation time: {d['observation_time']}. Format: {d['data_format']}. "
                             f"Processing: {d['processing']} Limitations: {d['limitations']}"})
    for lyr in catalog.layers():
        docs.append({"id": f"layer:{lyr['id']}", "title": lyr["title"], "source": lyr.get("source", ""), "url": lyr.get("source_url"),
                     "text": f"{lyr['title']} ({lyr['category_title']}). {lyr.get('description', '')[:900]} Limitations: {lyr.get('limitations', '')}"})
    for t in catalog.resolve_targets():
        cites = "; ".join(refs[r][1] for r in t.get("refs", []) if r in refs)
        docs.append({"id": f"target:{t['id']}", "title": t["name"], "source": cites or t["coordinate_source"], "url": None,
                     "text": f"{t['name']} ({t['category']}). {t['summary']} Evidence: {t['evidence']} Hypothesis (not established): "
                             f"{t.get('hypothesis') or 'none stated'}. Minerals: {', '.join(t.get('minerals') or [])}. References: {cites}"})
    docs.append({"id": "method:routing", "title": "MARS-X route planning method", "source": "MARS-X", "url": None,
                 "text": routing.__doc__ or ""})
    docs.append({"id": "method:radiation", "title": "Surface radiation (RAD)", "source": environment.RAD["reference"], "url": None,
                 "text": f"MSL RAD measured a surface galactic cosmic ray dose equivalent of 0.64 +/- 0.12 mSv/day and dose rate 0.21 mGy/day "
                         f"in Gale crater ({environment.RAD['period']}). {environment.RAD['limitations']}"})
    for d in docs:
        d["_tok"] = _tokens(d["title"] + " " + d["text"])
    _KB = docs
    return docs


def kb_search(query: str, k: int = 4) -> list[dict]:
    docs = knowledge_base()
    q = _tokens(query)
    if not q:
        return []
    n = len(docs)
    df = {t: sum(1 for d in docs if t in d["_tok"]) for t in set(q)}
    scored = []
    for d in docs:
        tf = {t: d["_tok"].count(t) for t in set(q)}
        s = sum((tf[t] / (tf[t] + 1.5)) * math.log(1 + n / (1 + df[t])) for t in tf if tf[t])
        if any(t in _tokens(d["title"]) for t in q):
            s *= 1.5
        if s > 0:
            scored.append((s, d))
    scored.sort(key=lambda x: -x[0])
    return [{"id": d["id"], "title": d["title"], "source": d["source"], "url": d["url"], "passage": d["text"][:1100], "score": round(s, 2)}
            for s, d in scored[:k]]


# --------------------------------------------------------------------------- executor

class ToolBox:
    def __init__(self, db):
        self.db = db
        self.actions: list[dict] = []
        self.trace: list[dict] = []
        self.sources: dict[str, dict] = {}

    def _cite(self, *dataset_ids: str):
        by = {d["id"]: d for d in catalog.DATASETS}
        for i in dataset_ids:
            if i in by:
                self.sources[i] = {"id": i, "name": by[i]["name"], "mission": by[i]["mission"], "instrument": by[i]["instrument"],
                                   "url": by[i]["source_url"]}

    def _cite_dem(self, dem: dict):
        self._cite(dem["id"])

    def run(self, name: str, args: dict) -> dict:
        fn = getattr(self, f"t_{name}", None)
        if fn is None:
            res = {"error": f"unknown tool {name}"}
        else:
            try:
                res = fn(**(args or {}))
            except (DemUnavailable, routing.RouteError, ValueError, KeyError, TypeError) as e:
                res = {"error": f"{type(e).__name__}: {e}"}
        self.trace.append({"tool": name, "input": args, "ok": "error" not in res, "summary": _summarise(name, res)})
        return res

    # ---- tools
    def t_search_locations(self, query: str):
        self._cite("iau_nomenclature")
        return {"results": science.search_locations(self.db, query, 8)}

    def t_get_location_info(self, lon: float, lat: float):
        info = science.location_info(self.db, lon, lat)
        self._cite("mola_megdr_128" if "MOLA" in (info["elevation"].get("dataset") or "") else "jezero_ctx_dtm_20m", "iau_nomenclature", "hydrous_minerals")
        self.actions.append({"type": "fly_to", "lon": info["lon"], "lat": lat})
        return info

    def t_get_terrain_profile(self, start_lon, start_lat, end_lon, end_lat):
        p = terrain.terrain_profile(start_lon, start_lat, end_lon, end_lat, 60)
        self._cite_dem(p["dem"])
        step = max(1, len(p["samples"]) // 25)
        return {**{k: p[k] for k in ("distance_m", "ascent_m", "descent_m", "min_elevation_m", "max_elevation_m", "note")},
                "dem": {k: p["dem"][k] for k in ("name", "effective_resolution_m", "limitations")},
                "samples": [{k: s[k] for k in ("distance_m", "elevation_m", "slope_deg", "quality")} for s in p["samples"][::step]]}

    def t_get_hazard_assessment(self, lon, lat, radius_km):
        radius_km = min(max(float(radius_km), 0.5), 150.0)
        dlat = math.degrees(radius_km * 1000 / 3_396_190.0)
        dlon = dlat / max(0.05, math.cos(math.radians(lat)))
        a = terrain.analyze_region(lon - dlon, lat - dlat, lon + dlon, lat + dlat, max_cells=120_000)
        self._cite_dem(a["summary"]["dem"])
        self.actions.append({"type": "show_overlay", "kind": "hazard", "bbox": a["summary"]["bbox"]})
        return a["summary"]

    def t_find_science_targets(self, lon, lat, radius_km, query: str | None = None):
        res = science.find_targets(lon, lat, radius_km, limit=8, query=query or None)
        self._cite("hydrous_minerals", "iau_nomenclature", "m20_localization", "msl_localization")
        self.actions.append({"type": "show_targets", "targets": [{k: t[k] for k in ("id", "name", "category", "lon", "lat", "score", "kind", "summary", "distance_m")} for t in res["targets"]]})
        slim = [{k: t[k] for k in ("id", "name", "category", "lon", "lat", "distance_m", "score", "score_components", "summary", "evidence",
                                   "hypothesis", "coordinate_source", "reference_ids")} for t in res["targets"]]
        return {"count": res["count"], "targets": slim, "scoring_note": res["scoring"]["note"], "disclaimer": res["disclaimer"]}

    def t_calculate_route(self, start_lon, start_lat, goal_lon, goal_lat, priority: str = "balanced", max_slope_deg: float = 25.0,
                          battery_wh: float | None = None):
        veh = routing.Vehicle(battery_wh=battery_wh)
        plan = routing.plan_routes((start_lon, start_lat), (goal_lon, goal_lat), weights=PRIORITY_WEIGHTS.get(priority, PRIORITY_WEIGHTS["balanced"]),
                                   max_slope_deg=max_slope_deg, vehicle=veh)
        plan["comparison"] = routing.compare(plan["candidates"])
        pid = store_plan(plan)
        self._cite_dem(plan["dem"])
        self.actions.append({"type": "show_plan", "plan_id": pid, "plan": plan})
        return {"plan_id": pid, "straight_line_m": plan["straight_line_m"],
                "dem": {k: plan["dem"][k] for k in ("name", "effective_resolution_m", "limitations")},
                "candidates": [_route_brief(c) for c in plan["candidates"]],
                "return_route": _route_brief(plan["return_route"]) if plan["return_route"] else None,
                "failures": plan["failures"], "warnings": plan["warnings"], "vehicle_assumptions": plan["vehicle"],
                "hazard_basis": plan["hazard_basis"], "recommendation": plan["comparison"]["recommendation"]}

    def t_compare_routes(self, plan_id: str):
        plan = PLAN_STORE[plan_id]
        return routing.compare(plan["candidates"])

    def t_generate_return_route(self, plan_id: str, profile: str | None = None):
        plan = PLAN_STORE[plan_id]
        if not plan["return_route"]:
            return {"error": "no traversable return route exists for this plan"}
        c = next((c for c in plan["candidates"] if c["profile"] == profile), None) or plan["candidates"][0]
        self.actions.append({"type": "highlight_return", "plan_id": plan_id})
        return {"return_route": _route_brief(plan["return_route"]), "description": plan["return_route"]["description"],
                "for_outbound_profile": c["profile"], "round_trip": c.get("return_feasibility")}

    def t_get_environmental_observations(self, station: str = "nearest", lon: float | None = None, lat: float | None = None):
        near = None
        if station == "nearest":
            if lon is None or lat is None:
                return {"error": "lon and lat are required when station is 'nearest'"}
            near = environment.nearest_station(norm_lon(lon), lat)
            station = near["station"]
        o = environment.observations(station, limit=7)
        self._cite(o["dataset_id"], "rad_surface")
        return {"station": o["station"], "location": o["location"], "provenance": o["provenance"], "latest": o["latest"],
                "recent_sols": o["history"]["sols"], "unavailable": o["unavailable"], "nearest_station_check": near,
                "radiation_published": environment.RAD}

    def t_get_dataset_metadata(self, query: str | None = None):
        q = (query or "").lower()
        hits = [d for d in catalog.DATASETS if not q or q in (d["id"] + " " + d["name"] + " " + str(d["mission"]) + " " + str(d["instrument"]) + " " + d["category"]).lower()]
        for d in hits:
            self._cite(d["id"])
        if not hits:
            return {"datasets": [], "note": f"No integrated dataset matches '{query}'. Integrated ids: {[d['id'] for d in catalog.DATASETS]}"}
        return {"datasets": hits}

    def t_simulate_mission_scenario(self, plan_id: str, scenario: str, profile: str | None = None, battery_wh: float | None = None):
        plan = PLAN_STORE[plan_id]
        c = next((c for c in plan["candidates"] if c["profile"] == profile), None) or plan["candidates"][0]
        ret = plan["return_route"]["geometry"]["coordinates"] if plan["return_route"] else None
        veh = routing.Vehicle(**{k: plan["vehicle"][k] for k in ("mass_kg", "rolling_resistance", "drivetrain_efficiency", "speed_kmh", "hotel_power_w")})
        sim = simulation.simulate(c["geometry"]["coordinates"], ret, scenario, veh, battery_wh or plan["vehicle"].get("battery_wh"),
                                  plan_constraints={**plan["constraints"], "cell_m": plan["dem"]["effective_resolution_m"]})
        self.actions.append({"type": "show_simulation", "plan_id": plan_id, "profile": c["profile"], "simulation": sim})
        return {"label": sim["label"], "scenario": scenario, "outcome": sim["outcome"], "target_reached": sim["target_reached"],
                "summary": sim["summary"], "events": sim["events"]}

    def t_search_knowledge_base(self, query: str):
        hits = kb_search(query)
        for h in hits:
            if h["id"].startswith("dataset:"):
                self._cite(h["id"].split(":", 1)[1])
        return {"passages": hits}


def _summarise(name: str, res: dict) -> str:
    if "error" in res:
        return res["error"]
    if name == "calculate_route":
        return f"plan {res['plan_id']}: {len(res['candidates'])} candidates on {res['dem']['name']} @ {res['dem']['effective_resolution_m']} m"
    if name == "find_science_targets":
        return f"{res['count']} targets; top: {res['targets'][0]['name'] if res['targets'] else 'none'}"
    if name == "get_location_info":
        return f"elevation {res['elevation'].get('value_m')} m ({res['elevation'].get('dataset')})"
    if name == "get_hazard_assessment":
        return f"hazard fractions {res['hazard_fraction']}"
    if name == "search_locations":
        return f"{len(res['results'])} matches"
    if name == "simulate_mission_scenario":
        return f"{res['scenario']}: {res['outcome']}"
    if name == "get_environmental_observations":
        return f"{res['station']} latest sol {res['latest'].get('sol')} ({res['latest'].get('terrestrial_date')})"
    if name == "search_knowledge_base":
        return f"{len(res['passages'])} passages"
    if name == "get_dataset_metadata":
        return f"{len(res['datasets'])} datasets"
    if name == "compare_routes":
        return f"recommend {res['recommendation']['profile'] if res.get('recommendation') else 'n/a'}"
    return "ok"
