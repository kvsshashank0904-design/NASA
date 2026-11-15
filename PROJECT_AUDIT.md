# Project audit: initial state

Record of what existed when MARS-X work started, and of the external endpoint checks that
shaped the design.

## Workspace

- The workspace (`C:\Users\DELL\Desktop\hackathon`) was empty: no source code, and no supplied
  images, datasets or PDFs. All data in MARS-X therefore comes from public NASA/USGS services,
  fetched by `backend/scripts/ingest_nasa.py` (snapshots) or lazily at runtime (DEMs, feeds).

## Toolchain found

| Tool | State |
| --- | --- |
| Node.js | 22 (v22.23.2) |
| Python | 3.14 (`py` launcher, 3.14.7) |
| Docker | CLI installed (Docker Desktop 29.8.0); daemon not running, so no containers could be run |
| PostgreSQL client (`psql`) | Not installed; no PostgreSQL server available |

Consequences: local development uses SQLite, and the Docker/PostGIS deployment files were
written but not executed. Windows Application Control on the machine also blocks some native
extension DLLs (rasterio, SQLAlchemy's Cython extension, psycopg's binary `pq` module). This led
to the Pillow GeoTIFF fallback and a pure-Python SQLAlchemy install.

## Endpoint verification (2026-11-14)

### Working

- **NASA Mars Trek WMTS** tile services and `WMTSCapabilities.xml` for the 17 integrated layers,
  and the **Mars Trek search index** (`TrekServices/ws/index/eq/searchItems`), used for the
  product catalogue and the nomenclature subset.
- **PDS Geosciences Node MOLA MEGDR** (`meg128` `.img` products), with HTTP `Range` request
  support. This made the band-wise lazy download in `dem.py` possible.
- **USGS Astrogeology Mars 2020 TRN Jezero CTX DTM**, a 9.7 MB GeoTIFF.
- **mars.nasa.gov REMS and MEDA weather feeds** (`rss/api/?feed=weather&category=msl|mars2020`).
- **Rover MMGIS traverse JSON** (Perseverance `M20_waypoints.json` / `M20_traverse.json`,
  Curiosity `MSL_waypoints.json` / `MSL_traverse.json`).
- **Raw image feeds** (`rss/api/?feed=raw_images&category=mars2020` for Perseverance,
  `api/v1/raw_image_items/` for Curiosity).

### Not working

- **api.nasa.gov Mars Rover Photos API (`mars-photos`)**: returned HTTP 404. It is not used;
  the raw image feeds above replace it.
- **Several guessed Mars Trek layer names**: returned HTTP 404. Only layer labels confirmed
  through the Trek catalogue and their capabilities documents are in `trek_layers.json`.
