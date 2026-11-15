"""MARS-X REST API, mounted at /api/v1. Interactive docs at /docs."""
from __future__ import annotations

import logging
import math
from collections import OrderedDict

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import schemas
from .config import settings
from .db import get_db
from .mars import MARS_RADIUS_M, norm_lon
from .models import Dataset, HazardGeometry, Location, Mission, MissionLog, Route, RouteSegment, ScientificReference
from .services import ai_agent, ai_tools, catalog, dem, environment, guided, routing, science, simulation, terrain

log = logging.getLogger("marsx.api")
router = APIRouter(prefix="/api/v1")


def _dem_error(e: Exception) -> HTTPException:
    return HTTPException(503, detail={"error": "elevation_data_unavailable", "message": str(e)})


# ----------------------------------------------------------------------------- system

@router.get("/health", tags=["system"])
def health(db: Session = Depends(get_db)):
    n = db.scalar(select(func.count()).select_from(Location))
    return {"status": "ok", "database": {"dialect": db.bind.dialect.name, "locations": n},
            "ai": {"mode": "llm" if ai_agent.credential_available() and not settings.offline else "planner", "model": settings.ai_model},
            "offline": settings.offline, "cache": dem.cache_status(),
            "crs": {"body": "Mars", "radius_m": MARS_RADIUS_M, "latitude": "planetocentric", "longitude": "east-positive"}}


# ----------------------------------------------------------------------------- planet

@router.get("/planet/layers", tags=["planet"])
def planet_layers():
    return {"retrieved": catalog.trek_layers()["retrieved"], "layers": catalog.layers(),
            "tiling": {"scheme": "geographic", "level_zero_tiles": [2, 1], "crs": "EPSG:104905 (GCS Mars 2000 sphere)", "radius_m": MARS_RADIUS_M}}


