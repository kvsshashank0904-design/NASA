"""Static catalogue: datasets with provenance, map layers, references, landing sites, curated targets.

Coordinates of curated science targets are never typed in by hand: each is resolved at
load time either from the IAU gazetteer snapshot or from NASA rover localisation data.
"""
from __future__ import annotations

import json
from functools import lru_cache

from ..config import DATA_DIR
from .dem import CTX_URL, MOLA_BASE


@lru_cache
def _load(name: str) -> dict:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def trek_layers() -> dict:
    return _load("trek_layers.json")


def nomenclature() -> dict:
    return _load("nomenclature.json")


def hydrous() -> dict:
    return _load("hydrous_minerals.json")


def rovers() -> dict:
    return _load("rover_traverses.json")


def weather_snapshot() -> dict:
    return _load("weather_snapshot.json")


def trek_catalog() -> dict:
    return _load("trek_catalog.json")


REFERENCES = [
    ("smith2001", "Smith, D. E., et al. (2001), Mars Orbiter Laser Altimeter: Experiment summary after the first year of global mapping of Mars, JGR 106(E10), 23689-23722.", "https://doi.org/10.1029/2000JE001364"),
    ("carter2013", "Carter, J., et al. (2013), Hydrous minerals on Mars as seen by the CRISM and OMEGA imaging spectrometers: Updated global view, JGR Planets 118, 831-858.", "https://doi.org/10.1029/2012JE004145"),
    ("hassler2014", "Hassler, D. M., et al. (2014), Mars' surface radiation environment measured with the Mars Science Laboratory's Curiosity rover, Science 343, 1244797.", "https://doi.org/10.1126/science.1244797"),
    ("zeitlin2013", "Zeitlin, C., et al. (2013), Measurements of energetic particle radiation in transit to Mars on the Mars Science Laboratory, Science 340, 1080-1084.", "https://doi.org/10.1126/science.1235989"),
    ("goudge2015", "Goudge, T. A., et al. (2015), Assessing the mineralogy of the watershed and fan deposits of the Jezero crater paleolake system, Mars, JGR Planets 120, 775-808.", "https://doi.org/10.1002/2014JE004782"),
    ("mangold2021", "Mangold, N., et al. (2021), Perseverance rover reveals an ancient delta-lake system and flood deposits at Jezero crater, Mars, Science 374, 711-717.", "https://doi.org/10.1126/science.abl4051"),
    ("farley2022", "Farley, K. A., et al. (2022), Aqueously altered igneous rocks sampled on the floor of Jezero crater, Mars, Science 377, eabo2196.", "https://doi.org/10.1126/science.abo2196"),
    ("hurowitz2025", "Hurowitz, J. A., et al. (2025), Redox-driven mineral and organic associations in Jezero Crater, Mars, Nature (2025).", "https://doi.org/10.1038/s41586-025-09413-0"),
    ("ehlmann2008", "Ehlmann, B. L., et al. (2008), Orbital identification of carbonate-bearing rocks on Mars, Science 322, 1828-1832.", "https://doi.org/10.1126/science.1164759"),
    ("bishop2008", "Bishop, J. L., et al. (2008), Phyllosilicate diversity and past aqueous activity revealed at Mawrth Vallis, Mars, Science 321, 830-833.", "https://doi.org/10.1126/science.1159699"),
    ("malin2003", "Malin, M. C., and Edgett, K. S. (2003), Evidence for persistent flow and aqueous sedimentation on early Mars, Science 302, 1931-1934.", "https://doi.org/10.1126/science.1090544"),
    ("grotzinger2014", "Grotzinger, J. P., et al. (2014), A habitable fluvio-lacustrine environment at Yellowknife Bay, Gale crater, Mars, Science 343, 1242777.", "https://doi.org/10.1126/science.1242777"),
    ("squyres2004", "Squyres, S. W., et al. (2004), In situ evidence for an ancient aqueous environment at Meridiani Planum, Mars, Science 306, 1709-1714.", "https://doi.org/10.1126/science.1104559"),
    ("squyres2008", "Squyres, S. W., et al. (2008), Detection of silica-rich deposits on Mars, Science 320, 1063-1067.", "https://doi.org/10.1126/science.1155429"),
    ("murchie2009", "Murchie, S. L., et al. (2009), A synthesis of Martian aqueous mineralogy after 1 Mars year of observations from the Mars Reconnaissance Orbiter, JGR 114, E00D06.", "https://doi.org/10.1029/2009JE003342"),
    ("tanaka2014", "Tanaka, K. L., et al. (2014), Geologic map of Mars, USGS Scientific Investigations Map 3292.", "https://doi.org/10.3133/sim3292"),
    ("edwards2011", "Edwards, C. S., et al. (2011), Mosaicking of global planetary image datasets: 1. Techniques and data processing for THEMIS multi-spectral data, JGR 116, E10008.", "https://doi.org/10.1029/2010JE003755"),
    ("gomezelvira2012", "Gomez-Elvira, J., et al. (2012), REMS: The environmental sensor suite for the Mars Science Laboratory rover, Space Sci. Rev. 170, 583-640.", "https://doi.org/10.1007/s11214-012-9921-1"),
    ("rodriguezmanfredi2021", "Rodriguez-Manfredi, J. A., et al. (2021), The Mars Environmental Dynamics Analyzer, MEDA, Space Sci. Rev. 217, 48.", "https://doi.org/10.1007/s11214-021-00816-9"),
    ("fergason2020", "Fergason, R. L., et al. (2020), Mars 2020 Terrain Relative Navigation flight product generation: Digital terrain model and orthorectified image mosaics, 51st Lunar and Planetary Science Conference.", "https://astrogeology.usgs.gov/search/map/mars_2020_terrain_relative_navigation_ctx_dtm_mosaic"),
    ("malin2007", "Malin, M. C., et al. (2007), Context Camera investigation on board the Mars Reconnaissance Orbiter, JGR 112, E05S04.", "https://doi.org/10.1029/2006JE002808"),
    ("mcewen2007", "McEwen, A. S., et al. (2007), Mars Reconnaissance Orbiter's High Resolution Imaging Science Experiment (HiRISE), JGR 112, E05S02.", "https://doi.org/10.1029/2005JE002605"),
]

