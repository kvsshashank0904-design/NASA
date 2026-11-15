"""Scientific discovery engine: target search and transparent scoring."""
from __future__ import annotations

import math
from functools import lru_cache

import numpy as np

from ..mars import haversine_m, norm_lon
from . import catalog

# Geological-context prior per IAU feature type (heuristic, documented in the API response).
FEATURE_PRIORS = {
    "Vallis, valles": (0.75, "Valley: possible fluvial or outflow channel"),
    "Chaos, chaoses": (0.65, "Chaotic terrain: possible groundwater release / collapse"),
    "Chasma, chasmata": (0.65, "Canyon: exposes deep stratigraphy"),
    "Fossa, fossae": (0.55, "Trough/graben: exposes bedrock, possible volcanic or hydrothermal pathways"),
    "Crater, craters": (0.45, "Impact crater: natural excavation of subsurface material, possible paleolake basin"),
    "Mensa, mensae": (0.5, "Mesa: layered-deposit remnant"),
    "Mons, montes": (0.5, "Mountain/volcano"), "Tholus, tholi": (0.5, "Small volcanic dome"),
    "Patera, paterae": (0.55, "Volcanic caldera; possible past hydrothermal activity"),
    "Cavus, cavi": (0.45, "Steep-sided depression"), "Labyrinthus, labyrinthi": (0.6, "Intersecting valley complex"),
    "Planum, plana": (0.35, "Plateau"), "Planitia, planitiae": (0.3, "Low plain"), "Terra, terrae": (0.3, "Highland region"),
    "Dorsum, dorsa": (0.4, "Ridge"), "Rupes, rupes": (0.45, "Scarp"), "Scopulus, scopuli": (0.4, "Lobate scarp"),
    "Collis, colles": (0.4, "Small hills"), "Catena, catenae": (0.45, "Crater chain"), "Sulcus, sulci": (0.4, "Subparallel furrows"),
    "Unda, undae": (0.4, "Dune field"), "Lingula, lingulae": (0.4, "Lobate plateau extension"),
    "Labes, labes": (0.5, "Landslide"), "Fluctus, fluctus": (0.45, "Flow terrain"), "Palus, paludes": (0.35, "Small plain"),
}
WEIGHTS = {"relevance": 0.30, "mineralogy": 0.20, "geology": 0.20, "accessibility": 0.20, "confidence": 0.10}
MINERAL_RADIUS_M = 25_000.0


@lru_cache
def _hydrous_arrays():
    d = catalog.hydrous()["detections"]
    return (np.radians([p["lon"] for p in d]), np.radians([p["lat"] for p in d]), d)


def hydrous_near(lon: float, lat: float, radius_m: float) -> list[dict]:
    lons, lats, d = _hydrous_arrays()
    lo, la = math.radians(lon), math.radians(lat)
    a = np.sin((lats - la) / 2) ** 2 + np.cos(la) * np.cos(lats) * np.sin((lons - lo) / 2) ** 2
    dist = 2 * 3_396_190.0 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
    idx = np.nonzero(dist <= radius_m)[0]
    return [dict(d[i], distance_m=round(float(dist[i]), 1)) for i in idx[np.argsort(dist[idx])]]


def _mineral_score(lon: float, lat: float) -> tuple[float, dict]:
    near = hydrous_near(lon, lat, MINERAL_RADIUS_M)
    n = len(near)
    by = {}
    for p in near:
        by[p["instrument"]] = by.get(p["instrument"], 0) + 1
    return min(1.0, n / 5.0), {"detections_within_25km": n, "by_instrument": by,
                               "nearest_m": near[0]["distance_m"] if near else None}


def _score(components: dict) -> float:
    return round(100 * sum(WEIGHTS[k] * components[k] for k in WEIGHTS), 1)


