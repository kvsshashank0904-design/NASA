# NASA data sources in MARS-X

This document lists every external dataset the MARS-X backend uses, taken from
`DATASETS` in `backend/app/services/catalog.py` and the Mars Trek layer list in
`backend/app/data/trek_layers.json`. The same metadata is served at runtime by
`GET /api/v1/datasets` and `GET /api/v1/planet/layers`.

All horizontal coordinates are planetocentric latitude and east-positive longitude
on the IAU 2000 Mars sphere (r = 3,396,190 m). Elevations are metres relative to the
MOLA areoid.

## Access modes

| Mode | Meaning |
| --- | --- |
| live | Fetched from the NASA service at request time (browser for map tiles, backend for feeds). |
| snapshot | Downloaded once by `backend/scripts/ingest_nasa.py` and bundled as JSON in `backend/app/data/`. In the repository, the nomenclature, hydrous-mineral, rover and weather snapshots were retrieved on 2026-11-14 (11:02 UTC); the Trek layer list (`trek_layers.json`) and Trek product catalogue (`trek_catalog.json`) were re-ingested on 2026-11-15 (06:00 UTC). |
| lazy-cache | Large raster fetched by the backend on first use, then cached under `MARSX_CACHE_DIR` (default `backend/data_cache`). |
| reference | Published values from the literature, used verbatim as constants. |

Bundled snapshot sizes (from the files in `backend/app/data/`): 1,783 named features,
1,642 hydrous mineral detection points (1,204 CRISM, 438 OMEGA), 554 Perseverance and
1,389 Curiosity end-of-drive waypoints, 700 REMS sols (newest sol 4995, 2026-08-25),
7 MEDA sols (2024-04-21 to 2024-04-27), 19 Trek map layers and metadata for 225 Trek
catalogue products.

---

## Elevation

### MOLA MEGDR, 128 px/deg (`mola_megdr_128`)

- Mission / instrument: Mars Global Surveyor / MOLA (Mars Orbiter Laser Altimeter)
- Source: NASA PDS Geosciences Node, product set MGS-M-MOLA-5-MEGDR-L3-V1.0,
  https://pds-geosciences.wustl.edu/mgs/mgs-m-mola-5-megdr-l3-v1/mgsl_300x/meg128/
- Observation time: 1997-09 to 2001-06 (aerobraking and mapping phases)
- Coverage: 88S to 88N at 128 px/deg; polar products at other resolutions are not integrated
- Resolution: 463 m/px at the equator
- Format: PDS3 raw 16-bit big-endian integer rasters (`megt*.img`, 44 deg x 90 deg tiles of
  5632 x 11520 pixels) with detached labels, plus the companion `megc*.img` counts rasters
  (laser shots per pixel, 8-bit)
- Processing (upstream): laser shots binned to a simple-cylindrical grid on the IAU 2000
  sphere, heights relative to the GMM-2B areoid; empty bins interpolated
- Processing (MARS-X): `app/services/dem.py` requests only the 1-degree latitude bands it
  needs (128 rows x 11520 columns) with HTTP `Range` headers, stores each band as a `.npy`
  file under `<cache>/mola128/`, and keeps up to 48 bands in memory. Pixels with a shot count
  of 0 are flagged "interpolated"; others "measured".
- Access: lazy-cache
- Limitations: many pixels are interpolated between ground tracks, especially near the
  equator. Resolves regional slopes only; rocks, dunes, scarps and any hazard smaller than
  several hundred metres are invisible. One analysis window may span at most 10 degrees.

### Mars 2020 TRN CTX DTM mosaic, Jezero crater (`jezero_ctx_dtm_20m`)

- Mission / instrument: Mars Reconnaissance Orbiter / CTX (Context Camera)
- Source: USGS Astrogeology Science Center, Mars 2020 Terrain Relative Navigation products,
  https://planetarymaps.usgs.gov/mosaic/mars2020_trn/CTX/JEZ_ctx_B_soc_008_DTM_MOLAtopography_DeltaGeoid_20m_Eqc_latTs0_lon0.tif
- Observation time: CTX stereo pairs acquired 2007-2017; mosaic released 2020
- Coverage: Jezero crater, 77.16-77.70 E, 18.21-18.72 N
- Resolution: 20 m/px
- Format: GeoTIFF, 32-bit float, equirectangular (latitude of true scale 0, central meridian 0)
  on the Mars 2000 sphere
- Processing (upstream): CTX stereo DTMs (SOCET SET), bundle-adjusted and tied to MOLA;
  elevations relative to the areoid