_TREK = "NASA Solar System Treks (Mars Trek) WMTS, trek.nasa.gov"

DATASETS = [
    dict(id="mola_megdr_128", name="MOLA Mission Experiment Gridded Data Record, 128 px/deg", mission="Mars Global Surveyor",
         instrument="MOLA", category="elevation", source="NASA PDS Geosciences Node (MGS-M-MOLA-5-MEGDR-L3-V1.0)",
         source_url=MOLA_BASE, observation_time="1997-09 to 2001-06 (aerobraking + mapping phases)",
         coverage="88S-88N at 128 px/deg (polar caps at other resolutions, not integrated)", resolution="463 m/px at equator; ~1 m vertical precision per shot",
         data_format="PDS3 raw 16-bit MSB integer rasters (.IMG) with detached labels; companion MEGC counts rasters",
         processing="Laser shots binned to simple-cylindrical grid on the IAU 2000 sphere, heights relative to the GMM-2B areoid; empty bins interpolated. "
                    "MARS-X reads 1-degree latitude bands by HTTP Range request and caches them as NumPy arrays.",
         limitations="Many pixels are interpolated (flagged from the MEGC counts product). Regional slopes only.", integration="lazy-cache"),
    dict(id="jezero_ctx_dtm_20m", name="Mars 2020 TRN CTX DTM mosaic, Jezero crater", mission="Mars Reconnaissance Orbiter",
         instrument="CTX", category="elevation", source="USGS Astrogeology Science Center (Mars 2020 Terrain Relative Navigation products)",
         source_url=CTX_URL, observation_time="CTX stereo pairs acquired 2007-2017; mosaic released 2020",
         coverage="Jezero crater, 77.16-77.70E, 18.21-18.72N", resolution="20 m/px",
         data_format="GeoTIFF, 32-bit float, equirectangular (lat_ts 0, lon0 0) on the Mars 2000 sphere",
         processing="CTX stereo DTMs (SOCET SET) bundle-adjusted and tied to MOLA; elevations relative to the areoid. MARS-X downloads the 9.7 MB file once and reads it locally.",
         limitations="20 m baseline: no boulders, ripples or metre-scale scarps. Jezero only.", integration="lazy-cache"),
    dict(id="mola_megdr_16", name="MOLA Mission Experiment Gridded Data Record, 16 px/deg (global)", mission="Mars Global Surveyor",
         instrument="MOLA", category="elevation", source="NASA PDS Geosciences Node (MGS-M-MOLA-5-MEGDR-L3-V1.0)",
         source_url="https://pds-geosciences.wustl.edu/mgs/mgs-m-mola-5-megdr-l3-v1/mgsl_300x/meg016/",
         observation_time="1997-09 to 2001-06", coverage="Global, 90S-90N", resolution="3.7 km/px at equator",
         data_format="PDS3 raw 16-bit MSB integer raster (.IMG), 5760 x 2880",
         processing="Downloaded once (33 MB + counts) and memory-mapped. Used for traverses longer than ~4 degrees and for the 3D relief of the globe.",
         limitations="Regional topography only; not usable for local hazard assessment.", integration="lazy-cache"),
    dict(id="gale_hirise_dem_1m", name="MSL Gale crater HiRISE DEM mosaic, 1 m (v3)", mission="Mars Reconnaissance Orbiter",
         instrument="HiRISE", category="elevation", source="USGS Astrogeology Science Center (MSL landing-site mosaics)",
         source_url="https://planetarymaps.usgs.gov/mosaic/Mars/MSL/MSL_Gale_DEM_Mosaic_1m_v3.tif",
         observation_time="HiRISE stereo pairs 2006-2012; mosaic v3", coverage="Gale crater floor and lower Mount Sharp (MARS-X caches the boxwork region window)",
         resolution="1 m/px (read at 2 m)", data_format="GeoTIFF, 32-bit float, LZW, one row per strip (3.9 GB)",
         processing="MARS-X reads only the rows of the mission window by HTTP Range, decodes them with libtiff, keeps every second pixel and caches the result.",
         limitations="Window only (about 1.7 x 2.2 km). Rocks under ~2 m and sand are not resolved.", integration="lazy-cache"),
    dict(id="jezero_hirise_dtm_1m", name="Mars 2020 TRN HiRISE DTM mosaic, Jezero crater, 1 m", mission="Mars Reconnaissance Orbiter",
         instrument="HiRISE", category="elevation", source="USGS Astrogeology Science Center (Mars 2020 Terrain Relative Navigation products)",
         source_url="https://planetarymaps.usgs.gov/mosaic/mars2020_trn/HiRISE/JEZ_hirise_soc_006_DTM_MOLAtopography_DeltaGeoid_1m_Eqc_latTs0_lon0_blend40.tif",
         observation_time="HiRISE stereo pairs 2007-2017; mosaic released 2020", coverage="Jezero landing ellipse (MARS-X caches the landing site to delta front window)",
         resolution="1 m/px (read at 2 m)", data_format="GeoTIFF, 32-bit float, uncompressed, one row per strip (1.8 GB)",
         processing="MARS-X reads only the needed columns of each row of the mission window by HTTP Range and caches the result.",
         limitations="Window only (about 4 x 2.7 km). Rocks under ~2 m and sand are not resolved.", integration="lazy-cache"),
    dict(id="trek_wmts", name="Mars Trek map layers (Viking MDIM2.1, MOLA shade, CTX, HiRISE, THEMIS, TES)", mission="Multiple (Viking, MGS, Mars Odyssey, MRO, Mars Express)",
         instrument="VIS, MOLA, CTX, HiRISE, THEMIS, TES, HRSC", category="imagery", source=_TREK,
         source_url="https://trek.nasa.gov/mars/", observation_time="1976-2018 depending on layer (see each layer)",
         coverage="Global and regional mosaics", resolution="25 cm/px (HiRISE regional) to 7.4 km/px (TES)",
         data_format="OGC WMTS REST tiles (JPEG/PNG), geographic tiling on the Mars 2000 sphere (EPSG:104905), 2x1 tiles at level 0",
         processing="Mosaics produced by USGS, ASU, Caltech/Murray Lab, JPL; served as pre-rendered tiles. Streamed by the browser on demand.",
         limitations="Rendered imagery only - pixel values are display colours, not calibrated physical quantities.", integration="live"),
    dict(id="hydrous_minerals", name="Hydrous mineral detections (CRISM and OMEGA)", mission="Mars Reconnaissance Orbiter; Mars Express",
         instrument="CRISM; OMEGA", category="mineralogy", source="Carter et al. (2013), distributed as a shapefile by NASA Mars Trek",
         source_url="https://trek.nasa.gov/mars/TrekWS/rest/cat/data/stream?label=Hydrous_Mineral_Detections_CRISM_clon0",
         observation_time="OMEGA 2004-2011; CRISM 2006-2012 (survey published 2013)", coverage="Global, targeted (60S-82N in the file)",
         resolution="CRISM 18-40 m/px targeted; OMEGA 0.3-5 km/px; points mark detection sites", data_format="ESRI point shapefile (parsed to JSON snapshot)",
         processing="Near-infrared hydration band detections compiled by Carter et al.; MARS-X parses the two point shapefiles and de-duplicates coincident points.",
         limitations="The distributed file has no per-point mineral class. Targeted coverage: absence of a point is not absence of hydrated minerals.", integration="snapshot"),
    dict(id="iau_nomenclature", name="IAU Gazetteer of Planetary Nomenclature (Mars)", mission=None, instrument=None, category="nomenclature",
         source="IAU / USGS Astrogeology, via the NASA Mars Trek search index", source_url="https://planetarynames.wr.usgs.gov/Page/MARS/target",
         observation_time="n/a (naming database)", coverage="Global, 1,783 named features in the Trek index", resolution="Feature centre points",
         data_format="JSON (Solr index)", processing="Snapshot of feature name, type and centre coordinate.",
         limitations="Centre points only; feature extents are not included. The Trek index is a subset of the full gazetteer.", integration="snapshot"),
    dict(id="m20_localization", name="Perseverance traverse and waypoints", mission="Mars 2020", instrument="Rover localisation (navigation + orbital registration)",
         category="rover", source="NASA/JPL-Caltech Mars 2020 mission map layers", source_url="https://mars.nasa.gov/mmgis-maps/M20/Layers/json/M20_waypoints.json",
         observation_time="2021-02-18 (sol 0) to snapshot date", coverage="Jezero crater floor, delta, margin unit and rim", resolution="End-of-drive positions; sub-metre relative, ~metres absolute",
         data_format="GeoJSON", processing="End-of-drive localisations filtered to final positions; traverse polyline decimated to ~4,000 vertices for display.",
         limitations="Snapshot; the rover keeps moving. Positions are localisation solutions, not surveyed benchmarks.", integration="snapshot"),
    dict(id="msl_localization", name="Curiosity traverse and waypoints", mission="Mars Science Laboratory", instrument="Rover localisation",
         category="rover", source="NASA/JPL-Caltech MSL mission map layers", source_url="https://mars.nasa.gov/mmgis-maps/MSL/Layers/json/MSL_waypoints.json",
         observation_time="2012-08-06 (sol 0) to snapshot date", coverage="Gale crater floor and lower Aeolis Mons (Mount Sharp)", resolution="End-of-drive positions",
         data_format="GeoJSON", processing="As for Perseverance.", limitations="Snapshot; positions are localisation solutions.", integration="snapshot"),
    dict(id="rems_weather", name="REMS daily weather summaries", mission="Mars Science Laboratory (Curiosity)", instrument="REMS",
         category="environment", source="Centro de Astrobiologia (CSIC-INTA) via NASA Mars public weather feed",
         source_url="https://mars.nasa.gov/rss/api/?feed=weather&category=msl&feedtype=json", observation_time="2012-08 to latest sol in feed (per-sol)",
         coverage="Single station: Curiosity's position in Gale crater (~4.6S, 137.4E)", resolution="One summary per sol",
         data_format="JSON", processing="Per-sol min/max air and ground temperature, mean pressure, UV index class, opacity class produced by CAB. Fetched live with a bundled snapshot fallback.",
         limitations="Outreach-grade product (per CAB disclaimer); for science use the PDS Atmospheres Node REMS RDRs. Wind is unavailable: the wind sensor was damaged at landing. Not live weather - the feed lags by days to weeks.",
         integration="live"),
    dict(id="meda_weather", name="MEDA daily weather summaries", mission="Mars 2020 (Perseverance)", instrument="MEDA",
         category="environment", source="NASA Mars public weather feed (Mars 2020)", source_url="https://mars.nasa.gov/rss/api/?feed=weather&category=mars2020&feedtype=json",
         observation_time="Seven-sol window published by the feed (see observation dates)", coverage="Single station: Perseverance in Jezero crater (~18.4N, 77.4E)",
         resolution="One summary per sol", data_format="JSON", processing="Per-sol min/max air temperature and mean pressure. Fetched live with a bundled snapshot fallback.",
         limitations="Feed carries only a short window and may be stale by months; wind, dust opacity and humidity are not in this feed (full MEDA data: PDS Atmospheres Node).",
         integration="live"),
    dict(id="rad_surface", name="RAD surface radiation dose (published values)", mission="Mars Science Laboratory (Curiosity)", instrument="RAD",
         category="environment", source="Hassler et al. (2014), Science; full archive at the PDS Planetary Plasma Interactions Node",
         source_url="https://pds-ppi.igpp.ucla.edu/search/?sc=Mars%20Science%20Laboratory&i=RAD", observation_time="2012-08 to 2013-06 (first ~300 sols, near solar maximum)",
         coverage="Gale crater floor, ~-4.4 km elevation", resolution="Mission-phase averages", data_format="Published constants (PDS archive is PDS3/PDS4 tables)",
         processing="Published averages are used verbatim; MARS-X does not process the RAD time series.",
         limitations="Historical average for one site and one solar-cycle phase. Dose is higher at higher elevation (less atmosphere) and during solar particle events. Not a live measurement.",
         integration="reference"),
    dict(id="rover_raw_images", name="Rover raw image feeds", mission="Mars 2020; Mars Science Laboratory", instrument="Mastcam-Z, Navcam, Hazcam, MAHLI, Mastcam, others",
         category="rover", source="NASA/JPL-Caltech raw image services", source_url="https://mars.nasa.gov/rss/api/?feed=raw_images&category=mars2020&feedtype=json",
         observation_time="Latest downlinked sols", coverage="Along each rover traverse", resolution="Full-frame and thumbnail images",
         data_format="JSON index + JPEG/PNG", processing="Unprocessed downlinked images; MARS-X lists the latest items live.",
         limitations="Raw, uncalibrated. Requires network access; not cached for offline use.", integration="live"),
]

