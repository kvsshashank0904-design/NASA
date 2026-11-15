"""Guided surface missions: pre-defined, multi-stop excursions an astronaut can load and follow.

Stop coordinates are never typed by hand: each is the NASA/JPL localisation of a rover on a given sol,
so every stop is a place where ground-truth images and measurements exist. Routes between stops are
computed by the route planner on 1-2 m HiRISE terrain; tasks are mission-design choices, not findings.
"""
from __future__ import annotations

import json
import logging
import math
import threading

from ..config import settings
from ..mars import haversine_m
from . import catalog, environment, routing
from .dem import DemUnavailable

log = logging.getLogger("marsx.guided")

MISSIONS: dict[str, dict] = {
    "boxwork-marswalk": {
        "title": "Boxwork Marswalk",
        "site": "Mount Sharp · Gale crater",
        "mode": "eva",
        "crew": "2 crew on foot",
        "tagline": "Walk the boxwork ridges Curiosity studied in 2025",
        "science_goal": "How did groundwater cement the boxwork ridges?",
        "context": "Boxwork: a lattice of low ridges with sandy hollows between them, on the sulfate-bearing slopes of Mount Sharp.",
        "hypothesis": "Ridges may be fractures cemented by minerals from groundwater, left standing as softer rock eroded. Unconfirmed.",
        "rover": "curiosity",
        "habitat": {"name": "Habitat · boxwork approach", "sol": 4539},
        "stops": [
            {"id": "ridge-edge", "name": "Ridge field edge", "sol": 4600, "dwell_min": 20,
             "tasks": ["Panorama of ridge lattice", "Measure ridge height and spacing", "Regolith scoop from a hollow"]},
            {"id": "ridge-hollow", "name": "Ridge and hollow pair", "sol": 4687, "dwell_min": 40,
             "tasks": ["Core the ridge top", "Core the hollow floor", "Close-up of cemented fracture fill"]},
            {"id": "upper-lattice", "name": "Upper lattice", "sol": 4893, "dwell_min": 25,
             "tasks": ["Sample upslope ridge", "Stereo images along ridge strike", "Radiation and weather reading"]},
        ],
        "max_slope_deg": 20.0, "safety_margin": 0.25, "endurance_h": 8.0,
        "layers": ["curiosity_hirise_mosaic", "Gale_CTX_BlockAdj_dd", "mx_hazard", "mx_rovers"],
        "data_types": [["Optical", "HiRISE 25 cm"], ["Topographic", "HiRISE DEM 1 m"], ["Thermal", "THEMIS IR"],
                       ["Atmospheric", "REMS"], ["Radiation", "RAD"], ["Surface images", "Curiosity"]],
        "station": "rems",
    },
    "jezero-delta-sortie": {
        "title": "Delta Front Sortie",
        "site": "Jezero crater · western delta",
        "mode": "rover",
        "crew": "2 crew · pressurised rover",
        "tagline": "Drive from the crater floor to the ancient river delta",
        "science_goal": "What do lake-bed sediments at the delta base record?",
        "context": "A 3.5-billion-year-old river delta: igneous crater floor, then fine lake sediments at the delta front.",
        "hypothesis": "Fine-grained delta sediments are favourable for preserving organic matter. Organics are not evidence of life.",
        "rover": "perseverance",
        "habitat": {"name": "Habitat · Octavia E. Butler Landing", "sol": 13},
        "stops": [
            {"id": "seitah", "name": "Séítah olivine outcrop", "sol": 248, "dwell_min": 30,
             "tasks": ["Sample olivine-rich bedrock", "Image carbonate alteration rims", "Check dune trafficability"]},
            {"id": "three-forks", "name": "Three Forks depot", "sol": 686, "dwell_min": 20,
             "tasks": ["Inspect cached sample tubes", "Photograph depot layout", "Dust-cover assessment"]},
            {"id": "delta-front", "name": "Delta front strata", "sol": 502, "dwell_min": 45,
             "tasks": ["Core fine-grained mudstone", "Log sediment layering", "Sulfate vein close-ups"]},
        ],
        "max_slope_deg": 25.0, "safety_margin": 0.2, "battery_wh": 40000.0,
        "layers": ["JEZ_ctx_B_soc_008_orthoMosaic_6m_Eqc_latTs0_lon0", "JEZ_hirise_soc_006_orthoMosaic_25cm_Eqc_latTs0_lon0_first_dd", "mx_hazard", "mx_rovers", "mx_minerals"],
        "data_types": [["Optical", "HiRISE 25 cm"], ["Topographic", "HiRISE DTM 1 m"], ["Spectral", "CRISM / OMEGA"],
                       ["Atmospheric", "MEDA"], ["Radiation", "RAD"], ["Surface images", "Perseverance"]],
        "station": "meda",
    },
}