- Processing (MARS-X): the 9.7 MB file is downloaded once to `<cache>/jezero_ctx_dtm_20m.tif`
  and read with rasterio when importable, otherwise with Pillow plus the GeoTIFF
  ModelPixelScale/ModelTiepoint tags. Projected metres are converted to degrees with
  lon = x / R, lat = y / R. Values below -1e30 are treated as no-data.
- Access: lazy-cache
- Limitations: 20 m baseline; no boulders, ripples or metre-scale scarps; stereo-matching
  artefacts are possible in bland terrain. Jezero only. When a request lies inside this
  footprint the backend uses it in preference to MOLA.

## Imagery and map layers

### Mars Trek map layers (`trek_wmts`)

- Missions: Viking, MGS, Mars Odyssey, MRO, Mars Express
- Instruments: VIS, MOLA, CTX, HiRISE, CRISM, THEMIS, TES, HRSC (plus two USGS geologic maps)
- Source: NASA Solar System Treks (Mars Trek), https://trek.nasa.gov/mars/
- Observation time: 1976-2018 depending on layer (per-layer details below)
- Coverage: global and regional mosaics
- Resolution: 25 cm/px (regional HiRISE) to about 7 km/px (TES)
- Format: OGC WMTS REST tiles (JPEG/PNG), geographic tiling on the Mars 2000 sphere
  (EPSG:104905), 2 x 1 tiles at level 0
- Processing: mosaics produced by USGS, ASU, Caltech/Murray Lab and JPL, served as
  pre-rendered tiles. `ingest_nasa.py` read each layer's `WMTSCapabilities.xml` to record the
  tile URL template, image format and number of tile levels.
- Access: live (tiles are streamed by the browser; the backend only serves the layer list)
- Limitations: rendered imagery only; pixel values are display colours, not calibrated
  physical quantities.

**Tile hosts.** Three hosts serve the tiles, as given by each layer's Trek capabilities
document:

- `trek.nasa.gov/tiles/Mars/EQ/...`: Trek's own tile store (13 layers).
- `trek.nasa.gov/mars/trekarcgis/rest/services/...`: Trek ArcGIS map services (the two CRISM
  indicator maps and the two geology layers).
- `astro.arcgis.com/arcgis/rest/services/OnMars/...`: the global CTX and HiRISE mosaics. The
  Trek catalogue references these USGS Astrogeology / Esri "OnMars" services, and the layer
  record's `source` field says so.

**Verified tile depth.** For most Trek-hosted layers the WMTS capabilities advertise two more
TileMatrix levels than the tile store actually serves. Beyond the real depth, requests return
errors and the globe would show blank tiles. `probe_max_level()` in `ingest_nasa.py` therefore
requests a tile at the centre of each `trek.nasa.gov` layer's footprint, starting at the deepest
advertised level and working up, and stores the deepest level that returns an image as
`max_level`. The advertised value is kept as `advertised_max_level`. The two `astro.arcgis.com`
layers are not probed, so for them `max_level` equals the advertised value. The frontend
requests tiles only up to `max_level`. Values in `trek_layers.json`:

| Layer id | `max_level` | `advertised_max_level` |
| --- | --- | --- |
| `Mars_Viking_MDIM21_ClrMosaic_global_232m` | 7 | 9 |
| `CTX_beta01_uncontrolled_5m_Caltech` | 13 | 13 (not probed) |
| `HiRISE_Global` | 19 | 19 (not probed) |
| `JEZ_ctx_B_soc_008_orthoMosaic_6m_Eqc_latTs0_lon0` | 13 | 15 |
| `JEZ_hirise_soc_006_orthoMosaic_25cm_Eqc_latTs0_lon0_first_dd` | 17 | 19 |
| `Gale_CTX_BlockAdj_dd` | 12 | 14 |
| `curiosity_hirise_mosaic` | 16 | 18 |
| `Mars_MGS_MOLA_ClrShade_merge_global_463m` | 7 | 9 |
| `Mars_MOLA_blend200ppx_HRSC_ClrShade_clon0dd_200mpp_lzw` | 8 | 10 |
| `mola_roughness` | 1 | 3 |
| `THEMIS_DayIR_ControlledMosaics_100m_v2_oct2018` | 9 | 11 |
| `THEMIS_NightIR_ControlledMosaics_100m_v2_oct2018` | 9 | 11 |
| `TES_Thermal_Inertia` | 1 | 3 |
| `T1303_FeMgSmectite_Mineral_Indicator_SP` | 11 | 11 |
| `MC18_PolySulfate_Mineral_IndicatorV2_SP` | 11 | 11 |
| `TES_Glass_Clay` | 1 | 3 |
| `TES_Dust` | 1 | 3 |
| `SIM3292_Global_Geology` | 11 | 11 |
| `Hynek_Valley_Networks` | 8 | 8 |

