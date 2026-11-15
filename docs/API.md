# MARS-X API reference

All endpoints are under `/api/v1` (router in `backend/app/api.py`). FastAPI generates
interactive OpenAPI documentation at `/docs` (Swagger UI) and the schema at `/openapi.json`.
`GET /` returns `{"name", "docs", "health"}` pointers.

## Conventions

- **Coordinates:** planetocentric latitude, east-positive longitude, in degrees, on the IAU
  2000 Mars sphere (r = 3,396,190 m). Longitude inputs accept -360..360 and are normalised to
  [-180, 180). Latitude inputs accept -90..90.
- **Elevations:** metres relative to the MOLA areoid.
- **Distances:** metres, great-circle on the Mars sphere unless stated otherwise.
- **Provenance labels:** values carry a `kind` such as `latest_observation`,
  `historical_observation`, `derived_estimate` or `simulated`; hazards are labelled as inferred
  from DEM slope.
- **Errors:** `detail` is an object, normally `{"error": "<code>", "message": "..."}`.
  - `422` request validation failure (FastAPI) or invalid domain request
    (`invalid_route_request`, `invalid_simulation`, `unknown_scenario`, ...)
  - `404` `mission_not_found`, `route_not_found`, `plan_not_found`, `dataset_not_found`
  - `503` `elevation_data_unavailable` (DEM could not be fetched or the region is outside DEM
    coverage), `offline`, `nasa_feed_unavailable`
  - `500` `internal_error` for unhandled exceptions
- **CORS:** origins from `MARSX_CORS_ORIGINS`; the `X-Overlay-BBox` header is exposed.

---

## System

### `GET /api/v1/health`

Status, database dialect and number of locations, AI mode (`llm` or `planner`) and model,
offline flag, DEM cache status (`mola_bands_cached`, `mola_cache_mb`, `ctx_dtm_cached`,
`ctx_dtm_mtime`, `cache_dir`), and the coordinate reference (`radius_m`, latitude/longitude
conventions).

## Planet

### `GET /api/v1/planet/layers`

All map layers: the 17 Mars Trek WMTS layers (tile URL template, format, max level, bbox,
mission, instrument, timestamp, resolution, limitations, attribution) followed by MARS-X
computed layers. Also returns `tiling` (`geographic`, level-0 tiles `[2, 1]`,
`EPSG:104905`, radius) and the snapshot `retrieved` time.

### `GET /api/v1/planet/locations`

| Parameter | Type | Default | Notes |
| --- | --- | --- | --- |
| `q` | string, max 80 | - | Name search. When given, returns `{query, results}` (science targets first, then name matches with prefix matches and landing sites ranked first). |
| `kind` | string | - | `nomenclature` or `landing_site` (ignored when `q` is set) |
| `feature_type` | string | - | IAU feature type, e.g. `Crater, craters` (ignored when `q` is set) |
| `limit` | int 1-200 | 25 | |
| `offset` | int >= 0 | 0 | |

Without `q`: `{total, offset, limit, results[]}` ordered by name; each result has `name`, `type`,
`kind`, `lon`, `lat`, `description`, `source`.

### `GET /api/v1/planet/location-info`

Parameters: `lon`, `lat` (required). Returns the point's elevation (value, datum, quality,
dataset, resolution, limitations, or `unavailable`), up to 5 nearest named features within
300 km, count and nearest distance of CRISM/OMEGA hydrous detections within 50 km, rovers whose
latest position is within 100 km, and regional Trek imagery layers covering the point.

### `GET /api/v1/planet/observations`

| Parameter | Type | Default |
| --- | --- | --- |
| `station` | `rems` or `meda` | `rems` |
| `limit` | int 1-700 | 60 |

Station metadata, `provenance` (`live feed`, `local cache (feed unreachable)` or
`bundled snapshot (feed unreachable)`), `retrieved`, `latest` (most recent sol with temperature
and pressure, with `age_days`), `history.sols[]` (newest first) and an `unavailable` list.

### `GET /api/v1/planet/rovers`

Perseverance and Curiosity from the bundled snapshot: name, source, source URL, latest sol,
decimated traverse polyline, latest waypoint, waypoint count, and waypoints thinned to about 150.

### `GET /api/v1/planet/rover-images`

| Parameter | Type | Default |
| --- | --- | --- |
| `rover` | `perseverance` or `curiosity` | `perseverance` |
| `limit` | int 1-24 | 8 |

Newest raw images fetched live from NASA: `sol`, `date`, `camera`, `title`, `image` URL, `link`.
Returns `503` when `MARSX_OFFLINE=true` or the feed is unreachable.

## Terrain

### `GET /api/v1/terrain/elevation`

Parameters: `lon`, `lat`. Returns `elevation_m` (bilinear), `quality` (`measured`,
`interpolated between measurements`, `no data`) and the `dem` description. Uses the Jezero CTX
DTM inside its footprint, MOLA elsewhere.

### `GET /api/v1/terrain/profile`

