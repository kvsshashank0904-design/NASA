"""Unit tests on synthetic grids (no network) plus checks against the real Jezero CTX DTM."""
import math

import numpy as np
import pytest

from app.mars import MARS_RADIUS_M, great_circle_points, haversine_m, norm_lon, solar_flux_toa
from app.services import dem, routing, terrain
from app.services.dem import Q_MEASURED, Q_NODATA, DemGrid


def synth(z, lat0=0.0, cell_m=100.0):
    z = np.asarray(z, dtype=np.float32)
    d = math.degrees(cell_m / MARS_RADIUS_M)
    lats = lat0 - np.arange(z.shape[0]) * d
    lons = 10.0 + np.arange(z.shape[1]) * d
    q = np.where(np.isnan(z), Q_NODATA, Q_MEASURED).astype(np.uint8)
    return DemGrid(z, q, lats, lons, "ctx")


def test_haversine_uses_mars_radius():
    # a quarter of the circumference of Mars, not Earth
    assert haversine_m(0, 0, 90, 0) == pytest.approx(math.pi * MARS_RADIUS_M / 2, rel=1e-9)
    assert haversine_m(0, 0, 0, 1) == pytest.approx(59_274.7, abs=1.0)   # ~59.3 km per degree on Mars


def test_lon_normalisation_and_great_circle():
    assert norm_lon(282.0) == pytest.approx(-78.0)
    assert norm_lon(-180.0) == -180.0
    pts = great_circle_points(179.0, 10, -179.0, 10, 5)     # crosses the antimeridian
    assert pts[0] == pytest.approx((179.0, 10)) and pts[-1] == pytest.approx((-179.0, 10))
    assert abs(pts[2][0]) == pytest.approx(180.0, abs=1e-6)


def test_solar_flux_range():
    assert 700 < solar_flux_toa(251) < 730     # perihelion
    assert 480 < solar_flux_toa(71) < 500      # aphelion


def test_slope_of_known_plane():
    n = 40
    rows = np.arange(n)[:, None] * np.ones((1, n))
    g = synth(rows * 100.0 * math.tan(math.radians(10)))     # 10 deg north-south ramp
    s = terrain.slope_deg(g)
    assert np.nanmean(s) == pytest.approx(10.0, abs=0.05)


def test_slope_accounts_for_cos_latitude():
    n = 40
    cols = np.ones((n, 1)) * np.arange(n)[None, :]
    z = cols * 5.0                                           # 5 m rise per column
    eq, hi = synth(z, lat0=0.0), synth(z, lat0=60.0)
    # the same angular spacing is half the ground distance at 60 deg latitude, so the slope must be steeper
    assert np.nanmean(terrain.slope_deg(hi)) > 1.8 * np.nanmean(terrain.slope_deg(eq))


def _cost(tg, p, weights):
    costs = tg.edge_costs(weights)
    tot = 0.0
    for (r0, c0), (r1, c1) in zip(p, p[1:]):
        tot += costs[routing.DIRS.index((r1 - r0, c1 - c0))][r0 * tg.W + c0]
    return tot


def test_astar_goes_around_wall_and_matches_dijkstra():
    z = np.zeros((40, 40), dtype=np.float32)
    z[5:35, 20] = 500.0                                       # cliff wall with gaps at both ends
    g = synth(z)
    tg = routing.TraversabilityGrid(g, 25, 10, 20, 1.0, routing.Vehicle())
    path = tg.astar((20, 5), (20, 35), routing.PROFILES["shortest"])
    assert path and path[0] == (20, 5) and path[-1] == (20, 35)
    assert all(not tg.blocked[r, c] for r, c in path)
    assert any(r < 5 or r >= 35 for r, c in path)            # had to detour through a gap
    # optimality: A* with the admissible heuristic equals uniform-cost search (heuristic disabled)
    wb = routing.PROFILES["balanced"]
    a = tg.astar((20, 5), (20, 35), wb)
    xs, ys = tg.x, tg.y
    tg.x, tg.y = [0.0] * tg.W, [0.0] * tg.H
    d = tg.astar((20, 5), (20, 35), wb)
    tg.x, tg.y = xs, ys
    assert _cost(tg, a, wb) == pytest.approx(_cost(tg, d, wb), rel=1e-9)


def test_astar_reports_no_path_when_enclosed():
    z = np.zeros((30, 30), dtype=np.float32)
    z[:, 15] = 800.0
    tg = routing.TraversabilityGrid(synth(z), 25, 10, 20, 1.0, routing.Vehicle())
    assert tg.astar((15, 3), (15, 27), routing.PROFILES["shortest"]) is None