The two-level gap appears on all 13 layers served from `trek.nasa.gov/tiles/`; the four
`trekarcgis` layers served every advertised level when probed.

The 19 integrated layers (in the order of `trek_layers.json`; "tile levels" below is the
verified `max_level`):

#### Viking VIS, Global Color Mosaic

- Layer id: `Mars_Viking_MDIM21_ClrMosaic_global_232m` (category: Base planetary imagery)
- Mission / instrument: Viking / MDIM21
- Source: https://trek.nasa.gov/tiles/Mars/EQ/Mars_Viking_MDIM21_ClrMosaic_global_232m/1.0.0/WMTSCapabilities.xml
- Tile URL template: `https://trek.nasa.gov/tiles/Mars/EQ/Mars_Viking_MDIM21_ClrMosaic_global_232m/1.0.0/default/default028mm/{z}/{y}/{x}.jpg`
- Observation time: Viking Orbiter 1 & 2, 1976-1980 (MDIM 2.1 released 2005)
- Coverage: Global (catalogue bounding box)
- Resolution: 232 m/px; tile levels 0-9
- Format: image/jpeg WMTS tiles
- Trek catalogue date: 2020-11-20T19:22:56Z
- Limitations: Colour mosaic of Viking Orbiter images; 232 m/px cannot resolve rover-scale features.

#### MRO CTX, Mosaic Global Uncontrolled (Caltech)

- Layer id: `CTX_beta01_uncontrolled_5m_Caltech` (category: High-resolution orbital imagery)
- Mission / instrument: Mars Reconnaissance Orbiter / CTX
- Source: https://trek.nasa.gov/tiles/Mars/EQ/CTX_beta01_uncontrolled_5m_Caltech/1.0.0/WMTSCapabilities.xml
- Tile URL template: `https://astro.arcgis.com/arcgis/rest/services/OnMars/CTX/MapServer/tile/{z}/{y}/{x}`
- Observation time: MRO CTX 2006-2018 (Murray Lab beta01 mosaic, 2018)
- Coverage: Global (catalogue bounding box)
- Resolution: ~5-6 m/px; tile levels 0-13
- Format: image/png WMTS tiles
- Trek catalogue date: 2020-06-25T22:50:16Z
- Limitations: Uncontrolled beta mosaic: seams and positional offsets of tens of metres are expected.

#### MRO HiRISE, Mosaic Global Uncontrolled

- Layer id: `HiRISE_Global` (category: High-resolution orbital imagery)
- Mission / instrument: Mars Reconnaissance Orbiter / HiRISE
- Source: https://trek.nasa.gov/tiles/Mars/EQ/HiRISE_Global/1.0.0/WMTSCapabilities.xml
- Tile URL template: `https://astro.arcgis.com/arcgis/rest/services/OnMars/HiRISE/MapServer/tile/{z}/{y}/{x}`
- Observation time: MRO HiRISE 2006 onward
- Coverage: Global (catalogue bounding box)
- Resolution: 0.25-0.5 m/px (sparse coverage); tile levels 0-19
- Format: image/png WMTS tiles
- Trek catalogue date: 2020-06-25T22:50:16Z
- Limitations: Uncontrolled; HiRISE covers only a few percent of Mars, most tiles are empty.

#### MRO CTX, Jezero Mosaic, Controlled

- Layer id: `JEZ_ctx_B_soc_008_orthoMosaic_6m_Eqc_latTs0_lon0` (category: Regional terrain imagery)
- Mission / instrument: Mars Reconnaissance Orbiter / CTX
- Source: https://trek.nasa.gov/tiles/Mars/EQ/JEZ_ctx_B_soc_008_orthoMosaic_6m_Eqc_latTs0_lon0/1.0.0/WMTSCapabilities.xml
- Tile URL template: `https://trek.nasa.gov/tiles/Mars/EQ/JEZ_ctx_B_soc_008_orthoMosaic_6m_Eqc_latTs0_lon0/1.0.0/default/default028mm/{z}/{y}/{x}.png`
- Observation time: MRO CTX stereo 2007-2017 (Mars 2020 TRN mosaic, 2020)
- Coverage: 77.16 to 77.70 E, 18.21 to 18.72 N
- Resolution: 6 m/px; tile levels 0-15
- Format: image/png WMTS tiles
- Trek catalogue date: 2020-08-03T22:38:00Z
- Limitations: Controlled Mars 2020 TRN base map; Jezero crater only.

#### MRO HiRISE, Jezero Mosaic, Controlled