LAYER_DATASET_TIME = {
    "Mars_Viking_MDIM21_ClrMosaic_global_232m": "Viking Orbiter 1 & 2, 1976-1980 (MDIM 2.1 released 2005)",
    "CTX_beta01_uncontrolled_5m_Caltech": "MRO CTX 2006-2018 (Murray Lab beta01 mosaic, 2018)",
    "HiRISE_Global": "MRO HiRISE 2006 onward",
    "JEZ_ctx_B_soc_008_orthoMosaic_6m_Eqc_latTs0_lon0": "MRO CTX stereo 2007-2017 (Mars 2020 TRN mosaic, 2020)",
    "JEZ_hirise_soc_006_orthoMosaic_25cm_Eqc_latTs0_lon0_first_dd": "MRO HiRISE 2007-2017 (Mars 2020 TRN mosaic, 2020)",
    "Gale_CTX_BlockAdj_dd": "MRO CTX 2006-2012",
    "curiosity_hirise_mosaic": "MRO HiRISE 2006-2012",
    "Mars_MGS_MOLA_ClrShade_merge_global_463m": "MGS MOLA 1997-2001",
    "Mars_MOLA_blend200ppx_HRSC_ClrShade_clon0dd_200mpp_lzw": "MGS MOLA 1997-2001 + Mars Express HRSC 2004-2017",
    "mola_roughness": "MGS MOLA 1997-2001",
    "THEMIS_DayIR_ControlledMosaics_100m_v2_oct2018": "Mars Odyssey THEMIS 2002-2018 (controlled mosaic v2, Oct 2018)",
    "THEMIS_NightIR_ControlledMosaics_100m_v2_oct2018": "Mars Odyssey THEMIS 2002-2018 (controlled mosaic v2, Oct 2018)",
    "T1303_FeMgSmectite_Mineral_Indicator_SP": "MRO CRISM 2006-2012 (map tile product)",
    "MC18_PolySulfate_Mineral_IndicatorV2_SP": "MRO CRISM 2006-2012 (map tile product)",
    "TES_Thermal_Inertia": "MGS TES 1997-2006", "TES_Glass_Clay": "MGS TES 1997-2006", "TES_Dust": "MGS TES 1997-2006",
    "SIM3292_Global_Geology": "Published 2014 (mapping from MOLA/THEMIS/CTX era data)",
    "Hynek_Valley_Networks": "Published 2010 (THEMIS/MOLA-based mapping)",
}
LAYER_RESOLUTION = {
    "Mars_Viking_MDIM21_ClrMosaic_global_232m": "232 m/px", "CTX_beta01_uncontrolled_5m_Caltech": "~5-6 m/px",
    "HiRISE_Global": "0.25-0.5 m/px (sparse coverage)", "JEZ_ctx_B_soc_008_orthoMosaic_6m_Eqc_latTs0_lon0": "6 m/px",
    "JEZ_hirise_soc_006_orthoMosaic_25cm_Eqc_latTs0_lon0_first_dd": "0.25 m/px", "Gale_CTX_BlockAdj_dd": "~6 m/px",
    "curiosity_hirise_mosaic": "0.25 m/px", "Mars_MGS_MOLA_ClrShade_merge_global_463m": "463 m/px",
    "Mars_MOLA_blend200ppx_HRSC_ClrShade_clon0dd_200mpp_lzw": "200 m/px", "mola_roughness": "~7 km/px",
    "THEMIS_DayIR_ControlledMosaics_100m_v2_oct2018": "100 m/px", "THEMIS_NightIR_ControlledMosaics_100m_v2_oct2018": "100 m/px",
    "T1303_FeMgSmectite_Mineral_Indicator_SP": "~200 m/px (CRISM multispectral mapping)",
    "MC18_PolySulfate_Mineral_IndicatorV2_SP": "~200 m/px (CRISM multispectral mapping)",
    "TES_Thermal_Inertia": "~7 km/px", "TES_Glass_Clay": "~7 km/px", "TES_Dust": "~7 km/px",
    "SIM3292_Global_Geology": "1:20,000,000 map scale", "Hynek_Valley_Networks": "Vector mapping, rendered",
}

