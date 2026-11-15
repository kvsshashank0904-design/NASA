"""MARS AI mission assistant.

Two interchangeable brains over the same tool layer (ai_tools.ToolBox):

* LLM mode  - Claude with tool calling (needs an Anthropic credential).
* Planner mode - a deterministic intent router that calls the same tools and writes its
  answer only from tool outputs. Used when no credential is configured or the API fails,
  so the assistant keeps working without a link to Earth.
"""
from __future__ import annotations

import json
import logging
import os
import re

from ..config import settings
from ..mars import haversine_m, norm_lon
from . import catalog
from .ai_tools import PLAN_STORE, TOOL_SPECS, ToolBox

log = logging.getLogger("marsx.ai")

SYSTEM_PROMPT = """You are MARS AI, the mission-planning assistant inside MARS-X, a planetary exploration workstation used by astronauts on Mars.

How you work
- Backend tools are the only source of truth for coordinates, elevations, slopes, routes, hazards, science targets and environmental observations. Call them; never estimate these yourself and never invent coordinates, distances or measurements. Resolve place names with search_locations.
- The "Mission context" block in the user's message carries the habitat, selected map point, planner start/goal and active plan id when they exist. Use those coordinates when the user says "my habitat", "here", "this route".
- For a mission request, typically: locate the start, find science targets, calculate routes to the best candidates, compare them, check the return route, then recommend. Routes you calculate are drawn on the 3D map automatically.
- If a tool returns an error or a warning (for example insufficient DEM resolution), say so plainly and adapt.

How you answer
- Lead with the recommendation, then the numbers that support it, then caveats. Keep it tight: an astronaut is reading this in a suit.
- Quote numbers exactly as tools returned them and say what they are: energy and duration are derived estimates under stated vehicle assumptions; hazards are inferred from DEM slope, not observed; REMS/MEDA values are dated observations from one station, not live weather at the user's location; RAD values are published historical averages.
- State data confidence and what the DEM cannot see (rocks, sand, scarps below pixel size).
- Name the NASA datasets behind each claim (e.g. "MOLA MEGDR 463 m", "CTX DTM 20 m", "CRISM/OMEGA detections, Carter et al. 2013").
- Separate observed evidence from hypotheses. Never state or imply that any feature proves past or present life.
- If something is not available in MARS-X, say it is unavailable rather than filling the gap."""


def credential_available() -> bool:
    return bool(settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def _context_block(ctx: dict) -> str:
    keep = {k: ctx[k] for k in ("habitat", "selected", "start", "goal", "plan_id", "selected_profile") if ctx.get(k)}
    return "\n\nMission context (from the MARS-X interface):\n" + json.dumps(keep) if keep else ""


def chat(db, message: str, history: list[dict] | None = None, context: dict | None = None) -> dict:
    context = context or {}
    box = ToolBox(db)
    mode, note = "planner", None
    if credential_available() and not settings.offline:
        try:
            reply = _llm_chat(box, message, history or [], context)
            mode = "llm"
        except Exception as e:  # noqa: BLE001 - any API failure degrades to the deterministic planner
            log.warning("LLM unavailable, using deterministic planner: %s", e)
            note = f"LLM unavailable ({type(e).__name__}); answered by the deterministic tool planner."
            box = ToolBox(db)
            reply = _planner_chat(box, message, context)
    else:
        note = "No Anthropic credential configured: answered by the deterministic tool planner (same backend tools, no language model)."
        reply = _planner_chat(box, message, context)
    return {"reply": reply, "mode": mode, "note": note, "model": settings.ai_model if mode == "llm" else None,
            "tool_trace": box.trace, "actions": box.actions, "sources": list(box.sources.values())}


# --------------------------------------------------------------------------- LLM mode

def _llm_chat(box: ToolBox, message: str, history: list[dict], context: dict) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key) if settings.anthropic_api_key else anthropic.Anthropic()
    messages = [{"role": h["role"], "content": h["content"]} for h in history[-12:] if h.get("role") in ("user", "assistant") and h.get("content")]
    messages.append({"role": "user", "content": message + _context_block(context)})
    tools = [dict(t) for t in TOOL_SPECS]
    for _ in range(settings.ai_max_tool_rounds):
        resp = client.beta.messages.create(
            model=settings.ai_model, max_tokens=8000, system=SYSTEM_PROMPT, tools=tools, messages=messages,
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        )
        if resp.stop_reason == "refusal":
            return "MARS AI could not process that request. Try rephrasing it as a mission-planning question."
        if resp.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": resp.content})
            continue
        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if b.type == "text").strip() or "(no response)"
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for b in resp.content:
            if b.type != "tool_use":
                continue
            out = box.run(b.name, dict(b.input) if isinstance(b.input, dict) else {})
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(out, default=str)[:60000],
                            "is_error": "error" in out})
        messages.append({"role": "user", "content": results})
    return "I reached the tool-call limit for one request. The partial results are shown in the tool trace; ask me to continue."