Parameters: `start_lon`, `start_lat`, `end_lon`, `end_lat` (required), `samples` (2-1000,
default 200; capped to about two samples per DEM cell). Great-circle elevation profile:
`distance_m`, `samples[]` (`distance_m`, `lon`, `lat`, `elevation_m`, along-track `slope_deg`,
`quality`), `ascent_m`, `descent_m`, min/max elevation, `dem`.

### `POST /api/v1/hazards/analyze`

Body (`HazardRequest`): either `bbox` `[west, south, east, north]`, or `center` `{lon, lat}`
plus `radius_km` (0-250). Optional `caution_deg` (default 10), `high_deg` (20),
`max_slope_deg` (30). Returns the analysis summary: `bbox`, `dem`, `cells`, elevation / slope /
roughness statistics, `hazard_fraction` per class, `quality_fraction`, `thresholds_deg`,
`hazard_basis`, and `overlays` (URLs for the five overlay PNGs below). The region is resampled to
at most 250,000 cells, and a MOLA window may not exceed 10 degrees. A `hazard_geometries` row
with basis `inferred` is stored.

### `GET /api/v1/terrain/overlay.png`

Parameters: `kind` (`slope`, `hazard`, `quality`, `elevation`, `roughness`), `west`, `south`,
`east`, `north` (required), `caution` (10), `high` (20), `max_slope` (30). Returns an RGBA PNG
in plate carree covering the analysed grid; the exact bounds are in the `X-Overlay-BBox` header
(`west,south,east,north`). The last 12 analyses are cached in memory.

## Routes

### `POST /api/v1/routes/plan`

Body (`RoutePlanRequest`):

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `start`, `goal` | `{lon, lat}` | required | |
| `weights` | `{distance, slope, roughness, hazard, energy}` each 0-20 | balanced profile | Applied to the `balanced` candidate only |
| `max_slope_deg` | 0-45 | 25 | Hard limit |
| `caution_deg` | 0-45 | 10 | |
| `high_deg` | 0-45 | 20 | Must satisfy caution <= high <= max |
| `safety_margin` | 0-0.8 | 0.2 | Tightens the slope limit for `safest` and the return route; energy margin for return feasibility |
| `unknown_penalty` | 0-20 | 1.0 | Extra cost on interpolated DEM cells |
| `vehicle` | `{mass_kg, rolling_resistance, drivetrain_efficiency, speed_kmh, hotel_power_w, battery_wh}` | 3000 kg, 0.15, 0.7, 8 km/h, 600 W, none | Planning assumptions |
| `include_return` | bool | true | |
| `mission_id` | int | - | Attach stored routes to a mission (must exist) |

Response: `plan_id`, `start`, `goal`, `straight_line_m`, `dem` (with `effective_resolution_m`
and `stride`), `analysis_bbox`, `grid_cells`, `constraints`, `vehicle`, `candidates[]`
(`safest`, `shortest`, `balanced`), `return_route`, `failures[]`, `warnings[]`, `comparison`
(`rows[]` and `recommendation {profile, reason}`), `science_nearby[]` (up to 8 targets within
1.5 km of the first candidate), `algorithm`, `hazard_basis`.

Each candidate and the return route carry: `route_id`, GeoJSON `geometry` (LineString of
`[lon, lat, elevation_m]`), `distance_m`, `ascent_m`, `descent_m`,
`max_along_track_grade_deg`, `max_cell_slope_deg`, `mean_slope_deg`, `mean_roughness_m`,
`hazard_exposure` (fractions of length), `interpolated_fraction`, `energy` (traction, hotel,
total Wh; derived), `duration_h` (derived), `difficulty_index`, `elevation_profile[]`,
`segments[]` (runs of constant hazard and quality), `profile`, `description`, `weights`,
`slope_limit_deg`, `confidence` (`level` and `reasons`), and, if it duplicates an earlier
candidate, `identical_to`. Candidates also carry `return_feasibility`.

Every candidate and the return route are stored as rows in `routes` / `route_segments`. The full
plan is kept in memory only (last 40 plans).

### `GET /api/v1/routes/plans/{plan_id}`

The full in-memory plan. `404 plan_not_found` after a server restart or once evicted.

### `GET /api/v1/routes/{route_id}`

A stored route: `id`, `plan_id`, `mission_id`, `profile`, `distance_m`, `energy_wh`,
`duration_h`, `dem_source`, `geometry`, `metrics` (all candidate fields except `geometry`,
`elevation_profile` and `segments`), `created_at`, `segments[]`.

## Missions

### `GET /api/v1/missions`

Parameters: `limit` (1-200, default 50), `offset`. Newest first: `{total, offset, limit, missions[]}`.

### `POST /api/v1/missions` (201)

Body: `name` (1-200 chars, required), `start` `{lon, lat}` (required), `goal`, `objectives[]`
(max 30), `target_ids[]` (max 30), `constraints` (object). Returns the mission with `routes` and
`logs` (a `created` log entry is added).

### `GET /api/v1/missions/{mission_id}`

The mission with `routes[]` and `logs[]`.

### `PATCH /api/v1/missions/{mission_id}`