_lock = threading.Lock()
_mem: dict[str, dict] = {}


def _wp(rover: str, sol: int) -> dict:
    wps = catalog.rovers()["rovers"][rover]["waypoints"]
    return next((w for w in reversed(wps) if w["sol"] <= sol), wps[0])


def _point(m: dict, name: str, sol: int, **extra) -> dict:
    w = _wp(m["rover"], sol)
    rv = catalog.rovers()["rovers"][m["rover"]]["name"].split(" (")[0]
    return {"name": name, "lon": w["lon"], "lat": w["lat"], "elev_m": w["elev_m"], "sol": w["sol"],
            "coordinate_source": f"{rv} localisation, sol {w['sol']} (NASA/JPL)", **extra}


def _bearing(a: list[float], b: list[float]) -> float:
    p1, p2 = math.radians(a[1]), math.radians(b[1])
    dl = math.radians(b[0] - a[0])
    return (math.degrees(math.atan2(math.sin(dl) * math.cos(p2), math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl))) + 360) % 360


def vehicle_for(m: dict) -> routing.Vehicle:
    if m["mode"] == "eva":
        return routing.Vehicle.eva(endurance_h=m["endurance_h"])
    return routing.Vehicle(battery_wh=m.get("battery_wh"))


def summary(mid: str) -> dict:
    m = MISSIONS[mid]
    hab = _point(m, m["habitat"]["name"], m["habitat"]["sol"])
    stops = [_point(m, s["name"], s["sol"], id=s["id"], dwell_min=s["dwell_min"], tasks=s["tasks"]) for s in m["stops"]]
    pts = [hab] + stops + [hab]
    straight = sum(haversine_m(a["lon"], a["lat"], b["lon"], b["lat"]) for a, b in zip(pts, pts[1:]))
    return {"id": mid, **{k: m[k] for k in ("title", "site", "mode", "crew", "tagline", "science_goal", "context", "hypothesis",
                                             "rover", "layers", "data_types")},
            "habitat": hab, "stops": stops, "straight_line_total_m": round(straight, 1), "planned": mid in _mem or _path(mid).exists()}


def _path(mid: str):
    return settings.cache_dir / f"guided_{mid}.json"


