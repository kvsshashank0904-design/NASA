# MARS-X architecture

MARS-X is a Mars exploration and mission-planning workstation: a FastAPI backend that turns
NASA elevation, imagery, mineralogy, rover and environment data into terrain analysis, route
plans, science-target rankings and mission simulations, and a Next.js + CesiumJS frontend that
renders them on a 3D globe.

## Components

```
backend/
  app/main.py            FastAPI app: lifespan (init_db), CORS, access log, error handler
  app/api.py             REST router mounted at /api/v1 (see docs/API.md)
  app/config.py          Settings from MARSX_* environment variables
  app/db.py, models.py   SQLAlchemy engine/session and ORM tables
  app/seed.py            Creates tables (SQLite) and loads catalogue data; idempotent
  app/mars.py            Mars constants and spherical geometry (no Earth constants)
  app/schemas.py         Pydantic request models
  app/services/
    dem.py               DEM access: MOLA MEGDR (HTTP Range + band cache), Jezero CTX DTM
    terrain.py           Slope, roughness, hazard classes, profiles, PNG overlays
    routing.py           Traversability grid + A* route planner, metrics, comparison
    science.py           Target search and scoring, location info, name search
    environment.py       REMS/MEDA feeds with fallbacks, RAD constants, derived risk index
    simulation.py        Deterministic mission digital twin
    catalog.py           Dataset provenance, layers, references, landing sites, curated targets
    ai_tools.py          MARS AI tool layer (ToolBox) and lexical knowledge base
    ai_agent.py          Claude tool-calling loop and deterministic planner
  app/data/*.json        NASA snapshots written by scripts/ingest_nasa.py
  alembic/               Migrations (PostgreSQL/PostGIS path)
frontend/                Next.js 16 + TypeScript + Tailwind 4 + CesiumJS
docker-compose.yml       PostGIS + backend + frontend
```

## Data flow

1. **Ingestion (offline, once).** `backend/scripts/ingest_nasa.py` downloads catalogue-sized
   resources (a few MB) and writes `backend/app/data/*.json`: Trek layer capabilities and the
   Trek product catalogue, the IAU nomenclature subset, CRISM/OMEGA hydrous detections, rover
   waypoints and traverses, and REMS/MEDA weather. These snapshots are committed with the code.
2. **Startup.** `init_db()` creates tables on SQLite (`Base.metadata.create_all`) or relies on
   `alembic upgrade head` on PostgreSQL, then loads datasets, references, locations (gazetteer
   plus nine landing sites), curated science targets and weather observations if their tables
   are empty. On PostgreSQL it also fills any `geom` column that is still NULL.
3. **Requests.**
   - Map imagery: the browser streams Mars Trek WMTS tiles directly; the backend only supplies
     the layer list.
   - Elevation: `dem.get_dem()` returns the best grid for a bounding box, fetching and caching
     raw data on first use.
   - Terrain, routing, science and simulation services compute results from those grids and the
     snapshots, then the API persists routes, hazard analyses and mission logs.
   - Weather: fetched live with a 6 h TTL, then a cache file, then the bundled snapshot.
4. **In-memory state** (per process, lost on restart): the last 40 route plans
   (`ai_tools.PLAN_STORE`), the last 12 terrain analyses (overlay cache in `api.py`), up to 48
   MOLA bands, and the loaded CTX grid.

## DEM access (`app/services/dem.py`)

Two verified sources, both plate carree on the Mars sphere, both relative to the MOLA areoid.

**MOLA MEGDR 128 px/deg (463 m).** The PDS `.IMG` files are raw big-endian int16 rasters in
16 tiles of 44 deg x 90 deg (5632 x 11520 px). Rather than downloading whole tiles (about
130 MB each), the backend:

- maps a bounding box to global rows (from 88N) and columns (from 0E), splitting at tile and
  antimeridian boundaries;
- for each 1-degree latitude band (128 rows) it touches, issues an HTTP `Range` request for
  exactly that band's bytes from both the topography (`megt...hb.img`) and counts
  (`megc...hb.img`) products;