# --------------------------------------------------------------------------- deterministic planner mode

# phrase -> curated target id (longer phrases shadow shorter ones). Coordinates always come from the catalogue.
_ALIASES = {
    "perseverance landing site": "jezero-landing", "octavia e. butler": "jezero-landing", "jezero landing site": "jezero-landing",
    "delta front": "jezero-delta-front", "western delta": "jezero-delta-front", "jezero delta": "jezero-delta-front",
    "three forks": "jezero-three-forks", "sample depot": "jezero-three-forks", "bright angel": "jezero-bright-angel",
    "cheyava falls": "jezero-bright-angel", "seitah": "jezero-seitah", "yellowknife bay": "gale-yellowknife",
    "mount sharp": "gale-mount-sharp", "columbia hills": "gusev-columbia",
    "perseverance": "perseverance-current", "curiosity": "curiosity-current",
}


def _dur(h: float) -> str:
    m = round(h * 60)
    return f"{m} min" if m < 90 else f"{h:.1f} h"


def _named_places() -> list[tuple[str, float, float, str]]:
    out = [(t["name"], t["lon"], t["lat"], "curated science target") for t in catalog.resolve_targets()]
    out += [(n, lo, la, "landing site") for n, lo, la, _ in catalog.LANDING_SITES]
    out += [(f["name"], f["lon"], f["lat"], f["feature_type"]) for f in catalog.nomenclature()["features"]]
    return out


def _find_places(text: str) -> list[dict]:
    low = text.lower()
    hits = []
    by_id = {t["id"]: t for t in catalog.resolve_targets()}
    for alias, tid in _ALIASES.items():
        m = re.search(rf"\b{re.escape(alias)}\b", low)
        if m and tid in by_id:
            t = by_id[tid]
            hits.append({"name": t["name"], "lon": t["lon"], "lat": t["lat"], "pos": m.start(), "len": len(alias), "kind": "curated science target"})
    for name, lon, lat, kind in _named_places():
        if len(name) < 4:
            continue
        m = re.search(rf"\b{re.escape(name.lower())}\b", low)
        if m:
            hits.append({"name": name, "lon": lon, "lat": lat, "pos": m.start(), "len": len(name), "kind": kind})
    # drop matches contained in longer matches ("Gale" inside "Gale crater ..."), keep text order
    hits.sort(key=lambda h: -h["len"])
    kept = []
    for h in hits:
        if not any(k["pos"] <= h["pos"] < k["pos"] + k["len"] for k in kept):
            kept.append(h)
    kept.sort(key=lambda h: h["pos"])
    return kept