# Layers computed or assembled by the MARS-X backend rather than served by Trek.
BACKEND_LAYERS = [
    dict(id="mx_slope", category="slope", category_title="Slope", title="Slope (computed from DEM)", kind="overlay", overlay="slope",
         description="Slope magnitude in degrees computed by MARS-X from the best DEM for the current analysis region (CTX 20 m inside Jezero, MOLA 463 m elsewhere).",
         mission="MRO / MGS", instrument="CTX / MOLA", source="MARS-X terrain engine over NASA DEMs", resolution="DEM-dependent (20 m or 463 m)",
         timestamp="Computed on request", limitations="Slope at the DEM baseline; underestimates local slopes on rough terrain."),
    dict(id="mx_hazard", category="hazard", category_title="Hazard information", title="Inferred terrain hazard", kind="overlay", overlay="hazard",
         description="Slope-threshold hazard classes (nominal / caution / high / impassable / no data) for the current analysis region.",
         mission="MRO / MGS", instrument="CTX / MOLA", source="MARS-X terrain engine over NASA DEMs", resolution="DEM-dependent (20 m or 463 m)",
         timestamp="Computed on request", limitations="INFERRED from DEM slope only. Not observed hazards. Rocks, sand and small scarps are invisible at this resolution."),
    dict(id="mx_quality", category="hazard", category_title="Hazard information", title="Elevation data quality", kind="overlay", overlay="quality",
         description="Where the DEM is measured versus interpolated versus missing (MOLA shot-count product; CTX no-data mask).",
         mission="MGS / MRO", instrument="MOLA / CTX", source="MOLA MEGC counts product; CTX DTM mask", resolution="DEM-dependent",
         timestamp="Computed on request", limitations="Interpolated MOLA cells can hide real relief between ground tracks."),
    dict(id="mx_minerals", category="mineral", category_title="Mineralogical information", title="Hydrous mineral detections (CRISM + OMEGA)", kind="points", endpoint="/api/v1/science/hydrous",
         description="1,642 sites where CRISM (MRO) or OMEGA (Mars Express) detected hydrated minerals (Carter et al., 2013).",
         mission="MRO / Mars Express", instrument="CRISM / OMEGA", source="Carter et al. (2013) via NASA Mars Trek", resolution="Detection sites (points)",
         timestamp="Survey published 2013", limitations="No per-point mineral class in the distributed file; targeted coverage."),
    dict(id="mx_rovers", category="rover", category_title="Rover observations", title="Rover traverses and waypoints", kind="rovers", endpoint="/api/v1/planet/rovers",
         description="Perseverance and Curiosity traverse paths and end-of-drive positions from NASA/JPL localisation.",
         mission="Mars 2020 / MSL", instrument="Rover localisation", source="NASA/JPL-Caltech MMGIS map layers", resolution="End-of-drive positions",
         timestamp="Snapshot (see Data Explorer)", limitations="Snapshot; rovers continue to move."),
    dict(id="mx_targets", category="science", category_title="Scientific targets", title="Science targets and landing sites", kind="targets", endpoint="/api/v1/science/targets",
         description="Curated, referenced science targets plus NASA landing sites.", mission="Multiple", instrument="Multiple",
         source="Peer-reviewed literature; coordinates from the IAU gazetteer or rover localisation", resolution="Points", timestamp="n/a",
         limitations="A curated selection, not a complete catalogue."),
    dict(id="mx_routes", category="route", category_title="Mission routes", title="Planned mission routes", kind="routes",
         description="Candidate, selected and return routes produced by the MARS-X route planner.", mission="-", instrument="-",
         source="MARS-X route planner (A* over DEM traversability grid)", resolution="DEM-dependent", timestamp="Computed on request",
         limitations="Planning aid only; see each route's confidence statement."),
]