- Layer id: `JEZ_hirise_soc_006_orthoMosaic_25cm_Eqc_latTs0_lon0_first_dd` (category: Regional terrain imagery)
- Mission / instrument: Mars Reconnaissance Orbiter / HiRISE
- Source: https://trek.nasa.gov/tiles/Mars/EQ/JEZ_hirise_soc_006_orthoMosaic_25cm_Eqc_latTs0_lon0_first_dd/1.0.0/WMTSCapabilities.xml
- Tile URL template: `https://trek.nasa.gov/tiles/Mars/EQ/JEZ_hirise_soc_006_orthoMosaic_25cm_Eqc_latTs0_lon0_first_dd/1.0.0/default/default028mm/{z}/{y}/{x}.png`
- Observation time: MRO HiRISE 2007-2017 (Mars 2020 TRN mosaic, 2020)
- Coverage: 77.22 to 77.58 E, 18.31 to 18.67 N
- Resolution: 0.25 m/px; tile levels 0-19
- Format: image/png WMTS tiles
- Trek catalogue date: 2020-08-03T22:48:28Z
- Limitations: Controlled Mars 2020 HiRISE base map; Jezero landing ellipse region only.

#### MRO CTX, Gale Crater Mosaic

- Layer id: `Gale_CTX_BlockAdj_dd` (category: Regional terrain imagery)
- Mission / instrument: Mars Reconnaissance Orbiter / CTX
- Source: https://trek.nasa.gov/tiles/Mars/EQ/Gale_CTX_BlockAdj_dd/1.0.0/WMTSCapabilities.xml
- Tile URL template: `https://trek.nasa.gov/tiles/Mars/EQ/Gale_CTX_BlockAdj_dd/1.0.0/default/default028mm/{z}/{y}/{x}.png`
- Observation time: MRO CTX 2006-2012
- Coverage: 135.18 to 139.24 E, -6.57 to -2.81 N
- Resolution: ~6 m/px; tile levels 0-14
- Format: image/png WMTS tiles
- Trek catalogue date: 2020-06-25T22:48:07Z
- Limitations: Gale crater only.

#### MRO HiRISE, Curiosity Roving Site Mosaic

- Layer id: `curiosity_hirise_mosaic` (category: Regional terrain imagery)
- Mission / instrument: Mars Reconnaissance Orbiter / HiRISE
- Source: https://trek.nasa.gov/tiles/Mars/EQ/curiosity_hirise_mosaic/1.0.0/WMTSCapabilities.xml
- Tile URL template: `https://trek.nasa.gov/tiles/Mars/EQ/curiosity_hirise_mosaic/1.0.0/default/default028mm/{z}/{y}/{x}.png`
- Observation time: MRO HiRISE 2006-2012
- Coverage: 137.12 to 137.73 E, -4.93 to -4.25 N
- Resolution: 0.25 m/px; tile levels 0-18
- Format: image/png WMTS tiles
- Trek catalogue date: 2020-06-25T22:50:16Z
- Limitations: Curiosity roving site only.

#### MGS MOLA, Global Color Hillshade

- Layer id: `Mars_MGS_MOLA_ClrShade_merge_global_463m` (category: Elevation)
- Mission / instrument: Mars Global Surveyor / MOLA
- Source: https://trek.nasa.gov/tiles/Mars/EQ/Mars_MGS_MOLA_ClrShade_merge_global_463m/1.0.0/WMTSCapabilities.xml
- Tile URL template: `https://trek.nasa.gov/tiles/Mars/EQ/Mars_MGS_MOLA_ClrShade_merge_global_463m/1.0.0/default/default028mm/{z}/{y}/{x}.jpg`
- Observation time: MGS MOLA 1997-2001
- Coverage: Global (catalogue bounding box)
- Resolution: 463 m/px; tile levels 0-9
- Format: image/jpeg WMTS tiles
- Trek catalogue date: 2020-06-25T22:51:06Z
- Limitations: Colourised hillshade rendering of the 463 m MOLA MEGDR; colours are relative, read values with the terrain tools.

#### MGS MOLA and Mars Express HRSC, Color Hillshade Blend

