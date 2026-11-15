# MARS-X

Mars exploration and mission-planning workstation built on NASA data (NASA Space Apps
hackathon project). It provides terrain analysis and A* route planning on real MOLA and CTX
elevation data, science-target ranking, dated environmental observations, a mission
simulation, and the MARS AI assistant, on a CesiumJS 3D globe.

- Architecture: [ARCHITECTURE.md](ARCHITECTURE.md)
- API reference: [docs/API.md](docs/API.md) (interactive docs at `http://localhost:8000/docs`)
- NASA data sources and limitations: [docs/NASA_DATA_SOURCES.md](docs/NASA_DATA_SOURCES.md)
- Initial state and endpoint checks: [PROJECT_AUDIT.md](PROJECT_AUDIT.md)
- Build order: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)

## Local development

Backend (Python 3.14 used on the build machine; SQLite database created automatically):

```bash
cd backend
py -3.14 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt    # Windows; use .venv/bin/python elsewhere
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

On first use the backend downloads the MOLA bands it needs and the 9.7 MB Jezero CTX DTM into
`backend/data_cache/`. Set `MARSX_OFFLINE=true` to use only cached data and bundled snapshots.

Frontend:

```bash
cd frontend
npm install
npm run dev        # http://localhost:3000, expects the API at NEXT_PUBLIC_API_URL (default http://localhost:8000)
```

Tests:

```bash
cd backend
.venv/Scripts/python -m pytest -q
```

The tests use a temporary SQLite database and the deterministic AI planner. Tests that need the
MOLA or CTX DTMs are skipped when the data is neither reachable nor cached.

Refreshing the bundled NASA snapshots (optional; network required):

```bash
cd backend
.venv/Scripts/python scripts/ingest_nasa.py            # or name steps: layers nomenclature hydrous rovers weather
```

## Docker (PostgreSQL/PostGIS)

```bash
cp .env.example .env      # optionally set ANTHROPIC_API_KEY
docker compose up --build
```

This starts PostGIS (`postgis/postgis:16-3.4`), the backend on port 8000 (it runs
`alembic upgrade head` before uvicorn) and the frontend on port 3000.

**Not verified:** the Docker/PostGIS path was not executed on the build machine because its
Docker daemon was not running. The Alembic migration was run against SQLite only, and its
PostgreSQL DDL was rendered offline but never applied to a real PostGIS server.

## Configuration

Settings are environment variables prefixed `MARSX_` (see `backend/app/config.py`; all of them
are documented in [.env.example](.env.example)). The main ones:

| Variable | Default | Purpose |
| --- | --- | --- |
| `MARSX_DATABASE_URL` | SQLite file `backend/marsx.db` | SQLAlchemy URL; PostgreSQL needs `alembic upgrade head` first |
| `MARSX_CACHE_DIR` | `backend/data_cache` | DEM and feed cache |
| `MARSX_OFFLINE` | `false` | Never touch the network |
| `MARSX_CORS_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Allowed origins |
| `ANTHROPIC_API_KEY` / `MARSX_ANTHROPIC_API_KEY` | unset | Optional; enables Claude in MARS AI |
| `MARSX_AI_MODEL` | `claude-opus-5-5` | Model used in LLM mode |

Without an Anthropic key, MARS AI answers with a deterministic tool planner that calls the same
backend tools. `GET /api/v1/ai/status` reports which mode is active.

## Troubleshooting

- **"An Application Control policy has blocked this file" (Windows).** Some Windows machines
  block native extension DLLs. On the build machine this affected:
  - *rasterio*: not needed locally. `dem.py` reads the CTX GeoTIFF with Pillow when rasterio
    cannot be imported, so do not install `requirements-geo.txt` on such hosts. The Docker image
    installs it.
  - *SQLAlchemy's Cython extension*: install SQLAlchemy as pure Python:
    `DISABLE_SQLALCHEMY_CEXT=1 .venv/Scripts/python -m pip install --no-binary sqlalchemy sqlalchemy==2.1.8`
  - *psycopg's binary libpq wrapper*: only needed for PostgreSQL. Use the default SQLite URL
    locally.
- **`503 elevation_data_unavailable`.** The DEM could not be fetched (no network and not
  cached), the region is poleward of 88 degrees, or a MOLA window is larger than 10 degrees.
  Narrow the region or warm the cache while online.
- **`404 plan_not_found`.** Route plans are held in memory and lost on restart. Stored routes
  remain available under `/api/v1/routes/{id}`.
- **Weather looks old.** REMS/MEDA feeds lag by days to months. Each response states its
  provenance (live feed, local cache or bundled snapshot) and the observation's age.
- **Pip cannot find a pinned version in Docker.** `requirements.txt` pins the versions installed
  under Python 3.14 on the build machine. The image uses Python 3.12 and has not been built, so
  a pin may need adjusting there.
