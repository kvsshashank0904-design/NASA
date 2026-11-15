"""Mission digital twin: deterministic simulation of a planned traverse.

Everything produced here is SIMULATED. Terrain (route geometry, elevations) is real DEM
data; vehicle behaviour, scenario disturbances and energy state are model outputs.
"""
from __future__ import annotations

import math

from ..mars import MARS_GRAVITY, haversine_m
from .routing import RouteError, Vehicle, plan_routes

SCENARIOS = {
    "nominal": "Normal exploration: drive out, do science at the target, return on the planned return route.",
    "terrain_hazard": "An impassable obstacle is discovered ahead at ~50% of the outbound leg; the planner re-routes around a no-go zone.",
    "energy_overrun": "Traction energy is 60% higher than modelled (e.g. soft sand / higher sinkage).",
    "dust_storm": "A dust storm arrives at 30% of the outbound leg: speed is halved and hotel load rises 25%.",
    "comm_degradation": "Communication with the habitat degrades, then drops, during the middle of the traverse; the crew continues autonomously.",
    "emergency_return": "An emergency is declared at 50% of the outbound leg; the crew backtracks along the already-driven path.",
}
DEFAULT_BATTERY_WH = 40_000.0
RESERVE_FRACTION = 0.15


def _segments(coords: list[list[float]]) -> list[dict]:
    segs = []
    for a, b in zip(coords, coords[1:]):
        dh = haversine_m(a[0], a[1], b[0], b[1])
        dz = (b[2] - a[2]) if len(a) > 2 and len(b) > 2 else 0.0
        segs.append({"a": a, "b": b, "d": math.hypot(dh, dz), "theta": math.atan2(dz, dh) if dh > 0 else 0.0})
    return segs


def _traction_wh(seg: dict, v: Vehicle, reverse: bool = False) -> float:
    th = -seg["theta"] if reverse else seg["theta"]
    j = v.mass_kg * MARS_GRAVITY * seg["d"] * max(0.0, v.rolling_resistance * math.cos(th) + math.sin(th))
    return j / v.drivetrain_efficiency / 3600.0