- Layer id: `Mars_MOLA_blend200ppx_HRSC_ClrShade_clon0dd_200mpp_lzw` (category: Elevation)
- Mission / instrument: Mixed / Blend
- Source: https://trek.nasa.gov/tiles/Mars/EQ/Mars_MOLA_blend200ppx_HRSC_ClrShade_clon0dd_200mpp_lzw/1.0.0/WMTSCapabilities.xml
- Tile URL template: `https://trek.nasa.gov/tiles/Mars/EQ/Mars_MOLA_blend200ppx_HRSC_ClrShade_clon0dd_200mpp_lzw/1.0.0/default/default028mm/{z}/{y}/{x}.jpg`
- Observation time: MGS MOLA 1997-2001 + Mars Express HRSC 2004-2017
- Coverage: Global (catalogue bounding box)
- Resolution: 200 m/px; tile levels 0-10
- Format: image/jpeg WMTS tiles
- Trek catalogue date: 2020-06-25T22:51:01Z
- Limitations: Blend of MOLA and Mars Express HRSC DEMs (ESA/DLR/FU Berlin); 200 m/px.

#### MGS MOLA, Global Surface Roughness

- Layer id: `mola_roughness` (category: Surface roughness)
- Mission / instrument: Mars Global Surveyor / LaserAltimeter
- Source: https://trek.nasa.gov/tiles/Mars/EQ/mola_roughness/1.0.0/WMTSCapabilities.xml
- Tile URL template: `https://trek.nasa.gov/tiles/Mars/EQ/mola_roughness/1.0.0/default/default028mm/{z}/{y}/{x}.png`
- Observation time: MGS MOLA 1997-2001
- Coverage: Global (catalogue bounding box)
- Resolution: ~7 km/px; tile levels 0-3
- Format: image/png WMTS tiles
- Trek catalogue date: 2020-06-25T22:53:03Z
- Limitations: Kilometre-scale vertical roughness from MOLA pulse/baseline statistics; not rock abundance.

#### MO THEMIS-IR Day, Global Mosaic

- Layer id: `THEMIS_DayIR_ControlledMosaics_100m_v2_oct2018` (category: Thermal observations)
- Mission / instrument: Mars Odyssey / THEMIS
- Source: https://trek.nasa.gov/tiles/Mars/EQ/THEMIS_DayIR_ControlledMosaics_100m_v2_oct2018/1.0.0/WMTSCapabilities.xml
- Tile URL template: `https://trek.nasa.gov/tiles/Mars/EQ/THEMIS_DayIR_ControlledMosaics_100m_v2_oct2018/1.0.0/default/default028mm/{z}/{y}/{x}.png`
- Observation time: Mars Odyssey THEMIS 2002-2018 (controlled mosaic v2, Oct 2018)
- Coverage: All longitudes, -65 to 65 N
- Resolution: 100 m/px; tile levels 0-11
- Format: image/png WMTS tiles
- Trek catalogue date: 2020-06-25T22:51:13Z
- Limitations: Daytime infrared brightness mosaic (relative, normalised between strips); not absolute temperature. Covers 65S-65N.

#### MO THEMIS-IR Night, Global Mosaic

- Layer id: `THEMIS_NightIR_ControlledMosaics_100m_v2_oct2018` (category: Thermal observations)
- Mission / instrument: Mars Odyssey / THEMIS
- Source: https://trek.nasa.gov/tiles/Mars/EQ/THEMIS_NightIR_ControlledMosaics_100m_v2_oct2018/1.0.0/WMTSCapabilities.xml
- Tile URL template: `https://trek.nasa.gov/tiles/Mars/EQ/THEMIS_NightIR_ControlledMosaics_100m_v2_oct2018/1.0.0/default/default028mm/{z}/{y}/{x}.png`
- Observation time: Mars Odyssey THEMIS 2002-2018 (controlled mosaic v2, Oct 2018)
- Coverage: All longitudes, -65 to 65 N
- Resolution: 100 m/px; tile levels 0-11
- Format: image/png WMTS tiles
- Trek catalogue date: 2020-06-25T22:48:19Z
- Limitations: Night-time infrared mosaic; brighter generally means rockier/higher thermal inertia. Covers 65S-65N.

#### MGS TES, Global Thermal Inertia

- Layer id: `TES_Thermal_Inertia` (category: Thermal observations)
- Mission / instrument: Mars Global Surveyor / TES
- Source: https://trek.nasa.gov/tiles/Mars/EQ/TES_Thermal_Inertia/1.0.0/WMTSCapabilities.xml
- Tile URL template: `https://trek.nasa.gov/tiles/Mars/EQ/TES_Thermal_Inertia/1.0.0/default/default028mm/{z}/{y}/{x}.png`
- Observation time: MGS TES 1997-2006
- Coverage: Global (catalogue bounding box)
- Resolution: ~7 km/px; tile levels 0-3
- Format: image/png WMTS tiles
- Trek catalogue date: 2020-06-25T22:50:53Z
- Limitations: MGS TES; several km per pixel.

#### MGS TES, Global Sheet Silicates/High-Si Glass