- stores each band as `<cache>/mola128/<name>_bNN.npy` and keeps up to 48 bands in memory,
  under a lock;
- flags pixels with zero laser shots as interpolated.

Windows are limited to 10 degrees per side and clamped to 88S-88N.

**Mars 2020 TRN CTX DTM, Jezero (20 m).** A 9.7 MB GeoTIFF downloaded once into the cache. It is
read with rasterio if importable, otherwise with Pillow using the GeoTIFF ModelPixelScale and
ModelTiepoint tags. Projected metres convert to degrees with lon = x/R, lat = y/R. `get_dem()`
returns a CTX window when the request lies inside the footprint and is less than half no-data,
and MOLA otherwise. The route planner also shrinks its padded window to the CTX footprint when
both endpoints are inside Jezero, rather than falling back to MOLA.

`DemGrid` carries elevation, a quality grid (measured / interpolated / no data), cell-centre
latitudes and longitudes, and helpers for bilinear sampling, indexing, longitude unwrapping and
block-mean downsampling. Downsampling keeps the worst quality flag in each block.

## Terrain analysis (`app/services/terrain.py`)

- **Slope:** central differences (`numpy.gradient`) after nearest-neighbour filling of NaN;
  north-south spacing `dy = R * dlat`, east-west spacing `dx = R * dlon * cos(lat)` per row.
- **Roughness:** RMS residual from the 3 x 3 local mean, i.e. relief at the DEM pixel scale
  (not rock abundance).
- **Hazard classes:** nominal, caution (>= 10 deg), high (>= 20), impassable (>= 30), unknown
  (no data). The thresholds are request parameters; they are planning assumptions, not NASA
  flight rules. Every response labels hazards as inferred from DEM slope.
- **Overlays:** RGBA PNGs (slope, hazard, quality, elevation, roughness) rendered with Pillow;
  small rasters are upscaled with nearest-neighbour sampling.

## Route planning (`app/services/routing.py`)

**Analysis window.** A box around start and goal padded by max(0.35 x distance, 1,500 m), with
longitude unwrapped across the antimeridian. The DEM is resampled by an integer stride so the
grid has at most 90,000 cells. The plan warns when the trip spans fewer than 3 cells or when the
DEM was resampled.

**Traversability grid.** From the DEM it computes slope, roughness and hazard class. Blocked
cells are impassable or unknown cells, NaN cells, and optional no-go discs `(lon, lat, radius_m)`
used by the simulation's re-plan. For each of the 8 neighbour directions it precomputes NumPy
arrays over the whole grid:

- `d3`: 3-D edge length, hypot(horizontal, dz), where horizontal = hypot(dr*dy, dc*dx(row))
- `S`: ((slope_a/limit + slope_b/limit) / 2)^2
- `R`: mean of clip(roughness / (0.1 x cell size), 0, 1) at both cells
- `H`: mean hazard penalty at both cells (caution 0.5, high 2.0), plus `unknown_penalty` on
  interpolated cells
- `E`: max(0, cos t + sin t / c_rr), traction effort relative to flat ground (t = edge grade)
- `ok`: the edge is allowed only if neither cell is blocked, dz is defined, and the along-edge
  grade does not exceed the slope limit

**Cost function.**

```
C(a->b) = d3 * (w_d + w_s*S + w_r*R + w_h*H + w_e*E)        (infinite where not ok)
```

