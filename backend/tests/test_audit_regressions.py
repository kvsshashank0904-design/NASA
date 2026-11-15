"""Regression tests for defects found in the strict technical audit."""
import pytest

from app.services import catalog, dem, routing
from app.services.ai_agent import _find_places, _radius_km

needs_ctx = pytest.mark.skipif(dem.ctx_grid() is None, reason="Jezero CTX DTM not available")


def _cand(profile, dist, hazard, slope, identical_to=None):
    c = {"profile": profile, "distance_m": dist, "duration_h": {"value": 1.0}, "energy": {"total_wh": 1000.0}, "mean_slope_deg": 2.0,
         "max_cell_slope_deg": slope, "hazard_exposure": {"nominal": 1 - hazard, "caution": hazard, "high": 0.0}, "interpolated_fraction": 0.0,
         "difficulty_index": {"value": 10.0}, "confidence": {"level": "moderate"}, "return_feasibility": {"feasible": True}}
    if identical_to:
        c["identical_to"] = identical_to
    return c


def test_recommendation_never_points_at_a_duplicate_path():
    r = routing.compare([_cand("safest", 500, 0.0, 8), _cand("shortest", 499, 0.0, 9), _cand("balanced", 500, 0.0, 8, identical_to="safest")])
    assert r["recommendation"]["profile"] == "safest"
    assert "0 m more" not in r["recommendation"]["reason"]


def test_recommendation_when_all_paths_converge():
    r = routing.compare([_cand("safest", 500, 0.0, 8), _cand("shortest", 500, 0.0, 8, identical_to="safest"), _cand("balanced", 500, 0.0, 8, identical_to="safest")])
    assert r["recommendation"]["profile"] == "safest" and "converge" in r["recommendation"]["reason"]


def test_infeasible_return_is_not_recommended():
    bad = _cand("shortest", 400, 0.0, 5)
    bad["return_feasibility"] = {"feasible": False}
    r = routing.compare([_cand("safest", 500, 0.1, 8), bad])
    assert r["recommendation"]["profile"] == "safest"


def test_overlong_route_is_a_validation_error_not_a_data_outage(client):
    with pytest.raises(routing.RouteError, match="legs"):
        routing.plan_routes((0.0, 0.0), (40.0, 10.0))
    r = client.post("/api/v1/routes/plan", json={"start": {"lon": 0, "lat": 0}, "goal": {"lon": 40, "lat": 10}})
    assert r.status_code == 422 and r.json()["detail"]["error"] == "invalid_route_request"


def test_layer_levels_are_verified_and_sources_are_honest():
    layers = catalog.trek_layers()["layers"]
    assert len(layers) >= 19
    for lyr in layers:
        assert 0 <= lyr["max_level"] <= lyr["advertised_max_level"]
        if "astro.arcgis.com" in lyr["tile_url"]:
            assert "Esri" in lyr["source"]            # not mislabelled as a Trek-hosted tile service
    by = {lyr["id"]: lyr for lyr in layers}
    assert by["Mars_Viking_MDIM21_ClrMosaic_global_232m"]["max_level"] == 7      # capabilities advertise 9; tiles stop at 7
    crism = [lyr for lyr in layers if lyr["instrument"] == "CRISM"]
    assert len(crism) == 2 and all("indicator" in lyr["limitations"].lower() for lyr in crism)


def test_planner_place_aliases_resolve_to_catalogue_coordinates():
    places = _find_places("Plan a route from the Perseverance landing site to the delta front")
    assert [p["name"].split(" (")[0] for p in places] == ["Octavia E. Butler Landing", "Western delta front"]
    targets = {t["name"]: t for t in catalog.resolve_targets()}
    for p in places:
        assert (p["lon"], p["lat"]) == (targets[p["name"]]["lon"], targets[p["name"]]["lat"])
    # the bare rover name still means the rover's latest position, and is not shadowed
    assert _find_places("where is perseverance now")[0]["name"].startswith("Perseverance - latest")


def test_radius_parsing_units():
    assert _radius_km("within 2 km of my habitat", 5) == 2
    assert _radius_km("within 800 m of here", 5) == pytest.approx(0.8)
    assert _radius_km("somewhere close", 5) == 5


@needs_ctx
def test_ai_does_not_assert_life(client):
    r = client.post("/api/v1/ai/chat", json={"message": "Is there evidence of life at Cheyava Falls?"}).json()
    low = r["reply"].lower()
    assert "no evidence of past or present life" in low and "potential" in low
    assert "proves" not in low and "confirmed life" not in low


def test_mola_plan_carries_resolution_warning(client):
    try:
        plan = routing.plan_routes((137.4417, -4.5895), (137.62, -4.9), include_return=False, profiles=["shortest"])
    except dem.DemUnavailable:
        pytest.skip("PDS MOLA not reachable and not cached")
    assert plan["dem"]["id"] == "mola_megdr_128"
    assert any(w.startswith("MOLA-ONLY TERRAIN") for w in plan["warnings"])
    assert plan["candidates"][0]["confidence"]["level"] == "low"