LANDING_SITES = [
    ("Viking 1 lander", -47.95, 22.27, "Landed 1976-07-20, Chryse Planitia."),
    ("Viking 2 lander", 134.29, 47.64, "Landed 1976-09-03, Utopia Planitia."),
    ("Mars Pathfinder / Sojourner", -33.22, 19.13, "Landed 1997-07-04, Ares Vallis outflow plain."),
    ("Spirit (MER-A) landing site", 175.4726, -14.5684, "Landed 2004-01-04, Gusev crater."),
    ("Opportunity (MER-B) landing site", -5.5266, -1.9462, "Landed 2004-01-25, Meridiani Planum."),
    ("Phoenix lander", -125.75, 68.22, "Landed 2008-05-25, Vastitas Borealis; sampled ground ice."),
    ("Curiosity (MSL) landing site - Bradbury Landing", 137.4417, -4.5895, "Landed 2012-08-06, Gale crater."),
    ("InSight lander", 135.6234, 4.5024, "Landed 2018-11-26, Elysium Planitia; seismology and heat flow."),
    ("Perseverance (Mars 2020) landing site - Octavia E. Butler Landing", 77.4509, 18.4447, "Landed 2021-02-18, Jezero crater."),
]

# locate: ("gazetteer", name) or ("rover", key, sol). scores are literature-based priors in [0, 1].
CURATED_TARGETS = [
    dict(id="jezero-landing", name="Octavia E. Butler Landing (crater floor)", category="Igneous crater floor", locate=("rover", "perseverance", 0),
         summary="Perseverance touchdown site on the Maaz formation of Jezero's floor.",
         evidence="In-situ analysis shows the floor units (Maaz, Seitah) are igneous - basaltic lava and an olivine cumulate - later altered by water (carbonate, sulfate, perchlorate salts).",
         hypothesis="Datable igneous rocks could anchor the absolute timing of the lake if samples are returned.",
         minerals=["olivine", "pyroxene", "carbonate", "sulfate"], scores=dict(relevance=0.7, geology=0.7, confidence=1.0), refs=["farley2022"], datasets=["m20_localization", "jezero_ctx_dtm_20m"]),
    dict(id="jezero-seitah", name="Seitah olivine cumulate (sol 262 position)", category="Igneous / aqueous alteration", locate=("rover", "perseverance", 262),
         summary="Dune-filled exposure of coarse olivine-rich rock explored in late 2021.",
         evidence="SuperCam and PIXL measured an olivine cumulate with carbonate alteration and Ca/Mg sulfate in voids.",
         hypothesis="Carbonation of olivine by liquid water; duration and temperature of the water are open questions.",
         minerals=["olivine", "carbonate", "sulfate"], scores=dict(relevance=0.8, geology=0.8, confidence=1.0), refs=["farley2022"], datasets=["m20_localization"]),
    dict(id="jezero-delta-front", name="Western delta front (sol 510 position)", category="Sedimentary deposit / delta", locate=("rover", "perseverance", 510),
         summary="Base of the Jezero western fan where fine-grained sedimentary rocks were sampled in 2022.",
         evidence="Layered sandstones and mudstones with sulfate and organic-bearing material detected by SHERLOC; orbital CRISM shows carbonate and Fe/Mg-smectite in the fan.",
         hypothesis="Fine-grained lake-bottom sediments are favourable for preserving organic matter. Detection of organics is not evidence of life.",
         minerals=["sulfate", "Fe/Mg smectite", "carbonate"], scores=dict(relevance=0.95, geology=1.0, confidence=1.0), refs=["mangold2021", "goudge2015"], datasets=["m20_localization", "hydrous_minerals"]),
    dict(id="jezero-three-forks", name="Three Forks sample depot (sol 690 position)", category="Mission infrastructure / sample cache", locate=("rover", "perseverance", 690),
         summary="Flat area at the delta base where ten sample tubes were deposited (Dec 2022 - Jan 2023).",
         evidence="Ten sealed tubes (rock cores, regolith, atmosphere, witness) were placed on the surface and documented by the rover.",
         hypothesis=None, minerals=[], scores=dict(relevance=0.75, geology=0.5, confidence=1.0), refs=["mangold2021"], datasets=["m20_localization"]),
    dict(id="jezero-bright-angel", name="Bright Angel / Cheyava Falls (sol 1217 position)", category="Potential biosignature (unconfirmed)", locate=("rover", "perseverance", 1217),
         summary="Mudstone outcrop in Neretva Vallis where the 'Cheyava Falls' rock was sampled in July 2024.",
         evidence="Organic carbon together with mm-scale reduced iron phosphate and iron sulfide features ('leopard spots') in a fine-grained mudstone.",
         hypothesis="The redox mineral textures are a POTENTIAL biosignature: they can form by microbial metabolism but also by purely abiotic chemistry. Not evidence of life; requires sample return to test.",
         minerals=["vivianite (candidate)", "greigite (candidate)", "Ca-sulfate", "organic carbon"], scores=dict(relevance=1.0, geology=0.9, confidence=0.9), refs=["hurowitz2025"], datasets=["m20_localization"]),
    dict(id="neretva-vallis", name="Neretva Vallis inlet channel", category="Ancient river channel", locate=("gazetteer", "Neretva Vallis"),
         summary="Valley that fed water and sediment into Jezero crater and built the western delta.",
         evidence="Channel morphology continuous with the delta in CTX/HiRISE images; boulder conglomerates near the fan top imply high-energy flows.",
         hypothesis="Sustained river flow followed by episodic floods late in the lake's history.",
         minerals=["Fe/Mg smectite", "carbonate"], scores=dict(relevance=0.85, geology=0.95, confidence=0.8), refs=["mangold2021", "goudge2015"], datasets=["iau_nomenclature", "trek_wmts"]),
    dict(id="jezero-crater", name="Jezero crater paleolake basin", category="Paleolake basin", locate=("gazetteer", "Jezero"),
         summary="45 km crater that hosted an open-basin lake with inlet and outlet valleys.",
         evidence="Inlet/outlet valleys, two fan deposits and marginal carbonates seen from orbit; lake deposits confirmed in situ.",
         hypothesis="The lake persisted long enough to be habitable; duration is debated.",
         minerals=["carbonate", "Fe/Mg smectite", "olivine"], scores=dict(relevance=0.9, geology=0.95, confidence=0.9), refs=["goudge2015", "mangold2021"], datasets=["iau_nomenclature"]),
    dict(id="nili-fossae", name="Nili Fossae carbonate and olivine terrain", category="Mineralogical target", locate=("gazetteer", "Nili Fossae"),
         summary="Graben system exposing some of the most diverse ancient mineralogy on Mars.",
         evidence="CRISM spectra identify Mg-carbonate, olivine, Fe/Mg-smectite, kaolinite and serpentine in bedrock.",
         hypothesis="Carbonate formed by neutral-to-alkaline water altering olivine-rich rock; serpentinisation may have produced hydrogen/methane.",
         minerals=["Mg-carbonate", "olivine", "Fe/Mg smectite", "serpentine"], scores=dict(relevance=0.9, geology=0.85, confidence=0.8), refs=["ehlmann2008", "murchie2009"], datasets=["hydrous_minerals", "iau_nomenclature"]),
    dict(id="mawrth-vallis", name="Mawrth Vallis clay stratigraphy", category="Clay-bearing region", locate=("gazetteer", "Mawrth Vallis"),
         summary="Outflow channel cutting thick, layered clay-rich Noachian rocks.",
         evidence="OMEGA and CRISM show Al-phyllosilicates (montmorillonite, kaolinite) over Fe/Mg-smectite (nontronite) across >100 km.",
         hypothesis="Prolonged surface or near-surface water-rock interaction (pedogenic leaching or changing water chemistry).",
         minerals=["nontronite", "montmorillonite", "kaolinite", "hydrated silica"], scores=dict(relevance=0.9, geology=0.85, confidence=0.8), refs=["bishop2008", "carter2013"], datasets=["hydrous_minerals", "iau_nomenclature"]),
    dict(id="eberswalde", name="Eberswalde crater delta", category="Sedimentary deposit / delta", locate=("gazetteer", "Eberswalde"),
         summary="One of the best-preserved river deltas on Mars, with meandering, cross-cutting distributary channels.",
         evidence="Inverted channel deposits with meander loops and cut-offs in MOC/HiRISE images.",
         hypothesis="Persistent (not catastrophic) river flow into a standing lake.",
         minerals=["Fe/Mg smectite"], scores=dict(relevance=0.85, geology=1.0, confidence=0.75), refs=["malin2003"], datasets=["iau_nomenclature"]),
    dict(id="gale-yellowknife", name="Yellowknife Bay (Curiosity sol 182 position)", category="Ancient lake sediments", locate=("rover", "curiosity", 182),
         summary="Mudstones drilled by Curiosity in 2013 (John Klein, Cumberland).",
         evidence="Smectite clay, Ca-sulfate veins, neutral-pH low-salinity chemistry and the elements C, H, N, O, P, S measured in situ.",
         hypothesis="A lake environment that would have been habitable for chemolithoautotrophs. Habitable does not mean inhabited.",
         minerals=["smectite", "Ca-sulfate", "magnetite"], scores=dict(relevance=0.95, geology=0.9, confidence=1.0), refs=["grotzinger2014"], datasets=["msl_localization", "rems_weather"]),
    dict(id="gale-mount-sharp", name="Aeolis Mons (Mount Sharp) layered sediments", category="Sedimentary stratigraphy", locate=("gazetteer", "Aeolis Mons"),
         summary="5 km mound of layered rock recording a transition from clay- to sulfate-bearing strata.",
         evidence="CRISM detects clay minerals low in the mound and hydrated sulfates above; Curiosity has confirmed lake mudstones in the lower strata.",
         hypothesis="The clay-to-sulfate transition records regional or global drying of Mars.",
         minerals=["smectite", "hydrated sulfate", "hematite"], scores=dict(relevance=0.9, geology=0.95, confidence=0.9), refs=["grotzinger2014", "murchie2009"], datasets=["iau_nomenclature", "msl_localization"]),
    dict(id="curiosity-current", name="Curiosity - latest localised position", category="Rover observation", locate=("rover", "curiosity", None),
         summary="Most recent end-of-drive position of Curiosity in the snapshot.", evidence="NASA/JPL localisation.", hypothesis=None, minerals=[],
         scores=dict(relevance=0.6, geology=0.6, confidence=1.0), refs=[], datasets=["msl_localization", "rems_weather", "rad_surface"]),
    dict(id="perseverance-current", name="Perseverance - latest localised position", category="Rover observation", locate=("rover", "perseverance", None),
         summary="Most recent end-of-drive position of Perseverance in the snapshot.", evidence="NASA/JPL localisation.", hypothesis=None, minerals=[],
         scores=dict(relevance=0.6, geology=0.6, confidence=1.0), refs=[], datasets=["m20_localization", "meda_weather"]),
    dict(id="meridiani", name="Meridiani Planum hematite and sulfate plains", category="Evaporite / aqueous sediments", locate=("gazetteer", "Meridiani Planum"),
         summary="Plains explored by Opportunity (2004-2018).",
         evidence="Hematite concretions, jarosite and Mg/Ca sulfate-rich sandstones with ripple cross-lamination measured in situ.",
         hypothesis="Acidic, saline groundwater and shallow ephemeral surface water.",
         minerals=["hematite", "jarosite", "Mg-sulfate"], scores=dict(relevance=0.85, geology=0.85, confidence=1.0), refs=["squyres2004"], datasets=["iau_nomenclature"]),
    dict(id="gusev-columbia", name="Gusev crater / Columbia Hills", category="Hydrothermal deposits", locate=("gazetteer", "Gusev"),
         summary="Crater explored by Spirit (2004-2010); Columbia Hills host altered rocks.",
         evidence="Opaline silica (>90 wt% SiO2) at Home Plate and Mg-Fe carbonate at Comanche measured in situ.",
         hypothesis="Hot-spring or fumarole activity; silica textures have been compared with terrestrial hot-spring deposits, which is not proof of biology.",
         minerals=["opaline silica", "Mg-Fe carbonate", "sulfate"], scores=dict(relevance=0.85, geology=0.8, confidence=1.0), refs=["squyres2008"], datasets=["iau_nomenclature"]),
    dict(id="candor-chasma", name="Candor Chasma layered sulfates", category="Mineralogical target", locate=("gazetteer", "Candor Chasma"),
         summary="Interior layered deposits several km thick within Valles Marineris.",
         evidence="CRISM/OMEGA detect kieserite and polyhydrated sulfates in the layered deposits.",
         hypothesis="Evaporitic or groundwater-upwelling origin; debated.",
         minerals=["kieserite", "polyhydrated sulfate", "hematite"], scores=dict(relevance=0.8, geology=0.85, confidence=0.75), refs=["murchie2009"], datasets=["iau_nomenclature", "hydrous_minerals"]),
    dict(id="holden", name="Holden crater layered deposits", category="Sedimentary deposit / paleolake", locate=("gazetteer", "Holden"),
         summary="Crater breached by Uzboi Vallis with finely layered clay-bearing deposits.",
         evidence="Light-toned layered beds with Fe/Mg-smectite signatures in CRISM; megabreccia in the walls.",
         hypothesis="A long-lived lake followed by a catastrophic flood when the rim was breached.",
         minerals=["Fe/Mg smectite"], scores=dict(relevance=0.8, geology=0.9, confidence=0.7), refs=["murchie2009", "malin2003"], datasets=["iau_nomenclature"]),
]