def plan(mid: str, refresh: bool = False) -> dict:
    """Leg-by-leg plan (habitat -> stops -> habitat). Cached on disk; recomputed on refresh."""
    if mid not in MISSIONS:
        raise KeyError(mid)
    if not refresh:
        if mid in _mem:
            return _mem[mid]
        if _path(mid).exists():
            _mem[mid] = json.loads(_path(mid).read_text(encoding="utf-8"))
            return _mem[mid]
    with _lock:
        m = MISSIONS[mid]
        info = summary(mid)
        veh = vehicle_for(m)
        pts = [info["habitat"]] + info["stops"] + [info["habitat"]]
        legs, warnings = [], []
        for i, (a, b) in enumerate(zip(pts, pts[1:])):
            is_return = i == len(pts) - 2
            try:
                p = routing.plan_routes((a["lon"], a["lat"]), (b["lon"], b["lat"]), max_slope_deg=m["max_slope_deg"],
                                        caution_deg=min(10.0, m["max_slope_deg"] * 0.5), high_deg=min(20.0, m["max_slope_deg"] * 0.8),
                                        safety_margin=m["safety_margin"], vehicle=veh, include_return=False, profiles=["safest"])
            except (routing.RouteError, DemUnavailable) as e:
                raise RuntimeError(f"leg {i + 1} ({a['name']} -> {b['name']}) could not be planned: {e}") from e
            if not p["candidates"]:
                raise RuntimeError(f"leg {i + 1} ({a['name']} -> {b['name']}) has no traversable route under {m['max_slope_deg']} deg")
            c = p["candidates"][0]
            coords = c["geometry"]["coordinates"]
            for w in p["warnings"]:
                if w not in warnings:
                    warnings.append(w)
            legs.append({
                "index": i, "from": a["name"], "to": b["name"], "kind": "return" if is_return else "outbound",
                "stop_id": None if is_return else b.get("id"),
                "geometry": c["geometry"], "distance_m": c["distance_m"], "duration_h": c["duration_h"]["value"],
                "energy_wh": c["energy"]["total_wh"], "ascent_m": c["ascent_m"], "descent_m": c["descent_m"],
                "mean_slope_deg": c["mean_slope_deg"], "max_cell_slope_deg": c["max_cell_slope_deg"],
                "hazard_exposure": c["hazard_exposure"], "difficulty": c["difficulty_index"]["value"],
                "confidence": c["confidence"], "elevation_profile": c["elevation_profile"],
                "initial_bearing_deg": round(_bearing(coords[0], coords[min(len(coords) - 1, 5)]), 0),
                "dem": {k: p["dem"][k] for k in ("id", "name", "effective_resolution_m", "limitations")},
            })
        move_h = sum(leg["duration_h"] for leg in legs)
        dwell_h = sum(s["dwell_min"] for s in info["stops"]) / 60.0
        total_h = move_h + dwell_h
        energy = sum(leg["energy_wh"] for leg in legs)
        if m["mode"] == "eva":
            energy += 250.0 * dwell_h                      # metabolic baseline while working at a stop (assumption)
            limit = m["endurance_h"]
            need = total_h * (1 + m["safety_margin"])
            feas = {"feasible": need <= limit, "basis": "life-support time", "need": round(need, 2), "limit": limit, "unit": "h"}
        else:
            energy += veh.hotel_power_w * dwell_h
            limit = m["battery_wh"]
            need = energy * (1 + m["safety_margin"])
            feas = {"feasible": need <= limit, "basis": "battery energy", "need": round(need, 0), "limit": limit, "unit": "Wh"}
        rad = environment.RAD["surface_gcr_dose_equivalent_mSv_per_day"]
        out = {
            **info, "planned": True, "legs": legs, "warnings": warnings,
            "totals": {"distance_m": round(sum(leg["distance_m"] for leg in legs), 1), "moving_h": round(move_h, 3), "dwell_h": round(dwell_h, 3),
                       "duration_h": round(total_h, 3), "energy_wh": round(energy, 1), "ascent_m": round(sum(leg["ascent_m"] for leg in legs), 1),
                       "max_cell_slope_deg": max(leg["max_cell_slope_deg"] for leg in legs),
                       "energy_kind": "metabolic, derived" if m["mode"] == "eva" else "battery, derived"},
            "feasibility": {**feas, "safety_margin": m["safety_margin"]},
            "radiation": {"kind": "derived_estimate", "dose_mSv": round(rad["value"] * total_h / 24.0, 3),
                          "basis": f"{rad['value']} mSv/day x {total_h:.1f} h (MSL RAD historical average, Gale crater)"},
            "constraints": {"max_slope_deg": m["max_slope_deg"], "safety_margin": m["safety_margin"]},
            "vehicle": veh.assumptions(), "station": m["station"],
            "dem": legs[0]["dem"], "confidence": legs[0]["confidence"]["level"],
        }
        _mem[mid] = out
        try:
            _path(mid).write_text(json.dumps(out), encoding="utf-8")
        except OSError:
            log.warning("could not cache guided plan %s", mid)
        return out


def abort_route(mid: str, lon: float, lat: float) -> dict:
    """Direct safest route from the crew's current position back to the habitat."""
    m = MISSIONS[mid]
    hab = summary(mid)["habitat"]
    p = routing.plan_routes((lon, lat), (hab["lon"], hab["lat"]), max_slope_deg=m["max_slope_deg"], safety_margin=m["safety_margin"],
                            vehicle=vehicle_for(m), include_return=False, profiles=["safest"])
    if not p["candidates"]:
        raise routing.RouteError("no traversable route back to the habitat from this position")
    c = p["candidates"][0]
    return {"geometry": c["geometry"], "distance_m": c["distance_m"], "duration_h": c["duration_h"]["value"], "energy_wh": c["energy"]["total_wh"],
            "max_cell_slope_deg": c["max_cell_slope_deg"], "hazard_exposure": c["hazard_exposure"], "elevation_profile": c["elevation_profile"],
            "dem": p["dem"]["name"], "warnings": p["warnings"]}