def simulate(route: list[list[float]], return_route: list[list[float]] | None, scenario: str = "nominal",
             vehicle: Vehicle | None = None, battery_wh: float | None = None, dwell_min: float = 30.0,
             safety_margin: float = 0.2, objectives: list[str] | None = None, plan_constraints: dict | None = None) -> dict:
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario '{scenario}'")
    if len(route) < 2:
        raise ValueError("route needs at least two points")
    v = vehicle or Vehicle()
    battery = battery_wh or v.battery_wh or DEFAULT_BATTERY_WH
    reserve = battery * RESERVE_FRACTION
    speed = v.speed_kmh / 3.6
    st = {"t": 0.0, "e": battery, "dist": 0.0, "comm": "nominal", "speed_f": 1.0, "hotel_f": 1.0,
          "trac_f": 1.6 if scenario == "energy_overrun" else 1.0}
    frames, events = [], []

    def event(kind: str, msg: str):
        events.append({"t_s": round(st["t"]), "kind": kind, "message": msg})

    def frame(p, phase):
        frames.append({"t_s": round(st["t"]), "phase": phase, "lon": p[0], "lat": p[1], "elev_m": p[2] if len(p) > 2 else None,
                       "distance_m": round(st["dist"], 1), "energy_wh": round(st["e"], 1),
                       "energy_pct": round(100 * st["e"] / battery, 1), "comm": st["comm"],
                       "speed_kmh": round(v.speed_kmh * st["speed_f"], 2)})

    def advance(seg, reverse=False) -> None:
        dt = seg["d"] / (speed * st["speed_f"])
        st["t"] += dt
        st["e"] -= _traction_wh(seg, v, reverse) * st["trac_f"] + v.hotel_power_w * st["hotel_f"] * dt / 3600.0
        st["dist"] += seg["d"]

    def backtrack_need(segs_done: list[dict]) -> float:
        dt = sum(s["d"] for s in segs_done) / (speed * st["speed_f"])
        return sum(_traction_wh(s, v, True) for s in segs_done) * st["trac_f"] + v.hotel_power_w * st["hotel_f"] * dt / 3600.0

    def drive_back(segs_done: list[dict], phase: str):
        for s in reversed(segs_done):
            advance(s, reverse=True)
            frame(s["a"], phase)
            if st["e"] <= 0:
                event("critical", "Energy exhausted before reaching the habitat (simulated outcome).")
                return False
        return True

    out_segs = _segments(route)
    total_out = sum(s["d"] for s in out_segs) or 1.0
    event("info", f"Departure. Scenario: {scenario}. Battery {battery:.0f} Wh, reserve {reserve:.0f} Wh ({RESERVE_FRACTION:.0%}).")
    if scenario == "energy_overrun":
        event("warning", "SIMULATED disturbance: traction energy x1.6 for the whole traverse.")
    frame(route[0], "outbound")

    done: list[dict] = []
    covered = 0.0
    outcome = "completed"
    reached = False
    replanned = False
    i = 0
    while i < len(out_segs):
        s = out_segs[i]
        frac = covered / total_out
        # --- scenario triggers
        if scenario == "dust_storm" and st["speed_f"] == 1.0 and frac >= 0.3:
            st["speed_f"], st["hotel_f"] = 0.5, 1.25
            event("warning", "SIMULATED dust storm onset: visibility-limited speed x0.5, hotel load x1.25.")
        if scenario == "comm_degradation":
            want = "nominal" if frac < 0.3 else ("degraded" if frac < 0.5 else "lost")
            if want != st["comm"]:
                st["comm"] = want
                event("warning" if want != "nominal" else "info", f"SIMULATED communication state: {want}. "
                      + ("Crew proceeds on the pre-loaded plan and cached maps." if want == "lost" else ""))
        if scenario == "emergency_return" and frac >= 0.5:
            event("critical", "SIMULATED emergency declared. Aborting and backtracking along the driven path.")
            outcome = "aborted_emergency"
            break
        if scenario == "terrain_hazard" and not replanned and frac >= 0.45:
            replanned = True
            ahead = out_segs[min(len(out_segs) - 1, i + max(2, len(out_segs) // 12))]["b"]
            cell = (plan_constraints or {}).get("cell_m", 100.0)
            radius = max(2.5 * cell, 60.0)
            event("warning", f"SIMULATED obstacle reported ahead at {ahead[1]:.5f}N {ahead[0]:.5f}E. Holding 10 min to assess; "
                             f"declaring a {radius:.0f} m no-go zone and re-planning.")
            st["t"] += 600; st["e"] -= v.hotel_power_w * 600 / 3600.0
            frame(s["a"], "outbound")
            try:
                c = plan_constraints or {}
                re = plan_routes((s["a"][0], s["a"][1]), (route[-1][0], route[-1][1]), max_slope_deg=c.get("max_slope_deg", 25.0),
                                 safety_margin=c.get("safety_margin", 0.2), vehicle=v, include_return=False, profiles=["balanced"],
                                 blocked_zones=[(ahead[0], ahead[1], radius)])
                if not re["candidates"]:
                    raise RouteError("no detour")
                new = re["candidates"][0]
                out_segs = out_segs[:i] + _segments(new["geometry"]["coordinates"])
                total_out = sum(x["d"] for x in out_segs)
                event("info", f"Detour found by the route planner: {new['distance_m']:.0f} m remaining to target "
                              f"(real A* re-plan on the {re['dem']['effective_resolution_m']:.0f} m DEM).")
                return_route = None   # planned return passed through the no-go zone's vicinity; backtrack instead
                continue
            except (RouteError, Exception) as ex:  # noqa: BLE001
                event("critical", f"No detour available ({ex}). Aborting and backtracking.")
                outcome = "aborted_no_detour"
                break
        # --- energy rule: always keep enough to get home with margin
        need = backtrack_need(done + [s]) * (1 + safety_margin)
        if st["e"] - _traction_wh(s, v) * st["trac_f"] - need < reserve:
            event("critical", f"Energy rule tripped at {covered:.0f} m: continuing would leave less than the "
                              f"{RESERVE_FRACTION:.0%} reserve after a margin-adjusted return. Turning back.")
            outcome = "aborted_energy"
            break
        advance(s)
        done.append(s)
        covered += s["d"]
        frame(s["b"], "outbound")
        i += 1
    else:
        reached = True

    if reached:
        event("info", f"Arrived at target after {st['t'] / 3600:.2f} h. Science operations for {dwell_min:.0f} min.")
        for obj in objectives or []:
            event("objective", f"Objective addressed (simulated): {obj}")
        st["t"] += dwell_min * 60
        st["e"] -= v.hotel_power_w * st["hotel_f"] * dwell_min / 60.0
        frame(route[-1] if not replanned else out_segs[-1]["b"], "at_target")
        ret_segs = _segments(return_route) if return_route and len(return_route) > 1 else None
        if ret_segs:
            event("info", "Departing on the planned return route.")
            ok = True
            for s in ret_segs:
                advance(s)
                frame(s["b"], "return")
                if st["e"] <= 0:
                    event("critical", "Energy exhausted on the return leg (simulated outcome).")
                    ok = False
                    break
            if not ok:
                outcome = "failed_energy"
        else:
            event("info", "Returning by backtracking along the outbound path.")
            if not drive_back(done, "return"):
                outcome = "failed_energy"
    else:
        if not drive_back(done, "emergency_return" if outcome == "aborted_emergency" else "return"):
            outcome = "failed_energy"

    if outcome != "failed_energy":
        event("info", f"Back at the habitat with {st['e']:.0f} Wh ({100 * st['e'] / battery:.0f}%) after {st['t'] / 3600:.2f} h.")
        if st["e"] < reserve:
            event("warning", "Arrived below the energy reserve.")
    step = max(1, len(frames) // 500)
    thin = frames[::step]
    if thin[-1] is not frames[-1]:
        thin.append(frames[-1])
    return {
        "simulated": True,
        "label": "SIMULATION - model output, not measurements",
        "scenario": scenario, "scenario_description": SCENARIOS[scenario], "outcome": outcome, "target_reached": reached,
        "summary": {"duration_h": round(st["t"] / 3600, 3), "distance_m": round(st["dist"], 1),
                    "energy_used_wh": round(battery - st["e"], 1), "energy_remaining_wh": round(st["e"], 1),
                    "energy_remaining_pct": round(100 * st["e"] / battery, 1), "battery_wh": battery, "reserve_wh": reserve},
        "assumptions": {**v.assumptions(), "battery_wh": battery, "dwell_min": dwell_min, "safety_margin": safety_margin,
                        "terrain": "Real DEM elevations along the planned route",
                        "disturbances": "Scenario disturbances are invented for training/what-if purposes"},
        "frames": thin, "events": events,
    }