Body (all optional): `name`, `status` (`planned`, `active`, `completed`, `aborted`), `goal`,
`objectives`, `target_ids`, `selected_route_id`, `return_route_id`. Referenced routes must exist
and are re-attached to the mission. An `updated` log entry is added.

### `DELETE /api/v1/missions/{mission_id}` (204)

Deletes the mission with its routes and logs.

### `POST /api/v1/missions/{mission_id}/logs` (201)

Body: `kind` (default `note`, max 40 chars), `message` (1-4000 chars), `data` (object).
Returns `id`, `kind`, `message`, `created_at`.

## Science

### `GET /api/v1/science/targets`

| Parameter | Type | Default | Notes |
| --- | --- | --- | --- |
| `lon`, `lat` | number | - | Origin; must be given together |
| `radius_km` | 0-5000 | - | Search radius |
| `q` | string, max 80 | - | Substring filter on name, category and summary |
| `category` | string | - | Substring filter on category |
| `include_gazetteer` | bool | true | Add IAU features (needs origin and radius) |
| `limit` | int 1-100 | 25 | |

Ranks curated literature targets, plus (when an origin and radius are given) rover waypoints
(radius <= 50 km), IAU named features and CRISM/OMEGA detections. Each target has `score`
(0-100), `score_components` (relevance, mineralogy, geology, accessibility, confidence),
`mineral_context`, `distance_m`, `evidence`, `hypothesis`, `coordinate_source`, `datasets`,
`reference_ids`, `kind`. The response includes the `scoring` weights and explanations and a
`disclaimer`.

### `GET /api/v1/science/hydrous`

All hydrous mineral detection points as compact `[lon, lat, instrument]` triples, with `count`,
source, reference and limitations.

### `GET /api/v1/science/references`

The 22 scientific references `{id, citation, url}`.

## Environment

### `GET /api/v1/environment/summary`

For each station (`rems`, `meda`): the observation payload as in `/planet/observations` (30 sols
of history), `solar_context` (top-of-atmosphere solar flux from Ls; derived), and `risk` (derived
0-100 EVA environmental risk index with its factors). Also `radiation` (published MSL RAD
values), `legend` of the provenance kinds, and `generated` time.

## AI assistant

### `GET /api/v1/ai/status`

`mode` (`llm` or `planner`), `model`, the tool list (`name`, `description`), and a `note`
explaining how to enable the language model when in planner mode.

### `POST /api/v1/ai/chat`

Body: `message` (1-4000 chars), `history[]` (`{role: user|assistant, content}`, max 40),
`context` (object; the assistant reads `habitat`, `selected`, `start`, `goal`, `plan_id`,
`selected_profile`). Returns `reply` (Markdown), `mode`, `note`, `model`, `tool_trace[]`
(`tool`, `input`, `ok`, `summary`), `actions[]` for the map (`fly_to`, `show_overlay`,
`show_targets`, `show_plan`, `highlight_return`, `show_simulation`) and `sources[]` (datasets
cited).

## Simulation

### `GET /api/v1/simulation/scenarios`

Scenario ids with descriptions (`nominal`, `terrain_hazard`, `energy_overrun`, `dust_storm`,
`comm_degradation`, `emergency_return`) and defaults (`battery_wh` 40,000, `reserve_fraction`
0.15).

### `POST /api/v1/simulation`

Body (`SimulationRequest`): `plan_id` (and optional `profile`) to simulate a stored plan, or
`route` `[[lon, lat, elev_m], ...]` with optional `return_route`; `scenario` (default
`nominal`); `vehicle`; `battery_wh`; `dwell_min` (0-600, default 30); `safety_margin` (0-0.8,
default 0.2); `objectives[]`; `mission_id` (adds a `simulation` log entry). One of `plan_id` or
`route` is required.

Response: `simulated: true`, `label`, `scenario`, `scenario_description`, `outcome`
(`completed`, `aborted_emergency`, `aborted_no_detour`, `aborted_energy`, `failed_energy`),
`target_reached`, `summary` (duration, distance, energy used/remaining, battery, reserve),
`assumptions`, `frames[]` (time, phase, position, energy, comm state, speed; at most about 500)
and `events[]`.

## Datasets and offline

### `GET /api/v1/datasets`

Parameters: `q` (substring of id, name, mission, instrument, category), `category`. Returns
`count`, `datasets[]` (every column of the `datasets` table) and the list of `missions`.

### `GET /api/v1/datasets/trek-catalog`

Parameters: `q`, `limit` (1-300, default 50), `offset`. Metadata of the Mars Trek product
catalogue snapshot (`productLabel`, `title`, `mission`, `instrument`, `productCat1`, `bbox`,
`data_created_date`, `integrated_as_layer`).

### `GET /api/v1/datasets/{dataset_id}`

One dataset record.

### `GET /api/v1/offline/bundle`

Parameters: `lon`, `lat` (required), `radius_km` (0-150, default 15). One response holding the
region's science targets (up to 60), location info, environment summary, all dataset records and
a terrain analysis summary (or `terrain.unavailable` if the DEM cannot be read).