def _find_coords(text: str) -> list[dict]:
    out = []
    for m in re.finditer(r"(-?\d{1,2}(?:\.\d+)?)\s*°?\s*([NS])[,\s]+(-?\d{1,3}(?:\.\d+)?)\s*°?\s*([EW])", text, re.I):
        lat = float(m.group(1)) * (-1 if m.group(2).upper() == "S" else 1)
        lon = float(m.group(3)) * (-1 if m.group(4).upper() == "W" else 1)
        out.append({"name": f"{lat:.4f}, {lon:.4f}", "lon": norm_lon(lon), "lat": lat, "pos": m.start(), "kind": "coordinate"})
    for m in re.finditer(r"lat(?:itude)?\s*[=:]?\s*(-?\d{1,2}(?:\.\d+)?)[,\s]+lon(?:gitude)?\s*[=:]?\s*(-?\d{1,3}(?:\.\d+)?)", text, re.I):
        out.append({"name": f"{float(m.group(1)):.4f}, {float(m.group(2)):.4f}", "lon": norm_lon(float(m.group(2))), "lat": float(m.group(1)), "pos": m.start(), "kind": "coordinate"})
    return [o for o in out if -90 <= o["lat"] <= 90]


def _radius_km(text: str, default: float) -> float:
    m = re.search(r"within\s+(\d+(?:\.\d+)?)\s*(km|kilomet\w*|m|met\w*)\b", text, re.I) or re.search(r"(\d+(?:\.\d+)?)\s*(km|kilomet\w*)\s+(?:radius|around|of)", text, re.I)
    if not m:
        return default
    v = float(m.group(1))
    return v if m.group(2).lower().startswith('k') else v / 1000.0


def _has(text: str, *words: str) -> bool:
    return any(re.search(rf"\b{w}", text, re.I) for w in words)


def _priority(text: str) -> str:
    if _has(text, "safe", "safest", "hazard", "careful", "low risk"):
        return "safety"
    if _has(text, "fast", "quick", "shortest", "speed"):
        return "speed"
    if _has(text, "energy", "battery", "efficient", "power"):
        return "energy"
    return "balanced"


def _fmt_pt(p: dict) -> str:
    return f"{abs(p['lat']):.4f}°{'N' if p['lat'] >= 0 else 'S'}, {abs(p['lon']):.4f}°{'E' if p['lon'] >= 0 else 'W'}"


def _route_lines(c: dict) -> str:
    hz = c["hazard_exposure"]
    return (f"- **{c['profile']}**: {c['distance_m'] / 1000:.2f} km, mean slope {c['mean_slope_deg']}°, steepest cell {c['max_cell_slope_deg']}°, "
            f"caution/high terrain {100 * (hz['caution'] + hz['high']):.0f}% of length, ~{c['energy_wh_derived'] / 1000:.1f} kWh and "
            f"~{_dur(c['duration_h_derived'])} (derived estimates), difficulty {c['difficulty_index']}/100"
            + (f" *(identical path to '{c['identical_to']}')*" if c.get("identical_to") else ""))


def _plan_section(res: dict) -> list[str]:
    out = [f"Route planner ran on **{res['dem']['name']}** at {res['dem']['effective_resolution_m']} m cells (plan `{res['plan_id']}`, drawn on the map):"]
    out += [_route_lines(c) for c in res["candidates"]]
    for f in res["failures"]:
        out.append(f"- **{f['profile']}**: no route - {f['reason']}")
    if res.get("recommendation"):
        out.append(f"\n**Recommended outbound route:** {res['recommendation']['reason']}")
    r = res.get("return_route")
    if r:
        rf = next((c.get("return_feasibility") for c in res["candidates"] if c["profile"] == (res.get("recommendation") or {}).get("profile")), None)
        out.append(f"\n**Return:** an independent return route exists: {r['distance_m'] / 1000:.2f} km, mean slope {r['mean_slope_deg']}°, "
                   f"~{r['energy_wh_derived'] / 1000:.1f} kWh (derived). " + (f"Round trip {rf['round_trip_distance_m'] / 1000:.2f} km, "
                   f"{rf['round_trip_energy_wh_with_margin'] / 1000:.1f} kWh including a {rf['safety_margin']:.0%} margin - {rf['reason']}." if rf else ""))
    else:
        out.append("\n**Return:** no traversable return route was found - do not commit to this traverse.")
    for w in res["warnings"]:
        out.append(f"\n> ⚠ {w}")
    conf = res["candidates"][0]["confidence"] if res["candidates"] else None
    if conf:
        out.append(f"\n**Data confidence: {conf['level']}.** " + " ".join(conf["reasons"]))
    out.append(f"_{res['hazard_basis']} Energy/duration assume a {res['vehicle_assumptions']['mass_kg']:.0f} kg rover at "
               f"{res['vehicle_assumptions']['speed_kmh']} km/h (editable in Mission Planner)._")
    return out


