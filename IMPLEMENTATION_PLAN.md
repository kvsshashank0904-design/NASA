# Implementation plan

## Priority

The first goal was **working end-to-end route planning on real elevation data**: a request
naming two points on Mars returns A* routes computed from NASA DEMs, with honest metrics and
confidence statements. Everything else (science ranking, environment, simulation, the AI
assistant, the 3D interface) builds on that core, so the risky parts came first: whether the
data could be obtained, whether the DEMs could be read without large downloads, and whether the
search was fast enough. Presentation came after.

## Build order followed

1. **Data verification.** Probe the candidate NASA/USGS endpoints and record what responds
   (see `PROJECT_AUDIT.md`). Drop sources that fail (api.nasa.gov rover photos, guessed Trek
   layer names) before any code depends on them.
2. **Ingestion snapshot.** `backend/scripts/ingest_nasa.py` writes small, verified catalogue
   data to `backend/app/data/*.json`: Trek layers and catalogue, nomenclature, hydrous mineral
   detections, rover traverses, weather.
3. **DEM access.** `dem.py`: MOLA MEGDR via HTTP Range requests on raw PDS bands with a `.npy`
   band cache, measured/interpolated flags from the counts product, and the Jezero CTX 20 m DTM
   with a Pillow GeoTIFF reader.
4. **Terrain.** Slope with cos(latitude) spacing, roughness, hazard classes, profiles and PNG
   overlays.
5. **Routing.** Traversability grid, vectorised edge costs, heapq A*, safest/shortest/balanced
   profiles, independent return route, derived energy/duration, confidence and comparison.
6. **Science and environment.** Target scoring with literature-resolved coordinates, location
   info; REMS/MEDA with live/cache/snapshot provenance, published RAD values, derived risk index.
7. **Simulation.** Deterministic mission digital twin with scenarios and the energy turn-back
   rule; the terrain-hazard scenario re-plans with the real A*.
8. **AI tools and agent.** ToolBox over the services, lexical knowledge base, Claude
   tool-calling loop, deterministic planner fallback.
9. **API.** FastAPI router, persistence of routes/missions/logs/hazard analyses, error model.
10. **Tests.** pytest suite (31 tests) through the real app on SQLite with the deterministic
    planner.
11. **Frontend.** Next.js + CesiumJS interface over the API.
12. **Infrastructure and documentation.** Requirements, Alembic migration with the PostGIS Mars
    CRS, Dockerfiles, docker-compose, environment template, data-source, API and architecture
    documents.
13. **Strict audit.** Review every claim in the UI and documentation against the code and data.