- Layer id: `TES_Glass_Clay` (category: Mineralogical information)
- Mission / instrument: Mars Global Surveyor / TES
- Source: https://trek.nasa.gov/tiles/Mars/EQ/TES_Glass_Clay/1.0.0/WMTSCapabilities.xml
- Tile URL template: `https://trek.nasa.gov/tiles/Mars/EQ/TES_Glass_Clay/1.0.0/default/default028mm/{z}/{y}/{x}.png`
- Observation time: MGS TES 1997-2006
- Coverage: Global (catalogue bounding box)
- Resolution: ~7 km/px; tile levels 0-3
- Format: image/png WMTS tiles
- Trek catalogue date: 2020-06-25T22:50:15Z
- Limitations: MGS TES spectral unmixing at ~7 km/px: sheet silicates and high-Si glass are not separable in this product.

#### MGS TES, Global Dust

- Layer id: `TES_Dust` (category: Mineralogical information)
- Mission / instrument: Mars Global Surveyor / TES
- Source: https://trek.nasa.gov/tiles/Mars/EQ/TES_Dust/1.0.0/WMTSCapabilities.xml
- Tile URL template: `https://trek.nasa.gov/tiles/Mars/EQ/TES_Dust/1.0.0/default/default028mm/{z}/{y}/{x}.png`
- Observation time: MGS TES 1997-2006
- Coverage: Global (catalogue bounding box)
- Resolution: ~7 km/px; tile levels 0-3
- Format: image/png WMTS tiles
- Trek catalogue date: 2020-06-25T22:52:03Z
- Limitations: MGS TES dust cover; several km per pixel.

#### Global Geology

- Layer id: `SIM3292_Global_Geology` (category: Geology)
- Mission / instrument: n/a / n/a
- Source: https://trek.nasa.gov/tiles/Mars/EQ/SIM3292_Global_Geology/1.0.0/WMTSCapabilities.xml
- Tile URL template: `https://trek.nasa.gov/mars/trekarcgis/rest/services/SIM3292_Global_Geology/MapServer/WMTS/tile/1.0.0/SIM3292_Global_Geology/default/default028mm/{z}/{y}/{x}.png`
- Observation time: Published 2014 (mapping from MOLA/THEMIS/CTX era data)
- Coverage: Global (catalogue bounding box)
- Resolution: 1:20,000,000 map scale; tile levels 0-11
- Format: image/png WMTS tiles
- Trek catalogue date: 2020-06-25T22:46:08Z
- Limitations: USGS SIM 3292 global geologic map (Tanaka et al., 2014), 1:20M scale.

#### Valley Networks

- Layer id: `Hynek_Valley_Networks` (category: Geology)
- Mission / instrument: n/a / n/a
- Source: https://trek.nasa.gov/tiles/Mars/EQ/Hynek_Valley_Networks/1.0.0/WMTSCapabilities.xml
- Tile URL template: `https://trek.nasa.gov/mars/trekarcgis/rest/services/Hynek_Valley_Networks/MapServer/WMTS/tile/1.0.0/Hynek_Valley_Networks/default/default028mm/{z}/{y}/{x}.png`
- Observation time: Published 2010 (THEMIS/MOLA-based mapping)
- Coverage: Global (catalogue bounding box)
- Resolution: Vector mapping, rendered; tile levels 0-8
- Format: image/png WMTS tiles
- Trek catalogue date: 2020-06-25T22:48:59Z
- Limitations: Valley network mapping (Hynek et al., 2010).

### MARS-X computed layers

`GET /api/v1/planet/layers` also lists layers produced by the backend rather than served by
Trek (`BACKEND_LAYERS` in `catalog.py`): slope, inferred terrain hazard and elevation data
quality overlays (PNG images rendered from the DEMs above by `/api/v1/terrain/overlay.png`),
and point/line layers for hydrous mineral detections, rover traverses, science targets and
planned routes. They are derived products of the datasets in this document, not separate
NASA datasets.

## Mineralogy

### Hydrous mineral detections, CRISM and OMEGA (`hydrous_minerals`)

- Missions / instruments: Mars Reconnaissance Orbiter / CRISM; Mars Express / OMEGA
- Source: Carter et al. (2013), JGR Planets 118, 831-858, distributed as point shapefiles by
  NASA Mars Trek:
  https://trek.nasa.gov/mars/TrekWS/rest/cat/data/stream?label=Hydrous_Mineral_Detections_CRISM_clon0