def _planner_chat(box: ToolBox, message: str, ctx: dict) -> str:
    text = message.strip()
    places = sorted(_find_places(text) + _find_coords(text), key=lambda p: p["pos"])
    habitat = ctx.get("habitat") or ctx.get("start")
    selected = ctx.get("selected")
    wants_here = _has(text, "habitat", "my location", "my position", "base", "here", "start point")
    origin = None
    if wants_here and habitat:
        origin = {"name": "your habitat", "lon": habitat["lon"], "lat": habitat["lat"]}
    elif places:
        origin = places[0]
    elif habitat:
        origin = {"name": "your habitat", "lon": habitat["lon"], "lat": habitat["lat"]}
    elif selected:
        origin = {"name": "the selected map point", "lon": selected["lon"], "lat": selected["lat"]}

    plan_id = ctx.get("plan_id") if ctx.get("plan_id") in PLAN_STORE else None

    # --- simulation / what-if on the active plan
    if _has(text, "simulat", "what if", "scenario", "dust storm", "emergency"):
        if not plan_id:
            return "There is no active route plan to simulate. Plan a route first (Mission Planner, or ask me to plan one), then ask again."
        scen = ("dust_storm" if _has(text, "dust") else "emergency_return" if _has(text, "emergency", "abort") else
                "terrain_hazard" if _has(text, "obstacle", "hazard", "blocked") else "energy_overrun" if _has(text, "energy", "battery", "sand") else
                "comm_degradation" if _has(text, "comm", "signal", "contact") else "nominal")
        r = box.run("simulate_mission_scenario", {"plan_id": plan_id, "scenario": scen, "profile": ctx.get("selected_profile")})
        if "error" in r:
            return f"The simulation could not run: {r['error']}"
        s = r["summary"]
        lines = [f"**{r['label']}**", f"Scenario **{scen}** on plan `{plan_id}` → outcome **{r['outcome']}** (target {'reached' if r['target_reached'] else 'not reached'}).",
                 f"Simulated totals: {s['distance_m'] / 1000:.2f} km driven in {s['duration_h']:.2f} h, {s['energy_used_wh'] / 1000:.1f} kWh used, "
                 f"{s['energy_remaining_pct']}% of a {s['battery_wh'] / 1000:.0f} kWh battery remaining.", "", "Key events:"]
        lines += [f"- t+{e['t_s'] // 60} min · {e['message']}" for e in r["events"] if e["kind"] != "objective"][:9]
        lines.append("\nOpen **Mission Simulation** to replay it on the map.")
        return "\n".join(lines)

    # --- environment
    if _has(text, "weather", "temperature", "pressure", "radiation", "dust", "wind", "environment", "cold", "uv"):
        args = {"station": "nearest", "lon": origin["lon"], "lat": origin["lat"]} if origin else {"station": "rems"}
        r = box.run("get_environmental_observations", args)
        if "error" in r:
            return f"Environmental data could not be retrieved: {r['error']}"
        l, rad = r["latest"], r["radiation_published"]
        lines = [f"**{r['station']}** ({r['location']}) - latest available observation, sol {l.get('sol')} on {l.get('terrestrial_date')} "
                 f"({l.get('age_days')} days old; **not live weather**). Source: {r['provenance']}.",
                 f"- Air temperature: {l.get('min_air_temp_c')} °C min / {l.get('max_air_temp_c')} °C max",
                 f"- Pressure: {l.get('pressure_pa')} Pa"]
        if l.get("atmo_opacity"):
            lines.append(f"- Opacity class: {l['atmo_opacity']}; UV index class: {l.get('uv_index')}")
        lines.append(f"- Not available from this feed: {'; '.join(r['unavailable'])}")
        if r.get("nearest_station_check"):
            n = r["nearest_station_check"]
            lines.append(f"\nStation is {n['distance_km']} km from {origin['name']}: {n['representativeness']}.")
        lines.append(f"\n**Radiation (published historical average, MSL RAD):** {rad['surface_gcr_dose_equivalent_mSv_per_day']['value']} ± "
                     f"{rad['surface_gcr_dose_equivalent_mSv_per_day']['uncertainty']} mSv/day GCR dose equivalent at Gale crater, {rad['period']}. {rad['limitations']}")
        return "\n".join(lines)

    # --- science mission around an origin
    science_q = _has(text, "research", "geolog", "science", "scientific", "interesting", "target", "explor", "sample", "mineral", "clay", "delta", "discover")
    if science_q and (len(places) < 2 or wants_here):
        if not origin:
            return ("I need a starting point. Set your habitat on the map (Mars Explorer → click a point → *Set as habitat*), "
                    "or name a place, e.g. *\"find a research target within 5 km of the Perseverance landing site\"*.")
        radius = _radius_km(text, 5.0)
        kw = next((k for k in ("delta", "clay", "carbonate", "sulfate", "channel", "igneous", "biosignature") if k in text.lower()), None)
        ft = box.run("find_science_targets", {"lon": origin["lon"], "lat": origin["lat"], "radius_km": radius, **({"query": kw} if kw else {})})
        if "error" in ft:
            return f"Target search failed: {ft['error']}"
        targets = [t for t in ft["targets"] if (t["distance_m"] or 0) > 40]
        if not targets:
            return (f"No science targets were found within {radius:g} km of {origin['name']} ({_fmt_pt(origin)}) in the MARS-X catalogue "
                    "(curated sites, rover waypoints, CRISM/OMEGA detections, named features). Try a larger radius.")
        pr = _priority(text)
        best, best_res, tried = None, None, []
        for t in targets[:3]:
            res = box.run("calculate_route", {"start_lon": origin["lon"], "start_lat": origin["lat"], "goal_lon": t["lon"], "goal_lat": t["lat"], "priority": pr})
            if "error" in res or not res["candidates"]:
                tried.append((t, None))
                continue
            rec = (res.get("recommendation") or {}).get("profile")
            c = next((c for c in res["candidates"] if c["profile"] == rec), res["candidates"][0])
            ok = bool(res["return_route"]) and (c.get("return_feasibility") or {}).get("feasible", False)
            hz = c["hazard_exposure"]["caution"] + c["hazard_exposure"]["high"]
            value = t["score"] - 40 * hz - (0 if ok else 50)
            tried.append((t, value))
            if ok and (best is None or value > best[1]):
                best, best_res = (t, value), res
        if best is None:
            return ("I found targets but could not produce a round trip with a feasible return to any of the top candidates:\n"
                    + "\n".join(f"- {t['name']} ({t['distance_m'] / 1000:.2f} km away)" for t, _ in tried)
                    + "\nNone is recommended. Try relaxing the slope limit in Mission Planner or choosing a nearer target.")
        t = best[0]
        if box.actions and best_res:   # make the chosen plan the last one drawn
            box.actions.append({"type": "show_plan", "plan_id": best_res["plan_id"], "plan": PLAN_STORE[best_res["plan_id"]]})
        box.run("compare_routes", {"plan_id": best_res["plan_id"]})
        box.run("generate_return_route", {"plan_id": best_res["plan_id"]})
        sc = t["score_components"]
        lines = [f"**Recommendation: {t['name']}** - {t['category']}, {t['distance_m'] / 1000:.2f} km from {origin['name']} ({_fmt_pt(origin)}).",
                 "", f"**Why it is interesting:** {t['summary']}",
                 f"- Observed evidence: {t['evidence']}"]
        if t.get("hypothesis"):
            lines.append(f"- Hypothesis (not established): {t['hypothesis']}")
        lines.append(f"- Target score {t['score']}/100 (relevance {sc['relevance']}, mineralogy {sc['mineralogy']}, geology {sc['geology']}, "
                     f"accessibility {sc['accessibility']}, data confidence {sc['confidence']}). Coordinates: {t['coordinate_source']}.")
        lines.append("")
        lines += _plan_section(best_res)
        others = [x for x, _ in tried if x is not t]
        if others:
            lines.append("\nAlso evaluated: " + "; ".join(f"{o['name']} ({o['distance_m'] / 1000:.2f} km, score {o['score']})" for o in others) + ".")
        lines.append(f"\n_{ft['disclaimer']}_")
        return "\n".join(lines)

    # --- point-to-point route
    if _has(text, "route", "path", "drive", "travel", "traverse", "get to", "go to", "from") and (len(places) >= 2 or (len(places) == 1 and habitat) or (ctx.get("start") and ctx.get("goal"))):
        if len(places) >= 2:
            a, b = places[0], places[1]
        elif len(places) == 1:
            a, b = {"name": "your habitat", **habitat}, places[0]
        else:
            a, b = {"name": "planner start", **ctx["start"]}, {"name": "planner destination", **ctx["goal"]}
        res = box.run("calculate_route", {"start_lon": a["lon"], "start_lat": a["lat"], "goal_lon": b["lon"], "goal_lat": b["lat"], "priority": _priority(text)})
        if "error" in res:
            return (f"The route planner could not plan from {a['name']} to {b['name']} "
                    f"({haversine_m(a['lon'], a['lat'], b['lon'], b['lat']) / 1000:.0f} km straight line): {res['error']}")
        return "\n".join([f"**Route from {a['name']} to {b['name']}** ({res['straight_line_m'] / 1000:.2f} km straight line)", ""] + _plan_section(res))

    # --- return on active plan
    if _has(text, "return", "way back", "get back") and plan_id:
        r = box.run("generate_return_route", {"plan_id": plan_id, "profile": ctx.get("selected_profile")})
        if "error" in r:
            return r["error"]
        rr, rt = r["return_route"], r["round_trip"] or {}
        return (f"**Return route for plan `{plan_id}`** (highlighted on the map): {rr['distance_m'] / 1000:.2f} km, mean slope {rr['mean_slope_deg']}°, "
                f"steepest cell {rr['max_cell_slope_deg']}°, ~{rr['energy_wh_derived'] / 1000:.1f} kWh (derived).\n\n{r['description']}\n\n"
                f"Round trip with the **{r['for_outbound_profile']}** outbound: {rt.get('round_trip_distance_m', 0) / 1000:.2f} km, "
                f"{rt.get('round_trip_energy_wh_with_margin', 0) / 1000:.1f} kWh incl. margin - {rt.get('reason')}. Confidence: {rr['confidence']['level']}.")

    # --- hazards / terrain at a place
    if _has(text, "hazard", "slope", "terrain", "rough", "steep", "safe") and origin:
        r = box.run("get_hazard_assessment", {"lon": origin["lon"], "lat": origin["lat"], "radius_km": _radius_km(text, 5.0)})
        if "error" in r:
            return f"Terrain analysis failed: {r['error']}"
        hf, q = r["hazard_fraction"], r["quality_fraction"]
        return "\n".join([
            f"**Terrain assessment around {origin['name']}** ({_fmt_pt(origin)}), from {r['dem']['name']} at {r['dem']['effective_resolution_m']} m cells (overlay shown on the map):",
            f"- Elevation {r['elevation_m']['min']} to {r['elevation_m']['max']} m; slope mean {r['slope_deg']['mean']}°, 95th percentile {r['slope_deg']['p95']}°, max {r['slope_deg']['max']}°",
            f"- Inferred hazard classes by area: nominal {hf['nominal']:.0%}, caution {hf['caution']:.0%}, high {hf['high']:.0%}, impassable {hf['impassable']:.0%}, no data {hf['unknown (no elevation data)']:.0%}",
            f"- DEM quality: measured {q['measured']:.0%}, interpolated {q['interpolated between measurements']:.0%}, no data {q['no data']:.0%}",
            f"\n_{r['hazard_basis']}_ {r['dem']['limitations']}"])

    # --- datasets / methods
    if _has(text, "dataset", "data source", "resolution", "instrument", "mola", "crism", "hirise", "ctx", "themis", "rems", "meda", "rad", "provenance", "how do you", "how does"):
        key = next((k for k in ("mola", "crism", "hirise", "ctx", "themis", "rems", "meda", "rad", "tes") if re.search(rf"\b{k}\b", text, re.I)), "")
        r = box.run("get_dataset_metadata", {"query": key})
        kb = box.run("search_knowledge_base", {"query": text})
        lines = []
        for d in r.get("datasets", [])[:3]:
            lines += [f"**{d['name']}** - {d['mission']} / {d['instrument']}", f"- Source: {d['source']} ({d['source_url']})",
                      f"- Observed: {d['observation_time']}; coverage: {d['coverage']}; resolution: {d['resolution']}",
                      f"- Processing: {d['processing']}", f"- Limitations: {d['limitations']}", ""]
        if not lines:
            for p in kb.get("passages", [])[:2]:
                lines += [f"**{p['title']}** ({p['source']})", p["passage"], ""]
        return "\n".join(lines) if lines else "Nothing in the MARS-X knowledge base matches that. Open **Data Explorer** for the full dataset catalogue."

    # --- location info
    if origin and origin.get("name") != "your habitat" or (origin and _has(text, "elevation", "where", "what is", "tell me", "info")):
        r = box.run("get_location_info", {"lon": origin["lon"], "lat": origin["lat"]})
        e = r["elevation"]
        lines = [f"**{origin['name']}** - {_fmt_pt(origin)}",
                 (f"- Elevation {e['value_m']} m ({e['datum']}), {e['quality']}, from {e['dataset']} at {e['resolution_m']} m/px" if e.get("value_m") is not None
                  else f"- Elevation unavailable: {e.get('unavailable', 'no data')}")]
        if r["nearest_named_features"]:
            lines.append("- Nearest named features: " + ", ".join(f"{f['name']} ({f['type']}, {f['distance_km']} km)" for f in r["nearest_named_features"][:4]))
        h = r["hydrous_mineral_detections_within_50km"]
        lines.append(f"- CRISM/OMEGA hydrous mineral detections within 50 km: {h['count']}" + (f" (nearest {h['nearest_km']} km)" if h["count"] else ""))
        for rv in r["rovers_nearby"]:
            lines.append(f"- {rv['rover']} is {rv['distance_km']} km away (latest sol {rv['latest_sol']} in the snapshot)")
        if _has(text, "life", "alive", "biosignature", "fossil", "organism", "microb"):
            lines.insert(0, "**MARS-X holds no evidence of past or present life at this or any location.** No mission has detected "
                            "life on Mars; the strongest claims in the literature are *potential* biosignatures that also have "
                            "non-biological explanations and need returned samples to test.\n")
        kb = box.run("search_knowledge_base", {"query": origin["name"]})
        tp = next((p for p in kb.get("passages", []) if p["id"].startswith("target:") and p["score"] > 2), None)
        if tp:
            lines += ["", f"**Science context** ({tp['source']}):", tp["passage"]]
        return "\n".join(lines)

    kb = box.run("search_knowledge_base", {"query": text})
    if kb.get("passages") and kb["passages"][0]["score"] > 1.5:
        p = kb["passages"][0]
        return f"**{p['title']}** ({p['source']})\n\n{p['passage']}"
    return ("I plan missions using the MARS-X backend tools. Try:\n"
            "- *Find an interesting geological research location within 2 km of my habitat. Prioritize safe terrain and make sure I can return.*\n"
            "- *Plan a route from the Perseverance landing site to the delta front.*\n"
            "- *What are the hazards within 10 km of Gale crater?*\n"
            "- *What is the weather at Jezero?*  ·  *Simulate a dust storm on this route.*  ·  *How accurate is the MOLA data?*")