def layers() -> list[dict]:
    out = []
    for lyr in trek_layers()["layers"]:
        d = dict(lyr)
        d["timestamp"] = LAYER_DATASET_TIME.get(lyr["id"])
        d["resolution"] = LAYER_RESOLUTION.get(lyr["id"])
        d["attribution"] = f"{lyr.get('mission') or 'USGS'} {lyr.get('instrument') or ''} - {lyr['source']}".strip()
        out.append(d)
    for lyr in BACKEND_LAYERS:
        d = dict(lyr)
        d["attribution"] = d["source"]
        out.append(d)
    return out


def resolve_targets() -> list[dict]:
    names = {f["name"]: f for f in nomenclature()["features"]}
    rv = rovers()["rovers"]
    out = []
    for t in CURATED_TARGETS:
        loc = t["locate"]
        if loc[0] == "gazetteer":
            f = names.get(loc[1])
            if f is None:
                continue
            lon, lat, src = f["lon"], f["lat"], f"IAU gazetteer centre point of '{loc[1]}'"
        else:
            wps = rv[loc[1]]["waypoints"]
            wp = wps[-1] if loc[2] is None else next((w for w in reversed(wps) if w["sol"] <= loc[2]), wps[0])
            lon, lat = wp["lon"], wp["lat"]
            src = f"{rv[loc[1]]['name']} end-of-drive localisation, sol {wp['sol']} (NASA/JPL)"
        d = {k: v for k, v in t.items() if k != "locate"}
        if loc[0] == "rover" and loc[2] is not None:
            d["name"] = d["name"].replace(f"sol {loc[2]} position", f"rover position, sol {wp['sol']}")
        d.update(lon=lon, lat=lat, coordinate_source=src)
        out.append(d)
    return out
