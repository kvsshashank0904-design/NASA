"""Terrain-aware route planning: A* over a traversability grid built from real DEMs.

Edge cost between adjacent cells a->b (8-connected):

    C = d3 * ( w_d*D + w_s*S + w_r*R + w_h*H + w_e*E )

    d3  3-D edge length in metres (great-circle horizontal + elevation change)
    D   1 (pure distance term)
    S   (mean cell slope / slope limit)^2
    R   clip(mean roughness / roughness_ref, 0, 1)
    H   hazard-class penalty (caution 0.5, high 2.0) + unknown/interpolated penalty
    E   traction energy per metre relative to flat ground: max(0, cos(t) + sin(t)/c_rr)

Cells steeper than the slope limit, cells without elevation data and edges whose
along-track grade exceeds the limit are impassable. Because every bracketed term
is >= w_d, h = w_d * straight-line distance is an admissible, consistent heuristic.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

import numpy as np

from ..mars import MARS_GRAVITY, MARS_RADIUS_M, haversine_m, norm_lon
from .dem import Q_INTERPOLATED, Q_MEASURED, Q_NODATA, DemGrid, dem_for_route
from .terrain import (H_CAUTION, H_HIGH, H_IMPASSABLE, H_NOMINAL, H_UNKNOWN, HAZARD_LABELS, hazard_classes,
                      roughness_m, slope_deg)

MAX_ROUTE_M = 12_000_000.0  # no practical cap: long trips fall back to the 3.7 km global MOLA grid
DIRS = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]

PROFILES = {
    "safest": {"distance": 0.3, "slope": 4.0, "roughness": 2.0, "hazard": 6.0, "energy": 0.5},
    "shortest": {"distance": 1.0, "slope": 0.0, "roughness": 0.0, "hazard": 0.0, "energy": 0.0},
    "balanced": {"distance": 1.0, "slope": 1.5, "roughness": 1.0, "hazard": 2.0, "energy": 1.0},
}
PROFILE_DESCRIPTIONS = {
    "safest": "Minimises slope, roughness and hazard exposure; uses a slope limit tightened by the safety margin.",
    "shortest": "Minimises 3-D path length subject only to the hard slope limit.",
    "balanced": "Trades distance against slope, roughness, hazard and traction energy using the mission weights.",
}


@dataclass
class Vehicle:
    """Crewed surface rover model. All values are configurable planning ASSUMPTIONS, not measurements."""
    mass_kg: float = 3000.0
    rolling_resistance: float = 0.15     # loose regolith
    drivetrain_efficiency: float = 0.7
    speed_kmh: float = 8.0
    hotel_power_w: float = 600.0         # life support / avionics while driving
    battery_wh: float | None = None
    kind: str = "rover"                  # "rover" | "eva"
    endurance_h: float | None = None     # life-support time limit (EVA)

    @classmethod
    def eva(cls, endurance_h: float = 8.0, speed_kmh: float = 3.0, mass_kg: float = 180.0) -> "Vehicle":
        """Suited astronaut on foot. Energy is METABOLIC: the parameters are chosen so level walking costs
        250 W (Apollo-era surface EVA average, an assumption) and climbing costs m*g*dh at 20% muscle efficiency."""
        v = speed_kmh / 3.6
        eff = 0.2
        crr = 250.0 * eff / (mass_kg * MARS_GRAVITY * v)
        return cls(mass_kg=mass_kg, rolling_resistance=crr, drivetrain_efficiency=eff, speed_kmh=speed_kmh,
                   hotel_power_w=0.0, battery_wh=None, kind="eva", endurance_h=endurance_h)

    def assumptions(self) -> dict:
        return {"mass_kg": self.mass_kg, "rolling_resistance": self.rolling_resistance,
                "drivetrain_efficiency": self.drivetrain_efficiency, "speed_kmh": self.speed_kmh,
                "hotel_power_w": self.hotel_power_w, "battery_wh": self.battery_wh,
                "kind": self.kind, "endurance_h": self.endurance_h, "gravity_m_s2": MARS_GRAVITY,
                "note": ("Suited astronaut on foot: energy is metabolic (250 W level-walking baseline + climbing work at 20% "
                         "efficiency). Planning assumptions." if self.kind == "eva" else
                         "Planning assumptions for a generic crewed rover; edit them in the mission constraints.")}


class RouteError(ValueError):
    pass


class TraversabilityGrid:
    def __init__(self, grid: DemGrid, max_slope_deg: float, caution_deg: float, high_deg: float,
                 unknown_penalty: float, vehicle: Vehicle, blocked_zones: list[tuple[float, float, float]] | None = None):
        self.grid = grid
        self.max_slope = max_slope_deg
        self.vehicle = vehicle
        self.slope = slope_deg(grid)
        self.rough = roughness_m(grid)
        self.hazard = hazard_classes(grid, self.slope, caution_deg, high_deg, max_slope_deg)
        H, W = grid.z.shape
        self.H, self.W = H, W
        z = grid.z.astype(np.float64)
        dy = grid.dy_m
        dx = grid.dx_m()
        self.x_min = float(dx.min())
        self.y = (np.arange(H) * dy).tolist()
        self.x = (np.arange(W) * self.x_min).tolist()      # conservative (never over-estimates) for the heuristic
        blocked = (self.hazard == H_IMPASSABLE) | (self.hazard == H_UNKNOWN) | np.isnan(z)
        # externally supplied no-go zones (lon, lat, radius_m), e.g. a hazard reported during a simulation
        for zlon, zlat, zrad in blocked_zones or []:
            zr, zc = grid.index(zlon, zlat)
            rr = (np.arange(H)[:, None] - zr) * dy
            cc = (np.arange(W)[None, :] - zc) * dx[:, None]
            blocked = blocked | (np.hypot(rr, cc) <= zrad)
        self.blocked = blocked
        slope_n = np.nan_to_num(self.slope, nan=max_slope_deg) / max_slope_deg
        rough_ref = max(1e-6, 0.1 * grid.cell_m)
        rough_n = np.clip(np.nan_to_num(self.rough, nan=rough_ref) / rough_ref, 0, 1)
        haz_pen = np.select([self.hazard == H_CAUTION, self.hazard == H_HIGH], [0.5, 2.0], 0.0)
        haz_pen = haz_pen + np.where(grid.quality == Q_INTERPOLATED, unknown_penalty, 0.0)
        c_rr = vehicle.rolling_resistance
        # per-direction edge components (H, W): geometry d3, and S, R, Hz, E factors
        self.d3, self.S, self.R, self.Hz, self.E, self.ok = [], [], [], [], [], []
        for dr, dc in DIRS:
            zb, sb, rb, hb, bb = (self._shift(a, dr, dc, fill) for a, fill in
                                  ((z, np.nan), (slope_n, 1.0), (rough_n, 1.0), (haz_pen, 0.0), (blocked.astype(float), 1.0)))
            dh = np.hypot(dr * dy, dc * dx[:, None] * np.ones((1, W)))
            dz = zb - z
            d3 = np.hypot(dh, dz)
            grade = np.degrees(np.arctan2(np.abs(dz), dh))
            theta = np.arctan2(dz, dh)
            e = np.maximum(0.0, np.cos(theta) + np.sin(theta) / c_rr)
            ok = ~(blocked | (bb > 0.5) | np.isnan(dz) | (grade > max_slope_deg))
            self.d3.append(d3); self.S.append(((slope_n + sb) / 2) ** 2); self.R.append((rough_n + rb) / 2)
            self.Hz.append((haz_pen + hb) / 2); self.E.append(e); self.ok.append(ok)

    @staticmethod
    def _shift(a: np.ndarray, dr: int, dc: int, fill: float) -> np.ndarray:
        """Value of the neighbour at (r+dr, c+dc) for every cell; out-of-grid -> fill."""
        out = np.full(a.shape, fill, dtype=np.float64)
        H, W = a.shape
        rs, rd = (slice(dr, H), slice(0, H - dr)) if dr >= 0 else (slice(0, H + dr), slice(-dr, H))
        cs, cd = (slice(dc, W), slice(0, W - dc)) if dc >= 0 else (slice(0, W + dc), slice(-dc, W))
        out[rd, cd] = a[rs, cs]
        return out

    def edge_costs(self, w: dict) -> list[list[float]]:
        out = []
        for i in range(8):
            c = self.d3[i] * (w["distance"] + w["slope"] * self.S[i] + w["roughness"] * self.R[i]
                              + w["hazard"] * self.Hz[i] + w["energy"] * self.E[i])
            c = np.where(self.ok[i], c, np.inf)
            out.append(c.ravel().tolist())
        return out

    def solve(self, start: tuple[int, int], goal: tuple[int, int], w: dict) -> list[tuple[int, int]] | None:
        """Optimal path on the same edge costs as `astar`, solved by SciPy's compiled Dijkstra.

        A* and Dijkstra return paths of identical cost (the A* heuristic only prunes the search); the compiled
        solver is 20-50x faster than the pure-Python A* below, which is kept as the reference implementation
        and is checked against this one in the test suite.
        """
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import dijkstra
        H, W = self.H, self.W
        n = H * W
        idx = np.arange(n).reshape(H, W)
        rows, cols, data = [], [], []
        for i, (dr, dc) in enumerate(DIRS):
            c = self.d3[i] * (w["distance"] + w["slope"] * self.S[i] + w["roughness"] * self.R[i]
                              + w["hazard"] * self.Hz[i] + w["energy"] * self.E[i])
            ok = self.ok[i] & np.isfinite(c)
            src = idx[ok]
            rows.append(src)
            cols.append(src + dr * W + dc)
            data.append(np.maximum(c[ok], 1e-9))
        g = coo_matrix((np.concatenate(data), (np.concatenate(rows), np.concatenate(cols))), shape=(n, n)).tocsr()
        s, t = start[0] * W + start[1], goal[0] * W + goal[1]
        dist, pred = dijkstra(g, directed=True, indices=s, return_predecessors=True)
        if not np.isfinite(dist[t]):
            return None
        path, u = [], t
        while u != s:
            path.append((u // W, u % W))
            u = int(pred[u])
            if u < 0:
                return None
        path.append(start)
        return path[::-1]

    def astar(self, start: tuple[int, int], goal: tuple[int, int], w: dict) -> list[tuple[int, int]] | None:
        H, W = self.H, self.W
        costs = self.edge_costs(w)
        offs = [dr * W + dc for dr, dc in DIRS]
        s, g = start[0] * W + start[1], goal[0] * W + goal[1]
        gx, gy = self.x[goal[1]], self.y[goal[0]]
        xs, ys, wd = self.x, self.y, w["distance"]
        INF = math.inf
        best = [INF] * (H * W)
        parent = [-1] * (H * W)
        best[s] = 0.0
        heap = [(0.0, s)]
        closed = bytearray(H * W)
        while heap:
            _, u = heapq.heappop(heap)
            if closed[u]:
                continue
            if u == g:
                break
            closed[u] = 1
            gu = best[u]
            for i in range(8):
                c = costs[i][u]
                if c == INF:
                    continue
                v = u + offs[i]
                ng = gu + c
                if ng < best[v]:
                    best[v] = ng
                    parent[v] = u
                    hx, hy = xs[v % W] - gx, ys[v // W] - gy
                    heapq.heappush(heap, (ng + wd * math.sqrt(hx * hx + hy * hy), v))
        if best[g] == INF:
            return None
        path, u = [], g
        while u != -1:
            path.append((u // W, u % W))
            u = parent[u]
        return path[::-1]

    def nearest_open(self, rc: tuple[int, int], radius: int = 3) -> tuple[int, int] | None:
        r0, c0 = rc
        if not self.blocked[r0, c0]:
            return rc
        bestd, best = None, None
        for r in range(max(0, r0 - radius), min(self.H, r0 + radius + 1)):
            for c in range(max(0, c0 - radius), min(self.W, c0 + radius + 1)):
                if not self.blocked[r, c]:
                    d = (r - r0) ** 2 + (c - c0) ** 2
                    if bestd is None or d < bestd:
                        bestd, best = d, (r, c)
        return best


def _metrics(tg: TraversabilityGrid, path: list[tuple[int, int]], vehicle: Vehicle) -> dict:
    grid = tg.grid
    pts, profile = [], []
    total = ascent = descent = work_j = 0.0
    len_by_class = {k: 0.0 for k in (H_NOMINAL, H_CAUTION, H_HIGH)}
    len_interp = 0.0
    max_grade, slope_len = 0.0, 0.0
    rough_len = 0.0
    prev = None
    for r, c in path:
        lon, lat, z = norm_lon(float(grid.lons[c])), float(grid.lats[r]), float(grid.z[r, c])
        seg = 0.0
        if prev is not None:
            pr, pc, plon, plat, pz = prev
            dh = haversine_m(plon, plat, lon, lat)
            dz = z - pz
            seg = math.hypot(dh, dz)
            theta = math.atan2(dz, dh)
            ascent += max(dz, 0.0); descent += max(-dz, 0.0)
            work_j += vehicle.mass_kg * MARS_GRAVITY * seg * max(0.0, vehicle.rolling_resistance * math.cos(theta) + math.sin(theta))
            max_grade = max(max_grade, abs(math.degrees(theta)))
            cls = int(max(tg.hazard[r, c], tg.hazard[pr, pc]))
            len_by_class[min(cls, H_HIGH)] += seg
            if grid.quality[r, c] != Q_MEASURED or grid.quality[pr, pc] != Q_MEASURED:
                len_interp += seg
            slope_len += seg * float(np.nanmean([tg.slope[r, c], tg.slope[pr, pc]]))
            rough_len += seg * float(np.nanmean([tg.rough[r, c], tg.rough[pr, pc]]))
        total += seg
        pts.append([round(lon, 6), round(lat, 6), round(z, 1)])
        profile.append({"distance_m": round(total, 1), "elevation_m": round(z, 1),
                        "slope_deg": round(float(tg.slope[r, c]), 2),
                        "hazard": HAZARD_LABELS[int(tg.hazard[r, c])],
                        "quality": "measured" if grid.quality[r, c] == Q_MEASURED else "interpolated"})
        prev = (r, c, lon, lat, z)
    total = max(total, 1e-9)
    hours = (total / 1000.0) / vehicle.speed_kmh
    traction_wh = work_j / vehicle.drivetrain_efficiency / 3600.0
    hotel_wh = vehicle.hotel_power_w * hours
    mean_slope = slope_len / total
    cells_max_slope = max(float(tg.slope[r, c]) for r, c in path)
    haz = {HAZARD_LABELS[k]: round(v / total, 4) for k, v in len_by_class.items()}
    rough_ref = 0.1 * grid.cell_m
    difficulty = 100 * min(1.0, 0.5 * mean_slope / tg.max_slope + 0.3 * (haz["caution"] * 0.5 + haz["high"])
                           + 0.2 * min(1.0, (rough_len / total) / rough_ref))
    # thin the geometry for transport; keep full profile resolution up to 400 samples
    step = max(1, len(profile) // 400)
    return {
        "geometry": {"type": "LineString", "coordinates": pts},
        "distance_m": round(total, 1),
        "ascent_m": round(ascent, 1), "descent_m": round(descent, 1),
        "max_along_track_grade_deg": round(max_grade, 2),
        "max_cell_slope_deg": round(cells_max_slope, 2),
        "mean_slope_deg": round(mean_slope, 2),
        "mean_roughness_m": round(rough_len / total, 2),
        "hazard_exposure": haz,
        "interpolated_fraction": round(len_interp / total, 4),
        "energy": {"traction_wh": round(traction_wh, 1), "hotel_wh": round(hotel_wh, 1),
                   "total_wh": round(traction_wh + hotel_wh, 1), "kind": "derived estimate"},
        "duration_h": {"value": round(hours, 3), "kind": "derived estimate (constant speed assumption)"},
        "difficulty_index": {"value": round(difficulty, 1), "kind": "derived index 0-100",
                             "formula": "100*min(1, 0.5*mean_slope/limit + 0.3*(0.5*caution+high) + 0.2*roughness/ref)"},
        "elevation_profile": profile[::step] + ([profile[-1]] if (len(profile) - 1) % step else []),
    }


def _confidence(grid: DemGrid, m: dict) -> dict:
    reasons = []
    res = grid.cell_m
    if grid.source.startswith("hirise"):
        level = "high" if res <= 5 else "moderate"
        reasons.append(f"Elevation from HiRISE stereo DEM at {res:.0f} m effective resolution.")
        floor = "Rocks under ~2 m and loose sand are not represented"
    elif grid.source == "ctx":
        level = "moderate"
        reasons.append(f"Elevation from CTX stereo DTM at {res:.0f} m effective resolution.")
        floor = "Rocks, sand traps and scarps smaller than the DEM pixel are not represented"
    else:
        level = "low" if grid.source == "mola" else "very low"
        reasons.append(f"Elevation from MOLA at {res:.0f} m effective resolution - regional slopes only.")
        floor = "Local slopes, scarps, dunes and rocks are not represented"
    if m["interpolated_fraction"] > 0.25:
        level = "low" if level in ("high", "moderate") else level
        reasons.append(f"{m['interpolated_fraction'] * 100:.0f}% of the route crosses interpolated (unmeasured) DEM cells.")
    reasons.append(floor + "; verify on the ground before committing.")
    return {"level": level, "reasons": reasons}


def _window(lon1, lat1, lon2, lat2, margin_frac=0.35) -> tuple[float, float, float, float]:
    dist = haversine_m(lon1, lat1, lon2, lat2)
    m = max(dist * margin_frac, 1500.0)
    dlat = math.degrees(m / MARS_RADIUS_M)
    dlon = dlat / max(0.05, math.cos(math.radians(max(abs(lat1), abs(lat2)))))
    # unwrap lon2 relative to lon1 for antimeridian safety
    d = norm_lon(lon2 - lon1)
    lo2 = lon1 + d
    return min(lon1, lo2) - dlon, min(lat1, lat2) - dlat, max(lon1, lo2) + dlon, max(lat1, lat2) + dlat


def plan_routes(start: tuple[float, float], goal: tuple[float, float], weights: dict | None = None,
                max_slope_deg: float = 25.0, caution_deg: float = 10.0, high_deg: float = 20.0,
                safety_margin: float = 0.2, unknown_penalty: float = 1.0, vehicle: Vehicle | None = None,
                include_return: bool = True, max_cells: int = 160_000, profiles: list[str] | None = None,
                blocked_zones: list[tuple[float, float, float]] | None = None) -> dict:
    """Plan candidate routes start->goal ((lon, lat) east-positive degrees) plus a separate return route."""
    vehicle = vehicle or Vehicle()
    lon1, lat1 = norm_lon(start[0]), start[1]
    lon2, lat2 = norm_lon(goal[0]), goal[1]
    straight = haversine_m(lon1, lat1, lon2, lat2)
    if straight < 1.0:
        raise RouteError("start and destination are the same point")
    if not (0 < max_slope_deg <= 45):
        raise RouteError("max_slope_deg must be in (0, 45]")
    if straight > MAX_ROUTE_M:
        raise RouteError(f"start and destination are {straight / 1000:.0f} km apart, beyond the planner limit")
    west, south, east, north = _window(lon1, lat1, lon2, lat2)
    # best DEM for the trip: HiRISE patch > CTX (Jezero) > MOLA 463 m > MOLA 3.7 km for long traverses
    full = dem_for_route(lon1, lat1, lon2, lat2, west, south, east, north)
    stride = max(1, math.ceil(math.sqrt(full.z.size / max_cells)))
    grid = full.downsample(stride)
    warnings = []
    if straight < 3 * grid.cell_m:
        warnings.append(f"INSUFFICIENT RESOLUTION: the {straight:.0f} m trip spans fewer than 3 DEM cells "
                        f"({grid.cell_m:.0f} m). The route below is essentially a straight line; terrain between "
                        "the endpoints is unresolved.")
    if grid.source.startswith("mola"):
        warnings.append(f"MOLA-ONLY TERRAIN: slopes are averages over ~{grid.cell_m:.0f} m baselines, so 'nominal' means no regional slope "
                        "hazard was resolved - it does NOT mean the ground is clear. Local slopes, scarps, dunes and rocks "
                        "are invisible at this resolution.")
    if stride > 1:
        warnings.append(f"DEM resampled by {stride}x to {grid.cell_m:.0f} m cells to keep the search tractable.")

    base_w = dict(PROFILES["balanced"])
    if weights:
        for k, v in weights.items():
            if k in base_w and v is not None:
                if v < 0:
                    raise RouteError("weights must be non-negative")
                base_w[k] = float(v)
    if sum(base_w.values()) <= 0:
        raise RouteError("at least one weight must be positive")

    tg = TraversabilityGrid(grid, max_slope_deg, caution_deg, high_deg, unknown_penalty, vehicle, blocked_zones)
    safe_limit = max_slope_deg * (1 - safety_margin)
    tg_safe = TraversabilityGrid(grid, safe_limit, min(caution_deg, safe_limit * 0.5), min(high_deg, safe_limit * 0.8),
                                 unknown_penalty, vehicle, blocked_zones) if safety_margin > 0 else tg

    def endpoints(t: TraversabilityGrid):
        s = t.nearest_open(grid.index(lon1, lat1))
        g = t.nearest_open(grid.index(lon2, lat2))
        return s, g

    candidates, failures = [], []
    for name in (profiles or ["safest", "shortest", "balanced"]):
        w = base_w if name == "balanced" else PROFILES[name]
        t = tg_safe if name == "safest" else tg
        s, g = endpoints(t)
        path = t.solve(s, g, w) if s and g else None
        if path is None and name == "safest" and t is not tg:
            s, g = endpoints(tg)
            path = tg.solve(s, g, w) if s and g else None
            t = tg
            if path is not None:
                warnings.append(f"No path satisfies the tightened {safe_limit:.1f} deg safety limit; the 'safest' "
                                f"candidate uses the hard {max_slope_deg:.1f} deg limit instead.")
        if path is None:
            failures.append({"profile": name, "reason": "no traversable path under the slope limit within the analysis window"})
            continue
        m = _metrics(t, path, vehicle)
        m.update({"profile": name, "description": PROFILE_DESCRIPTIONS[name], "weights": w,
                  "slope_limit_deg": round(t.max_slope, 2), "confidence": _confidence(grid, m),
                  "straight_line_m": round(straight, 1)})
        candidates.append(m)

    # mark duplicates so the UI does not pretend three identical lines are three options
    for i, c in enumerate(candidates):
        for p in candidates[:i]:
            if p["geometry"]["coordinates"] == c["geometry"]["coordinates"]:
                c["identical_to"] = p["profile"]
                break

    ret = None
    if include_return and candidates:
        s, g = endpoints(tg_safe)
        t = tg_safe
        path = t.solve(g, s, PROFILES["safest"]) if s and g else None
        if path is None:
            s, g = endpoints(tg)
            t = tg
            path = tg.solve(g, s, PROFILES["safest"]) if s and g else None
        if path is not None:
            ret = _metrics(t, path, vehicle)
            ret.update({"profile": "return", "description": "Independent return route (destination -> start) planned "
                        "with the safest weights and the safety-margin slope limit. Energy is direction-dependent, "
                        "so it is not simply the outbound route reversed.",
                        "weights": PROFILES["safest"], "slope_limit_deg": round(t.max_slope, 2),
                        "confidence": _confidence(grid, ret), "straight_line_m": round(straight, 1)})
        for c in candidates:
            c["return_feasibility"] = _return_feasibility(c, ret, vehicle, safety_margin)

    return {
        "start": {"lon": lon1, "lat": lat1}, "goal": {"lon": lon2, "lat": lat2},
        "straight_line_m": round(straight, 1),
        "dem": grid.info(),
        "analysis_bbox": grid.bbox,
        "grid_cells": int(grid.z.size),
        "constraints": {"max_slope_deg": max_slope_deg, "caution_deg": caution_deg, "high_deg": high_deg,
                        "safety_margin": safety_margin, "unknown_penalty": unknown_penalty},
        "vehicle": vehicle.assumptions(),
        "candidates": candidates, "return_route": ret, "failures": failures, "warnings": warnings,
        "algorithm": "Optimal graph search (A*-equivalent, compiled Dijkstra) on an 8-connected DEM traversability grid; cost C = d*(w_d + w_s*S + w_r*R + w_h*H + w_e*E)",
        "hazard_basis": "Hazards are INFERRED from DEM slope/roughness; none are directly observed.",
    }


def _return_feasibility(out: dict, ret: dict | None, vehicle: Vehicle, margin: float) -> dict:
    if ret is None:
        return {"feasible": False, "reason": "no traversable return path was found"}
    need = (out["energy"]["total_wh"] + ret["energy"]["total_wh"]) * (1 + margin)
    res = {"round_trip_energy_wh_with_margin": round(need, 1), "safety_margin": margin,
           "round_trip_distance_m": round(out["distance_m"] + ret["distance_m"], 1),
           "round_trip_duration_h": round(out["duration_h"]["value"] + ret["duration_h"]["value"], 3)}
    if vehicle.endurance_h is not None:
        need_h = res["round_trip_duration_h"] * (1 + margin)
        ok = need_h <= vehicle.endurance_h
        res.update({"feasible": ok, "endurance_h": vehicle.endurance_h, "round_trip_duration_h_with_margin": round(need_h, 3),
                    "reason": ("round trip fits the life-support time limit including margin" if ok else
                               "round-trip time with margin exceeds the life-support time limit")})
    elif vehicle.battery_wh is None:
        res.update({"feasible": True, "reason": "a return path exists; no energy budget supplied, so energy "
                    "sufficiency was not evaluated"})
    else:
        ok = need <= vehicle.battery_wh
        res.update({"feasible": ok, "battery_wh": vehicle.battery_wh,
                    "reason": ("round trip fits the energy budget including margin" if ok else
                               "round-trip energy with margin exceeds the energy budget")})
    return res


def compare(candidates: list[dict]) -> dict:
    """Side-by-side comparison + recommendation derived only from computed metrics."""
    if not candidates:
        return {"rows": [], "recommendation": None}
    rows = [{"profile": c["profile"], "distance_m": c["distance_m"], "duration_h": c["duration_h"]["value"],
             "energy_wh": c["energy"]["total_wh"], "mean_slope_deg": c["mean_slope_deg"],
             "max_cell_slope_deg": c["max_cell_slope_deg"],
             "hazard_exposure_pct": round(100 * (c["hazard_exposure"]["caution"] + c["hazard_exposure"]["high"]), 1),
             "interpolated_pct": round(100 * c["interpolated_fraction"], 1),
             "difficulty": c["difficulty_index"]["value"], "confidence": c["confidence"]["level"],
             "return_feasible": c.get("return_feasibility", {}).get("feasible")} for c in candidates]
    dup = {c["profile"] for c in candidates if c.get("identical_to")}
    distinct = [r for r in rows if r["profile"] not in dup]
    feasible = [r for r in distinct if r["return_feasible"] is not False] or distinct
    # rank on the terrain metrics (slope limit actually honoured, hazard exposure, mean slope), then effort
    best = min(feasible, key=lambda r: (r["hazard_exposure_pct"], r["max_cell_slope_deg"], r["difficulty"], r["energy_wh"]))
    shortest = min(distinct, key=lambda r: r["distance_m"])
    if len(distinct) == 1:
        why = (f"all profiles converge on the same path ('{best['profile']}'): hazard exposure {best['hazard_exposure_pct']}% of length, "
               f"steepest cell {best['max_cell_slope_deg']} deg")
    else:
        why = (f"'{best['profile']}' has the lowest hazard exposure ({best['hazard_exposure_pct']}% of length; steepest cell "
               f"{best['max_cell_slope_deg']} deg, difficulty {best['difficulty']}/100)")
        extra = best["distance_m"] - shortest["distance_m"]
        if best["profile"] != shortest["profile"] and extra >= 1:
            why += f", at the cost of {extra:.0f} m more driving than '{shortest['profile']}'"
    return {"rows": rows, "recommendation": {"profile": best["profile"], "reason": why + "."}}