@router.get("/planet/locations", tags=["planet"])
def planet_locations(q: str | None = Query(None, max_length=80), kind: str | None = None, feature_type: str | None = None,
                     limit: int = Query(25, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    if q:
        return {"query": q, "results": science.search_locations(db, q, limit)}
    stmt = select(Location)
    if kind:
        stmt = stmt.where(Location.kind == kind)
    if feature_type:
        stmt = stmt.where(Location.feature_type == feature_type)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(stmt.order_by(Location.name).offset(offset).limit(limit)).scalars().all()
    return {"total": total, "offset": offset, "limit": limit,
            "results": [{"name": r.name, "type": r.feature_type, "kind": r.kind, "lon": r.lon, "lat": r.lat, "description": r.description, "source": r.source} for r in rows]}


@router.get("/planet/location-info", tags=["planet"])
def planet_location_info(lon: float = Query(..., ge=-360, le=360), lat: float = Query(..., ge=-90, le=90), db: Session = Depends(get_db)):
    return science.location_info(db, lon, lat)


@router.get("/planet/observations", tags=["planet"])
def planet_observations(station: str = Query("rems", pattern="^(rems|meda)$"), limit: int = Query(60, ge=1, le=700)):
    return environment.observations(station, limit)


@router.get("/planet/rovers", tags=["planet"])
def planet_rovers():
    d = catalog.rovers()
    return {"retrieved": d["retrieved"], "rovers": {k: {**{x: v[x] for x in ("name", "source", "source_url", "latest_sol", "traverse")},
                                                          "latest": v["waypoints"][-1], "waypoint_count": len(v["waypoints"]),
                                                          "waypoints": v["waypoints"][::max(1, len(v["waypoints"]) // 150)]} for k, v in d["rovers"].items()}}


@router.get("/planet/labels", tags=["planet"])
def planet_labels():
    """Named features for map labels, tiered by feature type so large regions show first."""
    tiers = {"Planitia, planitiae": 1, "Terra, terrae": 1, "Mons, montes": 2, "Planum, plana": 2, "Chasma, chasmata": 2, "Vastitas, vastitates": 1,
             "Vallis, valles": 3, "Tholus, tholi": 3, "Patera, paterae": 3, "Fossa, fossae": 3, "Chaos, chaoses": 3, "Labyrinthus, labyrinthi": 2,
             "Crater, craters": 4}
    out = [[f["name"], round(f["lon"], 3), round(f["lat"], 3), tiers[f["feature_type"]]] for f in catalog.nomenclature()["features"] if f["feature_type"] in tiers]
    return {"source": catalog.nomenclature()["source"], "labels": out}


_pov_dir = settings.cache_dir / "pov"


@router.get("/planet/rover-images", tags=["planet"])
def planet_rover_images(rover: str = Query("perseverance", pattern="^(perseverance|curiosity)$"), limit: int = Query(8, ge=1, le=24),
                        sol: int | None = Query(None, ge=0, le=20000)):
    """Raw rover images from NASA: latest, or for one sol (point-of-view at a mission stop). Per-sol lists are cached."""
    import json as _json
    cache = _pov_dir / f"{rover}_{sol}.json" if sol is not None else None
    if cache is not None and cache.exists():
        d = _json.loads(cache.read_text(encoding="utf-8"))
        d["images"] = d["images"][:limit]
        return d
    if settings.offline:
        raise HTTPException(503, detail={"error": "offline", "message": "Rover raw images require a network link."})
    try:
        if sol is not None:
            with httpx.Client(timeout=25, follow_redirects=True, headers={"User-Agent": "mars-x/1.0"}) as c:
                if rover == "perseverance":
                    r = c.get("https://mars.nasa.gov/rss/api/", params={"feed": "raw_images", "category": "mars2020", "feedtype": "json", "num": 60, "page": 0,
                                                                         "order": "sol desc", "sol": sol, "search": "|NAVCAM_LEFT|MCZ_LEFT|MCZ_RIGHT"})
                    r.raise_for_status()
                    raw = [{"sol": i.get("sol"), "date": i.get("date_taken_utc"), "camera": (i.get("camera") or {}).get("instrument"), "title": i.get("title"),
                            "image": (i.get("image_files") or {}).get("medium") or (i.get("image_files") or {}).get("small"), "link": i.get("link"),
                            "thumb": (i.get("sample_type") or "").lower() == "thumbnail"} for i in r.json().get("images", [])]
                else:
                    r = c.get("https://mars.nasa.gov/api/v1/raw_image_items/", params={"order": "sol desc,instrument_sort asc,sample_type_sort asc", "per_page": 100, "page": 0,
                                                                                         "condition_1": "msl:mission", "condition_2": f"{sol}:sol:gte", "condition_3": f"{sol}:sol:lte"})
                    r.raise_for_status()
                    raw = [{"sol": i.get("sol"), "date": i.get("date_taken"), "camera": i.get("instrument"), "title": i.get("title") or i.get("imageid"),
                            "image": i.get("url"), "link": i.get("link") or i.get("url"),
                            "thumb": (i.get("extended") or {}).get("sample_type") == "thumbnail"} for i in r.json().get("items", [])]
            pref = ("MAST", "MCZ", "NAV")
            raw = [x for x in raw if x["image"] and not x["thumb"]]
            raw.sort(key=lambda x: next((n for n, p in enumerate(pref) if (x["camera"] or "").upper().startswith(p)), 9))
            seen, items = set(), []
            for x in raw:                                   # spread across cameras, drop near-duplicate frames
                key = (x["camera"], (x["image"] or "")[-28:-12])
                if key in seen:
                    continue
                seen.add(key)
                x.pop("thumb")
                items.append(x)
            d = {"rover": rover, "sol": sol, "source": "NASA/JPL-Caltech raw images (uncalibrated)", "images": items[:24]}
            if items:
                _pov_dir.mkdir(parents=True, exist_ok=True)
                cache.write_text(_json.dumps(d), encoding="utf-8")
            d["images"] = d["images"][:limit]
            return d
    except httpx.HTTPError as e:
        raise HTTPException(503, detail={"error": "nasa_feed_unavailable", "message": str(e)}) from e
    try:
        with httpx.Client(timeout=25, follow_redirects=True, headers={"User-Agent": "mars-x/1.0"}) as c:
            if rover == "perseverance":
                r = c.get("https://mars.nasa.gov/rss/api/", params={"feed": "raw_images", "category": "mars2020", "feedtype": "json", "num": limit, "page": 0, "order": "sol desc"})
                r.raise_for_status()
                items = [{"sol": i.get("sol"), "date": i.get("date_taken_utc"), "camera": (i.get("camera") or {}).get("instrument"),
                          "title": i.get("title"), "image": (i.get("image_files") or {}).get("medium") or (i.get("image_files") or {}).get("small"),
                          "link": i.get("link")} for i in r.json().get("images", [])]
            else:
                r = c.get("https://mars.nasa.gov/api/v1/raw_image_items/", params={"order": "sol desc", "per_page": limit, "page": 0, "condition_1": "msl:mission"})
                r.raise_for_status()
                items = [{"sol": i.get("sol"), "date": i.get("date_taken"), "camera": i.get("instrument"), "title": i.get("title") or i.get("imageid"),
                          "image": i.get("url"), "link": i.get("link") or i.get("url")} for i in r.json().get("items", [])]
    except httpx.HTTPError as e:
        raise HTTPException(503, detail={"error": "nasa_feed_unavailable", "message": str(e)}) from e
    return {"rover": rover, "source": "NASA/JPL-Caltech raw image feed (live, uncalibrated)", "images": items}


# ----------------------------------------------------------------------------- terrain / hazards

@router.get("/terrain/elevation", tags=["terrain"])
def terrain_elevation(lon: float = Query(..., ge=-360, le=360), lat: float = Query(..., ge=-90, le=90)):
    try:
        e = dem.sample_elevation(lon, lat)
    except dem.DemUnavailable as ex:
        raise _dem_error(ex) from ex
    return {"lon": norm_lon(lon), "lat": lat, "elevation_m": e["elevation_m"], "quality": terrain.QUALITY_LABELS[e["quality"]], "dem": e["source"]}


@router.get("/terrain/profile", tags=["terrain"])
def terrain_profile(start_lon: float = Query(..., ge=-360, le=360), start_lat: float = Query(..., ge=-90, le=90),
                    end_lon: float = Query(..., ge=-360, le=360), end_lat: float = Query(..., ge=-90, le=90),
                    samples: int = Query(200, ge=2, le=1000)):
    try:
        return terrain.terrain_profile(start_lon, start_lat, end_lon, end_lat, samples)
    except dem.DemUnavailable as ex:
        raise _dem_error(ex) from ex


@router.get("/terrain/tile/{level}/{x}/{y}", tags=["terrain"], responses={200: {"content": {"application/octet-stream": {}}}})
def terrain_tile(level: int, x: int, y: int, size: int = Query(33, ge=9, le=65)):
    """Heightmap tile for the 3D globe: size x size little-endian float32 metres, row 0 = north (geographic 2x1 tiling)."""
    if not (0 <= level <= 18 and 0 <= x < 2 * 2 ** level and 0 <= y < 2 ** level):
        raise HTTPException(422, detail={"error": "invalid_tile"})
    if not dem.mola16_ready() and settings.offline:
        raise HTTPException(503, detail={"error": "terrain_unavailable", "message": "global MOLA grid is not cached"})
    try:
        h = dem.terrain_tile(level, x, y, size)
    except dem.DemUnavailable as ex:
        raise _dem_error(ex) from ex
    return Response(h.astype("<f4").tobytes(), media_type="application/octet-stream", headers={"Cache-Control": "public, max-age=604800"})


_analysis_cache: "OrderedDict[tuple, dict]" = OrderedDict()


def _analysis(west, south, east, north, caution=10.0, high=20.0, mx=30.0) -> dict:
    key = (round(west, 4), round(south, 4), round(east, 4), round(north, 4), caution, high, mx)
    if key not in _analysis_cache:
        _analysis_cache[key] = terrain.analyze_region(west, south, east, north, caution_deg=caution, high_deg=high, max_deg=mx)
        while len(_analysis_cache) > 12:
            _analysis_cache.popitem(last=False)
    return _analysis_cache[key]


def _req_bbox(req: schemas.HazardRequest) -> tuple[float, float, float, float]:
    if req.bbox:
        return tuple(req.bbox)  # type: ignore[return-value]
    dlat = math.degrees(req.radius_km * 1000 / MARS_RADIUS_M)
    dlon = dlat / max(0.05, math.cos(math.radians(req.center.lat)))
    return req.center.lon - dlon, max(-87.9, req.center.lat - dlat), req.center.lon + dlon, min(87.9, req.center.lat + dlat)


@router.post("/hazards/analyze", tags=["terrain"])
def hazards_analyze(req: schemas.HazardRequest, db: Session = Depends(get_db)):
    w, s, e, n = _req_bbox(req)
    try:
        a = _analysis(w, s, e, n, req.caution_deg, req.high_deg, req.max_slope_deg)
    except dem.DemUnavailable as ex:
        raise _dem_error(ex) from ex
    b = a["summary"]["bbox"]
    q = f"west={w}&south={s}&east={e}&north={n}&caution={req.caution_deg}&high={req.high_deg}&max_slope={req.max_slope_deg}"
    db.add(HazardGeometry(basis="inferred", hazard="analysis", west=b[0], south=b[1], east=b[2], north=b[3], detail=a["summary"]["hazard_fraction"]))
    db.commit()
    return {**a["summary"], "overlays": {k: f"/api/v1/terrain/overlay.png?kind={k}&{q}" for k in ("slope", "hazard", "quality", "elevation", "roughness")}}


@router.get("/terrain/overlay.png", tags=["terrain"], responses={200: {"content": {"image/png": {}}}})
def terrain_overlay(kind: str = Query(..., pattern="^(slope|hazard|quality|elevation|roughness)$"), west: float = Query(...), south: float = Query(...),
                    east: float = Query(...), north: float = Query(...), caution: float = 10.0, high: float = 20.0, max_slope: float = 30.0):
    try:
        a = _analysis(west, south, east, north, caution, high, max_slope)
    except dem.DemUnavailable as ex:
        raise _dem_error(ex) from ex
    b = a["summary"]["bbox"]
    return Response(terrain.overlay_png(kind, a), media_type="image/png",
                    headers={"X-Overlay-BBox": ",".join(f"{v:.6f}" for v in b), "Cache-Control": "public, max-age=86400",
                             "Access-Control-Expose-Headers": "X-Overlay-BBox"})


# ----------------------------------------------------------------------------- routes

def _segments(profile: list[dict]) -> list[dict]:
    segs, cur = [], None
    for p in profile:
        key = (p["hazard"], p["quality"])
        if cur is None or cur["key"] != key:
            if cur:
                cur["end_m"] = p["distance_m"]
                segs.append(cur)
            cur = {"key": key, "start_m": p["distance_m"], "end_m": p["distance_m"], "hazard": p["hazard"], "quality": p["quality"]}
        cur["end_m"] = p["distance_m"]
    if cur:
        segs.append(cur)
    for s in segs:
        s.pop("key")
    return segs


def _persist_plan(db: Session, plan: dict, mission_id: int | None) -> None:
    for c in plan["candidates"] + ([plan["return_route"]] if plan["return_route"] else []):
        segs = _segments(c["elevation_profile"])
        c["segments"] = segs
        r = Route(mission_id=mission_id, plan_id=plan["plan_id"], profile=c["profile"], distance_m=c["distance_m"], energy_wh=c["energy"]["total_wh"],
                  duration_h=c["duration_h"]["value"], dem_source=plan["dem"]["id"], geometry=c["geometry"],
                  metrics={k: v for k, v in c.items() if k not in ("geometry", "elevation_profile", "segments")})
        r.segments = [RouteSegment(seq=i, start_m=s["start_m"], end_m=s["end_m"], hazard=s["hazard"], quality=s["quality"]) for i, s in enumerate(segs)]
        db.add(r)
        db.flush()
        c["route_id"] = r.id
    db.commit()


@router.post("/routes/plan", tags=["routes"])
def routes_plan(req: schemas.RoutePlanRequest, db: Session = Depends(get_db)):
    if req.mission_id is not None and db.get(Mission, req.mission_id) is None:
        raise HTTPException(404, detail={"error": "mission_not_found"})
    if req.mode == "eva":
        veh = routing.Vehicle.eva(endurance_h=req.endurance_h, **({"speed_kmh": min(req.vehicle.speed_kmh, 6.0)} if req.vehicle else {}))
    else:
        veh = routing.Vehicle(**req.vehicle.model_dump()) if req.vehicle else routing.Vehicle()
    try:
        plan = routing.plan_routes((req.start.lon, req.start.lat), (req.goal.lon, req.goal.lat),
                                   weights=req.weights.model_dump() if req.weights else None, max_slope_deg=req.max_slope_deg,
                                   caution_deg=req.caution_deg, high_deg=req.high_deg, safety_margin=req.safety_margin,
                                   unknown_penalty=req.unknown_penalty, vehicle=veh, include_return=req.include_return)
    except routing.RouteError as ex:
        raise HTTPException(422, detail={"error": "invalid_route_request", "message": str(ex)}) from ex
    except dem.DemUnavailable as ex:
        raise _dem_error(ex) from ex
    plan["comparison"] = routing.compare(plan["candidates"])
    plan["science_nearby"] = _science_near_route(plan)
    ai_tools.store_plan(plan)
    _persist_plan(db, plan, req.mission_id)
    return plan


def _science_near_route(plan: dict, corridor_m: float = 1500.0) -> list[dict]:
    """Science opportunities within a corridor of the recommended route (distance only)."""
    if not plan["candidates"]:
        return []
    from .mars import haversine_m
    rec = (plan.get("comparison") or {}).get("recommendation") or {}
    cand = next((c for c in plan["candidates"] if c["profile"] == rec.get("profile")), plan["candidates"][0])
    coords = cand["geometry"]["coordinates"]
    pts = coords[::max(1, len(coords) // 40)]
    mid = pts[len(pts) // 2]
    res = science.find_targets(mid[0], mid[1], max(2.0, plan["straight_line_m"] / 1000.0), limit=60, include_gazetteer=False)
    out = []
    for t in res["targets"]:
        d = min(haversine_m(t["lon"], t["lat"], p[0], p[1]) for p in pts)
        if d <= corridor_m:
            out.append({"id": t["id"], "name": t["name"], "category": t["category"], "lon": t["lon"], "lat": t["lat"], "offset_m": round(d), "score": t["score"]})
    return sorted(out, key=lambda x: -x["score"])[:8]


@router.get("/routes/plans/{plan_id}", tags=["routes"])
def routes_get_plan(plan_id: str):
    plan = ai_tools.PLAN_STORE.get(plan_id)
    if plan is None:
        raise HTTPException(404, detail={"error": "plan_not_found", "message": "Plans are kept in memory for the current server session; individual routes persist under /routes/{id}."})
    return plan


@router.get("/routes/{route_id}", tags=["routes"])
def routes_get(route_id: int, db: Session = Depends(get_db)):
    r = db.get(Route, route_id)
    if r is None:
        raise HTTPException(404, detail={"error": "route_not_found"})
    return {"id": r.id, "plan_id": r.plan_id, "mission_id": r.mission_id, "profile": r.profile, "distance_m": r.distance_m, "energy_wh": r.energy_wh,
            "duration_h": r.duration_h, "dem_source": r.dem_source, "geometry": r.geometry, "metrics": r.metrics, "created_at": r.created_at,
            "segments": [{"seq": s.seq, "start_m": s.start_m, "end_m": s.end_m, "hazard": s.hazard, "quality": s.quality} for s in sorted(r.segments, key=lambda s: s.seq)]}


# ----------------------------------------------------------------------------- guided missions

@router.get("/guided", tags=["guided missions"])
def guided_list():
    out = []
    for mid in guided.MISSIONS:
        s = guided.summary(mid)
        if s["planned"]:
            try:
                p = guided.plan(mid)
                s["totals"], s["feasibility"], s["confidence"], s["dem"] = p["totals"], p["feasibility"], p["confidence"], p["dem"]
            except Exception:  # noqa: BLE001 - a stale cache must not break the list
                s["planned"] = False
        out.append(s)
    return {"missions": out}


@router.get("/guided/{mission_id}", tags=["guided missions"])
def guided_get(mission_id: str, refresh: bool = False):
    if mission_id not in guided.MISSIONS:
        raise HTTPException(404, detail={"error": "guided_mission_not_found"})
    try:
        return guided.plan(mission_id, refresh=refresh)
    except RuntimeError as ex:
        raise HTTPException(503, detail={"error": "mission_plan_unavailable", "message": str(ex)}) from ex


@router.post("/guided/{mission_id}/abort", tags=["guided missions"])
def guided_abort(mission_id: str, pos: schemas.Point):
    if mission_id not in guided.MISSIONS:
        raise HTTPException(404, detail={"error": "guided_mission_not_found"})
    try:
        return guided.abort_route(mission_id, pos.lon, pos.lat)
    except routing.RouteError as ex:
        raise HTTPException(422, detail={"error": "no_return_route", "message": str(ex)}) from ex
    except dem.DemUnavailable as ex:
        raise _dem_error(ex) from ex


# ----------------------------------------------------------------------------- missions

def _mission_out(m: Mission, full: bool = False) -> dict:
    d = {"id": m.id, "name": m.name, "status": m.status, "start": {"lon": m.start_lon, "lat": m.start_lat},
         "goal": {"lon": m.goal_lon, "lat": m.goal_lat} if m.goal_lon is not None else None, "objectives": m.objectives or [],
         "target_ids": m.target_ids or [], "constraints": m.constraints, "selected_route_id": m.selected_route_id,
         "return_route_id": m.return_route_id, "created_at": m.created_at, "route_count": len(m.routes)}
    if full:
        d["routes"] = [{"id": r.id, "plan_id": r.plan_id, "profile": r.profile, "distance_m": r.distance_m, "energy_wh": r.energy_wh, "duration_h": r.duration_h} for r in m.routes]
        d["logs"] = [{"id": g.id, "kind": g.kind, "message": g.message, "data": g.data, "created_at": g.created_at} for g in sorted(m.logs, key=lambda g: g.id)]
    return d


@router.get("/missions", tags=["missions"])
def missions_list(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    total = db.scalar(select(func.count()).select_from(Mission))
    rows = db.execute(select(Mission).order_by(Mission.id.desc()).offset(offset).limit(limit)).scalars().all()
    return {"total": total, "offset": offset, "limit": limit, "missions": [_mission_out(m) for m in rows]}


@router.post("/missions", tags=["missions"], status_code=201)
def missions_create(req: schemas.MissionCreate, db: Session = Depends(get_db)):
    m = Mission(name=req.name, start_lon=norm_lon(req.start.lon), start_lat=req.start.lat, goal_lon=norm_lon(req.goal.lon) if req.goal else None,
                goal_lat=req.goal.lat if req.goal else None, objectives=req.objectives, target_ids=req.target_ids, constraints=req.constraints)
    m.logs.append(MissionLog(kind="created", message=f"Mission '{req.name}' created."))
    db.add(m)
    db.commit()
    return _mission_out(m, True)


@router.get("/missions/{mission_id}", tags=["missions"])
def missions_get(mission_id: int, db: Session = Depends(get_db)):
    m = db.get(Mission, mission_id)
    if m is None:
        raise HTTPException(404, detail={"error": "mission_not_found"})
    return _mission_out(m, True)


@router.patch("/missions/{mission_id}", tags=["missions"])
def missions_update(mission_id: int, req: schemas.MissionUpdate, db: Session = Depends(get_db)):
    m = db.get(Mission, mission_id)
    if m is None:
        raise HTTPException(404, detail={"error": "mission_not_found"})
    data = req.model_dump(exclude_unset=True)
    for rid_field in ("selected_route_id", "return_route_id"):
        if data.get(rid_field) is not None:
            r = db.get(Route, data[rid_field])
            if r is None:
                raise HTTPException(404, detail={"error": "route_not_found", "field": rid_field})
            r.mission_id = m.id
    if "goal" in data and data["goal"]:
        m.goal_lon, m.goal_lat = norm_lon(data["goal"]["lon"]), data["goal"]["lat"]
    for k in ("name", "status", "objectives", "target_ids", "selected_route_id", "return_route_id"):
        if k in data and data[k] is not None:
            setattr(m, k, data[k])
    m.logs.append(MissionLog(kind="updated", message="Mission updated: " + ", ".join(sorted(data))))
    db.commit()
    return _mission_out(m, True)


@router.delete("/missions/{mission_id}", tags=["missions"], status_code=204)
def missions_delete(mission_id: int, db: Session = Depends(get_db)):
    m = db.get(Mission, mission_id)
    if m is None:
        raise HTTPException(404, detail={"error": "mission_not_found"})
    db.delete(m)
    db.commit()


@router.post("/missions/{mission_id}/logs", tags=["missions"], status_code=201)
def missions_log(mission_id: int, req: schemas.MissionLogIn, db: Session = Depends(get_db)):
    m = db.get(Mission, mission_id)
    if m is None:
        raise HTTPException(404, detail={"error": "mission_not_found"})
    g = MissionLog(mission_id=m.id, kind=req.kind, message=req.message, data=req.data)
    db.add(g)
    db.commit()
    return {"id": g.id, "kind": g.kind, "message": g.message, "created_at": g.created_at}


# ----------------------------------------------------------------------------- science

@router.get("/science/targets", tags=["science"])
def science_targets(lon: float | None = Query(None, ge=-360, le=360), lat: float | None = Query(None, ge=-90, le=90),
                    radius_km: float | None = Query(None, gt=0, le=5000), q: str | None = Query(None, max_length=80),
                    category: str | None = None, include_gazetteer: bool = True, limit: int = Query(25, ge=1, le=100)):
    if (lon is None) != (lat is None):
        raise HTTPException(422, detail={"error": "lon and lat must be given together"})
    return science.find_targets(lon, lat, radius_km, include_gazetteer=include_gazetteer, limit=limit, query=q, category=category)


@router.get("/science/hydrous", tags=["science"])
def science_hydrous():
    d = catalog.hydrous()
    return {k: d[k] for k in ("retrieved", "source", "source_url", "reference", "limitations")} | {
        "count": len(d["detections"]), "detections": [[p["lon"], p["lat"], p["instrument"]] for p in d["detections"]]}


@router.get("/science/references", tags=["science"])
def science_references(db: Session = Depends(get_db)):
    return {"references": [{"id": r.id, "citation": r.citation, "url": r.url} for r in db.execute(select(ScientificReference)).scalars()]}


# ----------------------------------------------------------------------------- environment

@router.get("/environment/summary", tags=["environment"])
def environment_summary():
    return environment.summary()


# ----------------------------------------------------------------------------- AI

@router.get("/ai/status", tags=["ai"])
def ai_status():
    llm = ai_agent.credential_available() and not settings.offline
    return {"mode": "llm" if llm else "planner", "model": settings.ai_model if llm else None,
            "tools": [{"name": t["name"], "description": t["description"]} for t in ai_tools.TOOL_SPECS],
            "note": None if llm else "Set ANTHROPIC_API_KEY (or MARSX_ANTHROPIC_API_KEY) to enable the language model. "
                                     "Without it MARS AI uses a deterministic planner over the same tools."}


@router.post("/ai/chat", tags=["ai"])
def ai_chat(req: schemas.ChatRequest, db: Session = Depends(get_db)):
    return ai_agent.chat(db, req.message, [m.model_dump() for m in req.history], req.context)


# ----------------------------------------------------------------------------- simulation

@router.get("/simulation/scenarios", tags=["simulation"])
def simulation_scenarios():
    return {"scenarios": [{"id": k, "description": v} for k, v in simulation.SCENARIOS.items()],
            "defaults": {"battery_wh": simulation.DEFAULT_BATTERY_WH, "reserve_fraction": simulation.RESERVE_FRACTION}}


@router.post("/simulation", tags=["simulation"])
def simulation_run(req: schemas.SimulationRequest, db: Session = Depends(get_db)):
    if req.scenario not in simulation.SCENARIOS:
        raise HTTPException(422, detail={"error": "unknown_scenario", "valid": list(simulation.SCENARIOS)})
    constraints = None
    if req.plan_id:
        plan = ai_tools.PLAN_STORE.get(req.plan_id)
        if plan is None:
            raise HTTPException(404, detail={"error": "plan_not_found"})
        c = next((c for c in plan["candidates"] if c["profile"] == req.profile), None) or (plan["candidates"][0] if plan["candidates"] else None)
        if c is None:
            raise HTTPException(422, detail={"error": "plan_has_no_routes"})
        route = c["geometry"]["coordinates"]
        ret = plan["return_route"]["geometry"]["coordinates"] if plan["return_route"] else None
        constraints = {**plan["constraints"], "cell_m": plan["dem"]["effective_resolution_m"]}
        veh_d = {k: plan["vehicle"][k] for k in ("mass_kg", "rolling_resistance", "drivetrain_efficiency", "speed_kmh", "hotel_power_w")}
        veh = routing.Vehicle(**(req.vehicle.model_dump(exclude={"battery_wh"}) if req.vehicle else veh_d))
        battery = req.battery_wh or (req.vehicle.battery_wh if req.vehicle else None) or plan["vehicle"].get("battery_wh")
    else:
        route, ret = req.route, req.return_route
        veh = routing.Vehicle(**req.vehicle.model_dump(exclude={"battery_wh"})) if req.vehicle else routing.Vehicle()
        battery = req.battery_wh or (req.vehicle.battery_wh if req.vehicle else None)
    try:
        sim = simulation.simulate(route, ret, req.scenario, veh, battery, req.dwell_min, req.safety_margin, req.objectives, constraints)
    except ValueError as ex:
        raise HTTPException(422, detail={"error": "invalid_simulation", "message": str(ex)}) from ex
    if req.mission_id is not None:
        m = db.get(Mission, req.mission_id)
        if m:
            db.add(MissionLog(mission_id=m.id, kind="simulation", message=f"SIMULATION '{req.scenario}': {sim['outcome']}", data=sim["summary"]))
            db.commit()
    return sim


# ----------------------------------------------------------------------------- datasets / offline

@router.get("/datasets", tags=["datasets"])
def datasets_list(q: str | None = Query(None, max_length=80), category: str | None = None, db: Session = Depends(get_db)):
    rows = db.execute(select(Dataset).order_by(Dataset.category, Dataset.name)).scalars().all()
    out = []
    for d in rows:
        blob = f"{d.id} {d.name} {d.mission} {d.instrument} {d.category}".lower()
        if (q and q.lower() not in blob) or (category and d.category != category):
            continue
        out.append({c.name: getattr(d, c.name) for c in Dataset.__table__.columns})
    return {"count": len(out), "datasets": out,
            "missions": sorted({m.strip() for d in rows if d.mission for m in d.mission.replace(";", ",").split(",") if m.strip() and "Multiple" not in m})}


@router.get("/datasets/trek-catalog", tags=["datasets"])
def datasets_trek_catalog(q: str | None = Query(None, max_length=80), limit: int = Query(50, ge=1, le=300), offset: int = Query(0, ge=0)):
    """Metadata of every product in NASA Mars Trek's catalogue (snapshot); MARS-X renders a curated subset as layers."""
    cat = catalog.trek_catalog()
    items = [p for p in cat["products"] if not q or q.lower() in f"{p['title']} {p['mission']} {p['instrument']} {p['productLabel']}".lower()]
    integrated = {lyr["id"] for lyr in catalog.trek_layers()["layers"]}
    page = [{**{k: p[k] for k in ("productLabel", "title", "mission", "instrument", "productCat1", "bbox", "data_created_date")},
             "integrated_as_layer": p["productLabel"] in integrated} for p in items[offset: offset + limit]]
    return {"retrieved": cat["retrieved"], "total": len(items), "offset": offset, "limit": limit, "products": page}


@router.get("/datasets/{dataset_id}", tags=["datasets"])
def datasets_get(dataset_id: str, db: Session = Depends(get_db)):
    d = db.get(Dataset, dataset_id)
    if d is None:
        raise HTTPException(404, detail={"error": "dataset_not_found"})
    return {c.name: getattr(d, c.name) for c in Dataset.__table__.columns}


@router.get("/offline/bundle", tags=["offline"])
def offline_bundle(lon: float = Query(..., ge=-360, le=360), lat: float = Query(..., ge=-90, le=90), radius_km: float = Query(15, gt=0, le=150),
                   db: Session = Depends(get_db)):
    """Everything a crew needs for a region when the link drops: targets, terrain summary, environment snapshot, dataset provenance."""
    out = {"center": {"lon": norm_lon(lon), "lat": lat}, "radius_km": radius_km,
           "targets": science.find_targets(lon, lat, radius_km, limit=60)["targets"],
           "location": science.location_info(db, lon, lat),
           "environment": environment.summary(),
           "datasets": datasets_list(None, None, db)["datasets"]}
    try:
        dlat = math.degrees(radius_km * 1000 / MARS_RADIUS_M)
        dlon = dlat / max(0.05, math.cos(math.radians(lat)))
        out["terrain"] = _analysis(lon - dlon, lat - dlat, lon + dlon, lat + dlat)["summary"]
    except dem.DemUnavailable as ex:
        out["terrain"] = {"unavailable": str(ex)}
    return out
