"""API integration tests through the real FastAPI app (SQLite, deterministic AI planner)."""
import pytest

from app.config import settings
from app.services import dem

needs_ctx = pytest.mark.skipif(dem.ctx_grid() is None, reason="Jezero CTX DTM not available")
LANDING = {"lon": 77.4509, "lat": 18.4447}
DELTA = {"lon": 77.4059, "lat": 18.4586}


def test_health_and_crs(client):
    r = client.get("/api/v1/health").json()
    assert r["status"] == "ok" and r["crs"]["radius_m"] == 3396190.0 and r["database"]["locations"] > 1700


def test_layers_have_provenance(client):
    layers = client.get("/api/v1/planet/layers").json()["layers"]
    cats = {x["category"] for x in layers}
    assert {"base", "orbital", "regional", "elevation", "slope", "thermal", "mineral", "hazard", "rover", "route"} <= cats
    for x in layers:
        assert x["title"] and x["description"] is not None and x["attribution"] and x["limitations"]
    wm = [x for x in layers if x["kind"] == "wmts"]
    assert all(x["tile_url"].startswith("https://") and "{z}" in x["tile_url"] for x in wm)
    missions = " ".join(str(x.get("mission")) for x in layers)
    for m in ("Mars Reconnaissance Orbiter", "Mars Global Surveyor", "Mars Odyssey"):
        assert m in missions


def test_location_search_and_pagination(client):
    r = client.get("/api/v1/planet/locations", params={"q": "gale"}).json()["results"]
    gale = next(x for x in r if x["name"] == "Gale")
    assert gale["lon"] == pytest.approx(137.81, abs=0.05) and gale["lat"] == pytest.approx(-5.37, abs=0.05)
    p = client.get("/api/v1/planet/locations", params={"limit": 5, "offset": 10}).json()
    assert p["total"] > 1700 and len(p["results"]) == 5
    assert client.get("/api/v1/planet/locations", params={"limit": 0}).status_code == 422


@needs_ctx
def test_location_info_provenance(client):
    r = client.get("/api/v1/planet/location-info", params=LANDING).json()
    assert r["elevation"]["dataset"].startswith("Mars 2020 TRN CTX") and r["elevation"]["quality"] == "measured"
    assert "planetocentric" in r["crs"]
    assert any(x["rover"].startswith("Perseverance") for x in r["rovers_nearby"])


def test_invalid_coordinates_rejected(client):
    assert client.get("/api/v1/planet/location-info", params={"lon": 10, "lat": 95}).status_code == 422
    assert client.post("/api/v1/routes/plan", json={"start": {"lon": 0, "lat": 0}, "goal": {"lon": 1, "lat": 200}}).status_code == 422
    r = client.post("/api/v1/routes/plan", json={"start": LANDING, "goal": DELTA, "caution_deg": 30, "high_deg": 20})
    assert r.status_code == 422
    assert client.post("/api/v1/routes/plan", json={"start": LANDING, "goal": LANDING}).status_code == 422


@needs_ctx
def test_route_plan_persist_and_simulate(client):
    m = client.post("/api/v1/missions", json={"name": "Delta front sortie", "start": LANDING, "goal": DELTA, "objectives": ["Image delta strata"]})
    assert m.status_code == 201
    mid = m.json()["id"]
    plan = client.post("/api/v1/routes/plan", json={"start": LANDING, "goal": DELTA, "mission_id": mid, "vehicle": {"battery_wh": 40000}}).json()
    assert len(plan["candidates"]) == 3 and plan["return_route"] and plan["comparison"]["recommendation"]["profile"]
    rid = plan["candidates"][0]["route_id"]
    route = client.get(f"/api/v1/routes/{rid}").json()
    assert route["geometry"]["type"] == "LineString" and route["segments"] and route["mission_id"] == mid
    assert client.get("/api/v1/routes/999999").status_code == 404
    up = client.patch(f"/api/v1/missions/{mid}", json={"selected_route_id": rid, "status": "active"}).json()
    assert up["selected_route_id"] == rid and up["status"] == "active"

    sims = {}
    for sc in ("nominal", "terrain_hazard", "energy_overrun", "dust_storm", "comm_degradation", "emergency_return"):
        s = client.post("/api/v1/simulation", json={"plan_id": plan["plan_id"], "profile": "safest", "scenario": sc, "mission_id": mid})
        assert s.status_code == 200, s.text
        sims[sc] = s.json()
        assert sims[sc]["simulated"] is True and "SIMULATION" in sims[sc]["label"] and sims[sc]["frames"]
    assert sims["nominal"]["outcome"] == "completed" and sims["nominal"]["target_reached"]
    assert sims["emergency_return"]["outcome"] == "aborted_emergency" and not sims["emergency_return"]["target_reached"]
    assert sims["energy_overrun"]["summary"]["energy_used_wh"] > sims["nominal"]["summary"]["energy_used_wh"]
    assert sims["dust_storm"]["summary"]["duration_h"] > sims["nominal"]["summary"]["duration_h"]
    assert any("Detour found" in e["message"] for e in sims["terrain_hazard"]["events"])
    assert any(f["comm"] == "lost" for f in sims["comm_degradation"]["frames"])
    tiny = client.post("/api/v1/simulation", json={"plan_id": plan["plan_id"], "scenario": "nominal", "battery_wh": 3000}).json()
    assert tiny["outcome"] == "aborted_energy" and tiny["summary"]["energy_remaining_wh"] > 0
    assert client.post("/api/v1/simulation", json={"plan_id": plan["plan_id"], "scenario": "aliens"}).status_code == 422
    logs = client.get(f"/api/v1/missions/{mid}").json()["logs"]
    assert sum(1 for g in logs if g["kind"] == "simulation") == 6