The weights come from the profile: `safest` (0.3, 4.0, 2.0, 6.0, 0.5), `shortest`
(1, 0, 0, 0, 0), `balanced` (1, 1.5, 1, 2, 1, or the request's `weights`). For each weight set,
`edge_costs()` flattens the 8 arrays into plain Python lists once per search.

**A\*.** 8-connected search on flat cell indices with `heapq`, a `bytearray` closed set and
best-cost/parent lists. The heuristic is `w_d` x the planar distance to the goal, using the
grid's smallest east-west spacing for x, so it never overestimates. Every bracketed term is at
least `w_d`, so the heuristic is admissible and consistent. Start and goal snap to the nearest
unblocked cell within 3 cells.

**Candidates.** `safest` runs on a second grid whose slope limit is reduced by the safety margin
(limit x (1 - margin)), with caution/high thresholds tightened to at most 0.5x / 0.8x that
limit. If no path exists there, it falls back to the hard limit and adds a warning. `shortest`
and `balanced` use the hard limit. Identical geometries are marked `identical_to`. An
independent return route (goal to start) uses the safest weights on the safety-margin grid, then
the hard-limit grid.

**Metrics** (all labelled derived estimates): 3-D distance, ascent, descent, maximum grade,
mean slope and roughness, hazard exposure by length, interpolated fraction, and traction energy
m g d max(0, c_rr cos t + sin t) / efficiency. Hotel energy is power x time, duration assumes a
constant speed, and the difficulty index is 100 x min(1, 0.5 mean_slope/limit + 0.3(0.5 caution
+ high) + 0.2 roughness/ref). Confidence is `moderate` on CTX, `low` on MOLA or when more than
25% of the route is interpolated, and always states that sub-pixel hazards are not represented.
Return feasibility requires a return path and, when a battery is given, (outbound + return
energy) x (1 + margin) <= battery. `compare()` recommends, among return-feasible candidates, the
lowest hazard exposure, then difficulty, then energy.

## Science, environment and simulation

- **Science targets** (`science.py`): score = 100 x (0.30 relevance + 0.20 mineralogy +
  0.20 geology + 0.20 accessibility + 0.10 confidence). Mineralogy counts CRISM/OMEGA detections
  within 25 km, saturating at 5, with a 0.6 floor when the literature reports minerals.
  Accessibility is distance-based only. Curated target coordinates are resolved from the
  gazetteer or rover localisation, never typed in.
- **Environment** (`environment.py`): REMS/MEDA latest and historical sols with provenance and
  age. Also the published RAD constants, a top-of-atmosphere solar flux from Ls, and a heuristic
  EVA risk index, all labelled by kind.
- **Simulation** (`simulation.py`): steps along the route geometry with a constant-speed and
  energy model, a 15% battery reserve and a turn-back rule (continue only if the margin-adjusted
  backtrack energy still leaves the reserve). Scenarios inject disturbances; `terrain_hazard`
  re-runs the real A* planner around a no-go zone. Output is labelled simulated.

## MARS AI design

`ai_tools.ToolBox` exposes 12 tools: search_locations, get_location_info,
get_terrain_profile, get_hazard_assessment, find_science_targets, calculate_route,
compare_routes, generate_return_route, get_environmental_observations, get_dataset_metadata,
simulate_mission_scenario and search_knowledge_base. Each is a thin wrapper over a backend
service. The ToolBox records a trace, map actions (`fly_to`, `show_overlay`, `show_targets`,
`show_plan`, `highlight_return`, `show_simulation`) and the datasets cited. Two interchangeable
"brains" drive the same ToolBox:

- **LLM mode** (when `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` or `MARSX_ANTHROPIC_API_KEY`
  is set and not offline). A Claude tool-calling loop through the Anthropic Messages API (model
  `MARSX_AI_MODEL`, default `claude-opus-5-5`). It sends the system prompt, the last 12 history
  messages and a mission-context block, and runs up to `MARSX_AI_MAX_TOOL_ROUNDS` (8) rounds.
  Each round executes the requested tools and returns JSON results (truncated to 60,000
  characters). The system prompt requires tools as the only source of numbers, provenance
  labels, and separation of evidence from hypothesis. Any API exception falls back to planner
  mode for that request.
- **Planner mode.** A deterministic intent router: regular expressions for simulation,
  environment, science missions, point-to-point routes, return routes, hazards, dataset
  questions and location info, with a knowledge-base fallback. Place names are resolved against
  curated targets, landing sites and the gazetteer, and coordinates are parsed from text. It
  calls the same tools and writes its answer only from their outputs.

**Knowledge base.** Documents are built from the dataset records, layers, curated targets, the
routing method docstring and the RAD summary. Retrieval is lexical: tokens with stop-word
removal, saturated term frequency tf/(tf+1.5) x log(1 + N/(1+df)), and a 1.5x boost for title
matches.

## Database schema

| Table | Purpose |
| --- | --- |
| `datasets` | Provenance of each integrated dataset (mission, instrument, source URL, time, coverage, resolution, format, processing, limitations, integration mode) |
| `scientific_references` | Citations and DOIs |
| `locations` | IAU named features and landing sites (lon, lat, type, source) |
| `science_targets` | Curated targets with evidence, hypothesis, minerals, score priors, coordinate source |
| `observations` | REMS/MEDA per-sol values (JSON) by station and sol |
| `missions` | Mission records, objectives, constraints, selected/return route ids |
| `routes`, `route_segments` | Planned routes (GeoJSON geometry and metrics) and their constant-hazard/quality segments |
| `hazard_geometries` | Analysed or simulated hazard bounding boxes with basis `inferred` or `simulated` |
| `mission_logs` | Mission event log |
| `cached_resources` | Defined in the schema; not written by the current code |

On PostgreSQL the Alembic migration (`backend/alembic/versions/0001_initial.py`) also installs
PostGIS. It registers SRID 949900 (GCS Mars 2000 sphere,
`+proj=longlat +a=3396190 +b=3396190 +no_defs`), adds `geom` Point columns to `locations` and
`science_targets` and a LineString column to `routes`, with GiST indexes, and adds triggers that
derive `geom` from lon/lat or the route GeoJSON on insert and update. The application code does
not query `geom`; distances are computed in Python.

## Mars coordinate handling

- **Sphere, not the biaxial ellipsoid.** Mars Trek tiles, the MOLA MEGDR and the Mars 2020 CTX
  DTM are all referenced to the IAU 2000 sphere (r = 3,396,190 m) with planetocentric latitude
  and east-positive longitude. Using the same sphere everywhere avoids mixing datums.
  `app/mars.py` holds the constants and haversine and great-circle routines, and no code path
  uses Earth (WGS84) constants.
- **cos(latitude) scaling.** Both DEMs are plate carree, so east-west ground spacing per row is
  `R * dlon * cos(lat)`. It is applied in slope computation, edge lengths and region sizing.
- **No PostGIS `geography`.** `geography` always computes on Earth's WGS84 spheroid, which would
  make every distance and area wrong. Only `geometry` with the custom Mars SRID is used, for
  indexing.
- Longitudes are normalised to [-180, 180) at the API boundary. DEM grids unwrap longitudes
  locally so windows can cross the antimeridian.

## Deviations from the originally requested stack

| Requested | Used | Reason |
| --- | --- | --- |
| NetworkX for routing | Custom `heapq` A* over NumPy edge-cost arrays | No graph-construction cost (a 90,000-cell grid would need about 720,000 edge objects). Edge costs are computed vectorised in NumPy, and the search loop runs over flat lists. |
| GDAL / rasterio | rasterio optional; Pillow fallback | The build machine's Application Control policy blocks rasterio's native DLLs. The one GeoTIFF used needs only the pixel scale and tiepoint tags. rasterio is installed in the Docker image (`requirements-geo.txt`). |
| PostgreSQL + PostGIS | SQLite by default for local development; PostGIS in Docker | No PostgreSQL server was available on the build machine. The schema is portable, and PostGIS-specific parts live only in the Alembic migration. |
| Vector store with embeddings | Lexical TF-IDF-style retrieval | The corpus is small (dataset records, layers, curated targets, method notes). Lexical retrieval needs no embedding model or network and works offline and deterministically. |

## Frontend

<!-- FRONTEND: to be completed -->

## Deployment

`docker-compose.yml` runs `postgis/postgis:16-3.4` (healthchecked, named volume), the backend
(`alembic upgrade head`, then uvicorn on port 8000, NASA cache on a named volume) and the
frontend (port 3000, `NEXT_PUBLIC_API_URL` baked in at build time). The Docker/PostGIS path was
not executed on the build machine because its Docker daemon was not running. Only the SQLite
path has been run (application, 31 tests, and the Alembic migration).