def test_nodata_is_impassable_and_flagged():
    z = np.zeros((20, 20), dtype=np.float32)
    z[8:12, :] = np.nan
    g = synth(z)
    h = terrain.hazard_classes(g, terrain.slope_deg(g))
    assert (h[8:12, :] == terrain.H_UNKNOWN).all()
    tg = routing.TraversabilityGrid(g, 25, 10, 20, 1.0, routing.Vehicle())
    assert tg.astar((2, 10), (18, 10), routing.PROFILES["shortest"]) is None


def test_blocked_zone_forces_detour():
    g = synth(np.zeros((30, 30), dtype=np.float32))
    mid = (float(g.lons[15]), float(g.lats[15]), 350.0)
    tg = routing.TraversabilityGrid(g, 25, 10, 20, 1.0, routing.Vehicle(), blocked_zones=[mid])
    path = tg.astar((15, 2), (15, 28), routing.PROFILES["shortest"])
    assert path and (15, 15) not in path


def test_energy_is_direction_dependent():
    n = 30
    cols = np.ones((n, 1)) * np.arange(n)[None, :]
    g = synth(cols * 100.0 * math.tan(math.radians(6)))       # uphill to the east
    tg = routing.TraversabilityGrid(g, 25, 10, 20, 1.0, routing.Vehicle())
    up = routing._metrics(tg, [(15, c) for c in range(2, 28)], routing.Vehicle())
    down = routing._metrics(tg, [(15, c) for c in range(27, 1, -1)], routing.Vehicle())
    assert up["energy"]["traction_wh"] > 1.5 * down["energy"]["traction_wh"]
    assert up["ascent_m"] == pytest.approx(down["descent_m"], rel=1e-6)


# ---- real data (Jezero CTX DTM, 9.7 MB, cached after first download)

needs_ctx = pytest.mark.skipif(dem.ctx_grid() is None, reason="Jezero CTX DTM not available (no network and not cached)")


@needs_ctx
def test_ctx_georeferencing_matches_published_footprint():
    b = dem.ctx_footprint()
    assert b == pytest.approx([77.1605, 18.2110, 77.6990, 18.7212], abs=2e-3)   # footprint from the Mars Trek catalogue
    g = dem.ctx_grid()
    assert g.dy_m == pytest.approx(20.0, abs=0.01)
    assert float(g.dx_m().mean()) == pytest.approx(20.0 * math.cos(math.radians(18.47)), abs=0.1)


@needs_ctx
def test_perseverance_landing_site_elevation():
    e = dem.sample_elevation(77.4509, 18.4447)
    assert e["source"]["id"] == "jezero_ctx_dtm_20m"
    assert e["elevation_m"] == pytest.approx(-2569, abs=15)   # published landing-site elevation


@needs_ctx
def test_jezero_route_plan_properties():
    plan = routing.plan_routes((77.4509, 18.4447), (77.4059, 18.4586))
    assert plan["dem"]["id"] == "jezero_ctx_dtm_20m"
    by = {c["profile"]: c for c in plan["candidates"]}
    assert set(by) == {"safest", "shortest", "balanced"}
    assert by["shortest"]["distance_m"] <= by["safest"]["distance_m"] + 1e-6
    assert by["shortest"]["distance_m"] >= plan["straight_line_m"] * 0.999

    def haz(c):
        return c["hazard_exposure"]["caution"] + c["hazard_exposure"]["high"]
    assert haz(by["safest"]) <= haz(by["shortest"]) + 1e-9
    for c in plan["candidates"]:
        assert c["max_cell_slope_deg"] <= c["slope_limit_deg"] + 1e-6
        assert c["energy"]["kind"] == "derived estimate"
        assert c["return_feasibility"]["feasible"] is True
    ret = plan["return_route"]
    assert ret and ret["geometry"]["coordinates"][0][:2] == pytest.approx(by["safest"]["geometry"]["coordinates"][-1][:2], abs=1e-3)


@needs_ctx
def test_short_trip_is_flagged_insufficient_resolution():
    plan = routing.plan_routes((77.4509, 18.4447), (77.4512, 18.4449))
    assert any("INSUFFICIENT RESOLUTION" in w for w in plan["warnings"])


def test_route_rejects_bad_input():
    with pytest.raises(routing.RouteError):
        routing.plan_routes((77.45, 18.44), (77.45, 18.44))
    with pytest.raises(routing.RouteError):
        routing.plan_routes((77.45, 18.44), (77.40, 18.45), weights={"slope": -1})