@needs_ctx
def test_hazard_analysis_and_overlay(client):
    r = client.post("/api/v1/hazards/analyze", json={"center": LANDING, "radius_km": 4}).json()
    assert r["dem"]["id"] == "jezero_ctx_dtm_20m" and abs(sum(r["hazard_fraction"].values()) - 1) < 1e-3
    assert "INFERRED" in r["hazard_basis"]
    png = client.get(r["overlays"]["hazard"])
    assert png.status_code == 200 and png.content[:8] == b"\x89PNG\r\n\x1a\n" and png.headers["x-overlay-bbox"]
    assert client.post("/api/v1/hazards/analyze", json={}).status_code == 422


def test_science_targets_scoring(client):
    r = client.get("/api/v1/science/targets", params={**LANDING, "radius_km": 6}).json()
    assert r["count"] > 3 and "life" in r["disclaimer"]
    for t in r["targets"]:
        assert 0 <= t["score"] <= 100 and set(t["score_components"]) == set(r["scoring"]["weights"]) and t["coordinate_source"]
        assert t["distance_m"] <= 6000
    scores = [t["score"] for t in r["targets"]]
    assert scores == sorted(scores, reverse=True)
    h = client.get("/api/v1/science/hydrous").json()
    assert h["count"] > 1500 and "Carter" in h["reference"]


def test_environment_labels(client):
    r = client.get("/api/v1/environment/summary").json()
    for k in ("rems", "meda"):
        st = r["stations"][k]
        assert st["latest"]["kind"] == "latest_observation" and st["latest"]["terrestrial_date"]
        assert st["history"]["kind"] == "historical_observation" and st["risk"]["kind"] == "derived_estimate"
        assert "not live" in st["latest"]["note"].lower()
    assert r["radiation"]["kind"] == "historical_observation"
    assert r["radiation"]["surface_gcr_dose_equivalent_mSv_per_day"]["value"] == 0.64


def test_datasets_catalog(client):
    r = client.get("/api/v1/datasets").json()
    ids = {d["id"] for d in r["datasets"]}
    assert {"mola_megdr_128", "jezero_ctx_dtm_20m", "hydrous_minerals", "rems_weather", "meda_weather", "rad_surface", "trek_wmts"} <= ids
    for d in r["datasets"]:
        for f in ("source", "source_url", "observation_time", "coverage", "resolution", "data_format", "processing", "limitations"):
            assert d[f], (d["id"], f)
    assert client.get("/api/v1/datasets/nope").status_code == 404
    tc = client.get("/api/v1/datasets/trek-catalog", params={"q": "CRISM"}).json()
    assert tc["total"] >= 2


@needs_ctx
def test_ai_planner_runs_real_tools(client):
    assert client.get("/api/v1/ai/status").json()["mode"] == "planner"
    r = client.post("/api/v1/ai/chat", json={
        "message": "Find an interesting geological research location within 2 km of my habitat. Prioritize safe terrain and make sure I can return.",
        "context": {"habitat": LANDING}}).json()
    tools = [t["tool"] for t in r["tool_trace"]]
    assert tools[0] == "find_science_targets" and "calculate_route" in tools and "generate_return_route" in tools
    assert all(t["ok"] for t in r["tool_trace"])
    plan = next(a for a in reversed(r["actions"]) if a["type"] == "show_plan")["plan"]
    rec = plan["comparison"]["recommendation"]["profile"]
    cand = next(c for c in plan["candidates"] if c["profile"] == rec)
    # every number in the reply must come from the tool output
    assert f"{cand['distance_m'] / 1000:.2f} km" in r["reply"]
    assert "Return" in r["reply"] and "derived" in r["reply"] and "CTX" in r["reply"]
    assert any(s["id"] == "jezero_ctx_dtm_20m" for s in r["sources"])
    assert "proves" not in r["reply"].lower()


def test_ai_planner_other_intents(client):
    w = client.post("/api/v1/ai/chat", json={"message": "What is the weather at Gale crater?"}).json()
    assert "not live weather" in w["reply"] and w["tool_trace"][0]["tool"] == "get_environmental_observations"
    d = client.post("/api/v1/ai/chat", json={"message": "How accurate is the MOLA dataset and what is its resolution?"}).json()
    assert "463" in d["reply"] and any(s["id"] == "mola_megdr_128" for s in d["sources"])
    n = client.post("/api/v1/ai/chat", json={"message": "Simulate a dust storm"}).json()
    assert "no active route plan" in n["reply"].lower()
    assert client.post("/api/v1/ai/chat", json={"message": ""}).status_code == 422


def test_offline_flag_blocks_network_only_features(client):
    settings.offline = True
    try:
        assert client.get("/api/v1/planet/rover-images").status_code == 503
        r = client.get("/api/v1/environment/summary").json()      # still answers from cache/snapshot
        assert r["stations"]["rems"]["latest"]["sol"]
    finally:
        settings.offline = False