- Observation time: OMEGA 2004-2011; CRISM 2006-2012 (survey published 2013)
- Coverage: global, targeted; points in the file span 60S to 82N
- Resolution: CRISM 18-40 m/px targeted, OMEGA 0.3-5 km/px; each point marks a detection site
- Format: ESRI point shapefile (zip), parsed to JSON
- Processing (MARS-X): `ingest_nasa.py` reads the CRISM and OMEGA point shapefiles with a
  minimal built-in shapefile/dBase reader and drops points that coincide (same instrument,
  coordinates rounded to 0.001 degree). Used for map points (`/api/v1/science/hydrous`), the
  mineralogy component of science-target scores (detections within 25 km) and location
  information (detections within 50 km).
- Access: snapshot
- Limitations: the distributed file has no per-point mineral class. Coverage is targeted, so
  the absence of a point is not evidence that hydrated minerals are absent.

## Nomenclature

### IAU Gazetteer of Planetary Nomenclature, Mars (`iau_nomenclature`)

- Source: IAU / USGS Astrogeology, via the NASA Mars Trek search index
  (https://trek.nasa.gov/mars/TrekServices/ws/index/eq/searchItems); gazetteer at
  https://planetarynames.wr.usgs.gov/Page/MARS/target
- Observation time: not applicable (naming database)
- Coverage: global, 1,783 named features in the Trek index
- Resolution: feature centre points
- Format: JSON (Solr index)
- Processing: snapshot of feature name, feature type and centre coordinate. Loaded into the
  `locations` table together with nine NASA landing sites. Curated science targets that are
  located by name take their coordinates from this snapshot.
- Access: snapshot
- Limitations: centre points only, no feature extents. The Trek index is a subset of the full
  gazetteer.

## Rover data

### Perseverance traverse and waypoints (`m20_localization`)

- Mission / instrument: Mars 2020 / rover localisation (navigation plus orbital registration)
- Source: NASA/JPL-Caltech Mars 2020 MMGIS map layers,
  https://mars.nasa.gov/mmgis-maps/M20/Layers/json/M20_waypoints.json (and `M20_traverse.json`)
- Observation time: 2021-02-18 (sol 0) to the snapshot date
- Coverage: Jezero crater floor, delta, margin unit and rim
- Resolution: end-of-drive positions
- Format: GeoJSON
- Processing: waypoints filtered to final end-of-drive positions and sorted by sol;
  traverse polyline decimated to about 4,000 vertices for display.
- Access: snapshot
- Limitations: the rover keeps moving after the snapshot. Positions are localisation solutions,
  not surveyed benchmarks.

### Curiosity traverse and waypoints (`msl_localization`)

- Mission / instrument: Mars Science Laboratory / rover localisation
- Source: NASA/JPL-Caltech MSL MMGIS map layers,
  https://mars.nasa.gov/mmgis-maps/MSL/Layers/json/MSL_waypoints.json (and `MSL_traverse.json`)
- Observation time: 2012-08-06 (sol 0) to the snapshot date
- Coverage: Gale crater floor and lower Aeolis Mons (Mount Sharp)
- Resolution: end-of-drive positions
- Format: GeoJSON
- Processing: as for Perseverance.
- Access: snapshot
- Limitations: snapshot; positions are localisation solutions.

### Rover raw image feeds (`rover_raw_images`)

- Missions / instruments: Mars 2020 (Mastcam-Z, Navcam, Hazcam and others); MSL (MAHLI,
  Mastcam and others)
- Source: NASA/JPL-Caltech raw image services. Perseverance:
  https://mars.nasa.gov/rss/api/?feed=raw_images&category=mars2020&feedtype=json.
  Curiosity: https://mars.nasa.gov/api/v1/raw_image_items/
- Observation time: latest downlinked sols
- Coverage: along each rover traverse
- Format: JSON index plus JPEG/PNG images
- Processing: none; `GET /api/v1/planet/rover-images` lists the newest items.
- Access: live only
- Limitations: raw, uncalibrated. Requires network access; not cached, so unavailable offline.

## Environment

### REMS daily weather summaries (`rems_weather`)

- Mission / instrument: Mars Science Laboratory (Curiosity) / REMS
- Source: Centro de Astrobiologia (CSIC-INTA) via the NASA Mars public weather feed,
  https://mars.nasa.gov/rss/api/?feed=weather&category=msl&feedtype=json
- Observation time: 2012-08 to the latest sol in the feed
- Coverage: one station, Curiosity's position in Gale crater (about 4.6S, 137.4E)
- Resolution: one summary per sol
- Format: JSON
- Content: per-sol minimum/maximum air and ground temperature, mean pressure, UV index class,
  atmospheric opacity class, sunrise/sunset
- Processing (MARS-X): `app/services/environment.py` fetches the feed live, keeps the newest
  1,400 sols, reuses it for `MARSX_WEATHER_TTL_S` (default 6 h) and writes a copy to the cache
  directory. If the feed is unreachable it falls back to that cached copy, then to the bundled
  snapshot. Every response states which of the three was used and is labelled
  `latest_observation` with its age in days. A derived 0-100 EVA environmental risk index is
  computed from the latest complete sol and labelled `derived_estimate`.
- Access: live, with cache and snapshot fallback
- Limitations: outreach-grade product (per the CAB disclaimer); science use should go to the
  PDS Atmospheres Node REMS RDRs. No wind (the wind sensor was damaged at landing); humidity
  is not populated in the feed. The feed lags by days to weeks, so this is never live weather.

### MEDA daily weather summaries (`meda_weather`)

- Mission / instrument: Mars 2020 (Perseverance) / MEDA
- Source: NASA Mars public weather feed,
  https://mars.nasa.gov/rss/api/?feed=weather&category=mars2020&feedtype=json
- Observation time: the seven-sol window published by the feed (the bundled snapshot holds
  2024-04-21 to 2024-04-27)
- Coverage: one station, Perseverance in Jezero crater (about 18.4N, 77.4E)
- Resolution: one summary per sol
- Format: JSON
- Content: per-sol minimum/maximum air temperature and mean pressure
- Processing: as for REMS (live fetch, cache, snapshot fallback, provenance label).
- Access: live, with cache and snapshot fallback
- Limitations: the feed carries only a short window and may be stale by months. Wind, dust
  opacity, humidity and UV are not in this feed (full MEDA data: PDS Atmospheres Node).

### RAD surface radiation dose (`rad_surface`)

- Mission / instrument: Mars Science Laboratory (Curiosity) / RAD
- Source: Hassler et al. (2014), Science 343, 1244797; cruise value from Zeitlin et al. (2013),
  Science 340, 1080. Full archive: PDS Planetary Plasma Interactions Node,
  https://pds-ppi.igpp.ucla.edu/search/?sc=Mars%20Science%20Laboratory&i=RAD
- Observation time: 2012-08 to 2013-06 (first ~300 sols, near solar maximum)
- Coverage: Gale crater floor, about -4.4 km elevation
- Values used: surface GCR dose rate 0.21 +/- 0.04 mGy/day; surface GCR dose equivalent
  0.64 +/- 0.12 mSv/day; cruise dose equivalent 1.84 +/- 0.33 mSv/day
- Format: published constants (the PDS archive is PDS3/PDS4 tables)
- Processing: none; the published averages are used verbatim (`RAD` in `environment.py`).
- Access: reference
- Limitations: historical average for one site and one phase of the solar cycle. Dose is higher
  at higher elevation (less atmosphere), near solar minimum, and during solar particle events.
  Not a live measurement.

---

## What is NOT integrated and why

- **CRISM per-pixel spectral cubes.** MARS-X does not process CRISM TRDR/MTRDR hyperspectral
  cubes or derive spectral parameter maps. Mineralogy comes only from the Carter et al. (2013)
  CRISM/OMEGA detection points (with no per-point mineral class) and the TES mineral map tiles
  (`TES_Glass_Clay`, `TES_Dust`) shown as rendered imagery. Mineral names attached to curated
  targets come from the cited literature, not from MARS-X analysis.
- **THEMIS absolute temperatures.** The THEMIS Day IR and Night IR layers are controlled
  mosaics of relative, strip-normalised brightness. They are displayed as imagery only; no
  surface temperature is derived from them.
- **RAD time series.** Only the published mission-phase averages are used. The RAD archive at
  the PDS PPI Node is not ingested, so there is no current or time-resolved dose.
- **REMS and MEDA wind.** The REMS wind sensor was damaged at landing, and the public MEDA feed
  does not include wind. The environment responses list wind as unavailable, and the EVA risk
  index excludes it.
- **MOLA poleward of 88 degrees.** Only the 128 px/deg MEGDR tiles (88S-88N) are read. Terrain
  queries beyond 88 degrees latitude are clamped to 87.999 degrees or fail with
  `elevation_data_unavailable`; the polar MEGDR products are not integrated.
- **api.nasa.gov Mars Rover Photos API.** This retired API returned HTTP 404 when checked on
  2026-11-14. Rover images come from the mars.nasa.gov raw image feeds listed above instead.
- **Full IAU gazetteer.** The nomenclature snapshot is the 1,783-feature subset available in the
  Mars Trek search index, not the complete IAU gazetteer, and carries centre points only.
- **Other DEMs.** HiRISE DTMs and HRSC DTMs are not used for elevation values. The MOLA/HRSC
  blend appears only as a rendered hillshade layer.