def find_targets(lon: float | None = None, lat: float | None = None, radius_km: float | None = None,
                 include_gazetteer: bool = True, include_rover_sites: bool = True, limit: int = 25,
                 query: str | None = None, category: str | None = None) -> dict:
    """Rank science targets. With an origin + radius, accessibility is distance-based (run the route planner
    for terrain-based accessibility)."""
    origin = (norm_lon(lon), lat) if lon is not None and lat is not None else None
    radius_m = radius_km * 1000.0 if radius_km else None
    cands = []

    def consider(t: dict):
        d = haversine_m(origin[0], origin[1], t["lon"], t["lat"]) if origin else None
        if radius_m is not None and d is not None and d > radius_m:
            return
        if query and query.lower() not in (t["name"] + " " + t["category"] + " " + t.get("summary", "")).lower():
            return
        if category and category.lower() not in t["category"].lower():
            return
        m, mdetail = _mineral_score(t["lon"], t["lat"])
        if t.get("minerals"):
            m = max(m, 0.6)   # minerals reported in the cited literature for this target
        acc = 0.5 if d is None else (max(0.0, 1 - d / radius_m) if radius_m else max(0.0, 1 - d / 500_000.0))
        comp = {"relevance": t["scores"]["relevance"], "mineralogy": round(m, 2), "geology": t["scores"]["geology"],
                "accessibility": round(acc, 2), "confidence": t["scores"]["confidence"]}
        out = {k: t.get(k) for k in ("id", "name", "category", "lon", "lat", "summary", "evidence", "hypothesis",
                                     "minerals", "coordinate_source", "datasets", "reference_ids", "kind")}
        out.update(distance_m=None if d is None else round(d, 1), score=_score(comp), score_components=comp,
                   mineral_context=mdetail, why=t.get("why") or t.get("summary"))
        cands.append(out)

    for t in catalog.resolve_targets():
        consider(dict(t, kind="curated", reference_ids=t.get("refs", [])))

    if include_rover_sites and origin and radius_m and radius_m <= 50_000:
        for key, r in catalog.rovers()["rovers"].items():
            wps = [w for w in r["waypoints"] if haversine_m(origin[0], origin[1], w["lon"], w["lat"]) <= radius_m]
            # thin to at most 12 evenly spaced waypoints so the list stays useful
            for w in wps[::max(1, len(wps) // 12)]:
                consider(dict(id=f"{key}-sol-{w['sol']}", name=f"{r['name']} waypoint, sol {w['sol']}", category="Rover observation",
                              lon=w["lon"], lat=w["lat"], kind="rover_waypoint",
                              summary=f"Ground-truth site: the rover ended a drive here on sol {w['sol']} (elevation {w['elev_m']} m). "
                                      "Rover images and instrument data exist for this location in the PDS.",
                              evidence="Rover localisation (NASA/JPL).", hypothesis=None, minerals=[],
                              scores=dict(relevance=0.55, geology=0.5, confidence=1.0), coordinate_source=r["source"],
                              datasets=["m20_localization" if key == "perseverance" else "msl_localization"], reference_ids=[]))

    if include_gazetteer and origin and radius_m:
        for f in catalog.nomenclature()["features"]:
            prior = FEATURE_PRIORS.get(f["feature_type"])
            if prior is None:
                continue
            consider(dict(id=f"iau-{f['name'].lower().replace(' ', '-')}", name=f["name"], category=f["feature_type"], lon=f["lon"], lat=f["lat"],
                          kind="gazetteer", summary=f"{prior[1]} (IAU feature type '{f['feature_type']}').",
                          evidence="Named surface feature; morphology only.", hypothesis=prior[1] + " - an interpretation of feature type, not a site-specific finding.",
                          minerals=[], scores=dict(relevance=prior[0] * 0.8, geology=prior[0], confidence=0.3),
                          coordinate_source="IAU gazetteer centre point", datasets=["iau_nomenclature"], reference_ids=[]))

    if origin and radius_m:
        for p in hydrous_near(origin[0], origin[1], radius_m)[:40]:
            consider(dict(id=f"hyd-{p['instrument'].lower()}-{p['lon']:.3f}-{p['lat']:.3f}", name=f"{p['instrument']} hydrous mineral detection",
                          category="Mineralogical target", lon=p["lon"], lat=p["lat"], kind="mineral_detection",
                          summary=f"Hydrated mineral signature detected from orbit by {p['instrument']} ({p['mission']}).",
                          evidence="Near-infrared hydration absorption bands (Carter et al., 2013).",
                          hypothesis="Indicates past water-rock interaction; the specific mineral is not given in the distributed dataset.",
                          minerals=["hydrated mineral (class unspecified)"], scores=dict(relevance=0.7, geology=0.6, confidence=0.7),
                          coordinate_source="Carter et al. (2013) detection point via NASA Mars Trek", datasets=["hydrous_minerals"], reference_ids=["carter2013"]))

    cands.sort(key=lambda c: -c["score"])
    return {
        "origin": {"lon": origin[0], "lat": origin[1]} if origin else None, "radius_km": radius_km,
        "count": len(cands), "targets": cands[:limit],
        "scoring": {"weights": WEIGHTS,
                    "components": {
                        "relevance": "Literature-based prior for curated targets; feature-type prior otherwise.",
                        "mineralogy": "Count of CRISM/OMEGA hydrous detections within 25 km (saturates at 5); floor of 0.6 when minerals are reported in the cited literature.",
                        "geology": "Geological-context prior (curated) or IAU feature-type prior.",
                        "accessibility": "1 - distance/radius from the origin. Distance only - plan a route for terrain accessibility.",
                        "confidence": "1.0 in-situ rover measurement; 0.7-0.9 orbital spectroscopy; 0.3 named feature only."},
                    "note": "Scores rank exploration interest. They are heuristics, not measurements."},
        "disclaimer": "No target here constitutes evidence of past or present life. 'Hypothesis' fields are interpretations.",
    }


def search_locations(db, q: str, limit: int = 20) -> list[dict]:
    from sqlalchemy import select
    from ..models import Location, ScienceTarget
    q = q.strip()
    if not q:
        return []
    like = f"%{q}%"
    out = []
    rows = db.execute(select(Location).where(Location.name.ilike(like)).limit(limit * 3)).scalars().all()
    rows.sort(key=lambda r: (not r.name.lower().startswith(q.lower()), r.kind != "landing_site", len(r.name)))
    for r in rows[:limit]:
        out.append({"name": r.name, "type": r.feature_type, "kind": r.kind, "lon": r.lon, "lat": r.lat, "source": r.source,
                    "description": r.description})
    for t in db.execute(select(ScienceTarget).where(ScienceTarget.name.ilike(like)).limit(8)).scalars().all():
        out.insert(0, {"name": t.name, "type": t.category, "kind": "science_target", "lon": t.lon, "lat": t.lat,
                       "source": t.coordinate_source, "description": t.summary})
    return out[:limit]


def location_info(db, lon: float, lat: float) -> dict:
    """Everything MARS-X knows about a point, each item with provenance."""
    from sqlalchemy import select
    from ..models import Location
    from .dem import DemUnavailable, sample_elevation
    from .terrain import QUALITY_LABELS
    lon = norm_lon(lon)
    out: dict = {"lon": lon, "lat": lat, "crs": "IAU 2000 Mars sphere (r = 3,396,190 m), planetocentric latitude, east-positive longitude"}
    try:
        e = sample_elevation(lon, lat)
        out["elevation"] = {"value_m": e["elevation_m"], "datum": e["source"]["vertical_datum"], "quality": QUALITY_LABELS[e["quality"]],
                            "dataset": e["source"]["name"], "resolution_m": e["source"]["resolution_m"],
                            "limitations": e["source"]["limitations"]}
    except DemUnavailable as ex:
        out["elevation"] = {"value_m": None, "unavailable": str(ex)}
    box = 3.0
    rows = db.execute(select(Location).where(Location.lat.between(lat - box, lat + box))).scalars().all()
    near = sorted(((haversine_m(lon, lat, r.lon, r.lat), r) for r in rows), key=lambda x: x[0])[:5]
    out["nearest_named_features"] = [{"name": r.name, "type": r.feature_type, "distance_km": round(d / 1000, 1), "lon": r.lon, "lat": r.lat}
                                     for d, r in near if d < 300_000]
    hyd = hydrous_near(lon, lat, 50_000)
    out["hydrous_mineral_detections_within_50km"] = {"count": len(hyd), "nearest_km": round(hyd[0]["distance_m"] / 1000, 1) if hyd else None,
                                                     "dataset": "Carter et al. (2013) CRISM/OMEGA"}
    out["rovers_nearby"] = []
    for key, r in catalog.rovers()["rovers"].items():
        w = r["waypoints"][-1]
        d = haversine_m(lon, lat, w["lon"], w["lat"])
        if d < 100_000:
            out["rovers_nearby"].append({"rover": r["name"], "distance_km": round(d / 1000, 2), "latest_sol": w["sol"]})
    covers = []
    for lyr in catalog.trek_layers()["layers"]:
        b = lyr["bbox"]
        if b[0] <= lon <= b[2] and b[1] <= lat <= b[3] and (b[2] - b[0]) < 300:
            covers.append({"id": lyr["id"], "title": lyr["title"]})
    out["regional_imagery_available"] = covers
    return out
