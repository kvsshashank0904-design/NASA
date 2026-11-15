"""Snapshot small, verified NASA/USGS catalogue data into app/data/*.json.

Every URL below was verified to respond on 2026-11-14. The script only pulls
catalogue-sized resources (a few MB total); large rasters (MOLA MEGDR, CTX DTM)
are fetched lazily at runtime by app.services.dem.

Run:  python scripts/ingest_nasa.py
"""
from __future__ import annotations

import io
import json
import re
import struct
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parents[1] / "app" / "data"
OUT.mkdir(parents=True, exist_ok=True)
NOW = datetime.now(timezone.utc).isoformat(timespec="seconds")

TREK_SEARCH = "https://trek.nasa.gov/mars/TrekServices/ws/index/eq/searchItems"
TREK_PROJ = "urn:ogc:def:crs:EPSG::104905"
TREK_TILES = "https://trek.nasa.gov/tiles/Mars/EQ/{label}/1.0.0/WMTSCapabilities.xml"
TREK_STREAM = "https://trek.nasa.gov/mars/TrekWS/rest/cat/data/stream"

# layer label -> (app layer id, category, notes on limitations)
LAYERS = [
    ("Mars_Viking_MDIM21_ClrMosaic_global_232m", "base", "Base planetary imagery",
     "Colour mosaic of Viking Orbiter images; 232 m/px cannot resolve rover-scale features."),
    ("CTX_beta01_uncontrolled_5m_Caltech", "orbital", "High-resolution orbital imagery",
     "Uncontrolled beta mosaic: seams and positional offsets of tens of metres are expected."),
    ("HiRISE_Global", "orbital", "High-resolution orbital imagery",
     "Uncontrolled; HiRISE covers only a few percent of Mars, most tiles are empty."),
    ("JEZ_ctx_B_soc_008_orthoMosaic_6m_Eqc_latTs0_lon0", "regional", "Regional terrain imagery",
     "Controlled Mars 2020 TRN base map; Jezero crater only."),
    ("JEZ_hirise_soc_006_orthoMosaic_25cm_Eqc_latTs0_lon0_first_dd", "regional", "Regional terrain imagery",
     "Controlled Mars 2020 HiRISE base map; Jezero landing ellipse region only."),
    ("Gale_CTX_BlockAdj_dd", "regional", "Regional terrain imagery", "Gale crater only."),
    ("curiosity_hirise_mosaic", "regional", "Regional terrain imagery", "Curiosity roving site only."),
    ("Mars_MGS_MOLA_ClrShade_merge_global_463m", "elevation", "Elevation",
     "Colourised hillshade rendering of the 463 m MOLA MEGDR; colours are relative, read values with the terrain tools."),
    ("Mars_MOLA_blend200ppx_HRSC_ClrShade_clon0dd_200mpp_lzw", "elevation", "Elevation",
     "Blend of MOLA and Mars Express HRSC DEMs (ESA/DLR/FU Berlin); 200 m/px."),
    ("mola_roughness", "roughness", "Surface roughness",
     "Kilometre-scale vertical roughness from MOLA pulse/baseline statistics; not rock abundance."),
    ("THEMIS_DayIR_ControlledMosaics_100m_v2_oct2018", "thermal", "Thermal observations",
     "Daytime infrared brightness mosaic (relative, normalised between strips); not absolute temperature. Covers 65S-65N."),
    ("THEMIS_NightIR_ControlledMosaics_100m_v2_oct2018", "thermal", "Thermal observations",
     "Night-time infrared mosaic; brighter generally means rockier/higher thermal inertia. Covers 65S-65N."),
    ("TES_Thermal_Inertia", "thermal", "Thermal observations", "MGS TES; several km per pixel."),
    ("T1303_FeMgSmectite_Mineral_Indicator_SP", "mineral", "Mineralogical information",
     "CRISM spectral-parameter indicator map (relative band strength, not abundance); one CRISM map tile around Mawrth Vallis only."),
    ("MC18_PolySulfate_Mineral_IndicatorV2_SP", "mineral", "Mineralogical information",
     "CRISM spectral-parameter indicator map (relative band strength, not abundance); Mars Chart 18 (Coprates / Valles Marineris) only."),
    ("TES_Glass_Clay", "mineral", "Mineralogical information",
     "MGS TES spectral unmixing at ~7 km/px: sheet silicates and high-Si glass are not separable in this product."),
    ("TES_Dust", "mineral", "Mineralogical information", "MGS TES dust cover; several km per pixel."),
    ("SIM3292_Global_Geology", "geology", "Geology",
     "USGS SIM 3292 global geologic map (Tanaka et al., 2014), 1:20M scale."),
    ("Hynek_Valley_Networks", "geology", "Geology", "Valley network mapping (Hynek et al., 2010)."),
]


def get(client: httpx.Client, url: str, **params) -> httpx.Response:
    r = client.get(url, params=params or None, timeout=90, follow_redirects=True)
    r.raise_for_status()
    return r


def trek_search(client, **extra):
    r = get(client, TREK_SEARCH, proj=TREK_PROJ, start=0, rows=2000, **extra)
    return r.json()["response"]["docs"]


def probe_max_level(client, url: str, bbox: list[float], advertised: int) -> int:
    """Deepest level that actually serves a tile at the centre of the layer's footprint.

    Some Trek capabilities documents advertise more TileMatrix levels than the tile store holds
    (the Viking MDIM2.1 mosaic advertises 0-9 but 404s beyond 7), which would otherwise produce
    failed requests and blank tiles when zooming in.
    """
    lon, lat = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    for z in range(advertised, -1, -1):
        nx, ny = 2 * 2 ** z, 2 ** z
        x, y = int((lon + 180) / 360 * nx), int((90 - lat) / 180 * ny)
        try:
            r = client.get(url.format(z=z, x=x, y=y), timeout=40)
        except httpx.HTTPError:
            continue
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
            return z
    return 0


def ingest_layers(client):
    products = {d["productLabel"]: d for d in trek_search(client, facetKeys="itemType", facetValues="product")}
    layers = []
    for label, category, category_title, limitation in LAYERS:
        xml = get(client, TREK_TILES.format(label=label)).text
        fmt = re.search(r"<Format>([^<]+)", xml).group(1)
        template = re.search(r'template="([^"]+)"', xml).group(1)
        levels = len(re.findall(r"<TileMatrix>", xml))
        tms = re.search(r"<TileMatrixSet>([^<]+)</TileMatrixSet>\s*</TileMatrixSetLink>", xml)
        tms = tms.group(1) if tms else "default028mm"
        url = (template.replace("{Style}", "default").replace("{TileMatrixSet}", tms)
               .replace("{TileMatrix}", "{z}").replace("{TileRow}", "{y}").replace("{TileCol}", "{x}")
               .replace("1.0.0//", "1.0.0/"))
        p = products.get(label, {})
        bbox = [float(v) for v in p.get("bbox", "-180,-90,180,90").split(",")]
        advertised = levels - 1
        verified = probe_max_level(client, url, bbox, advertised) if "trek.nasa.gov" in url else advertised
        layers.append({
            "id": label, "category": category, "category_title": category_title,
            "title": p.get("title", label), "description": (p.get("description") or "").strip(),
            "mission": p.get("mission"), "instrument": p.get("instrument"),
            "source": ("NASA Solar System Treks (Mars Trek) WMTS" if "trek.nasa.gov" in url else
                       "USGS Astrogeology / Esri 'OnMars' ArcGIS tile service, as referenced by the NASA Mars Trek catalogue"),
            "source_url": TREK_TILES.format(label=label),
            "tile_url": url, "format": fmt, "max_level": verified, "advertised_max_level": advertised, "bbox": bbox,
            "catalog_date": p.get("data_created_date"), "limitations": limitation,
            "kind": "wmts",
        })
        print("layer", label, fmt, "advertised", advertised, "verified", verified)
    (OUT / "trek_layers.json").write_text(json.dumps({"retrieved": NOW, "layers": layers}, indent=1), encoding="utf-8")
    # full product catalogue (metadata only) for the Data Explorer
    cat = [{k: d.get(k) for k in ("productLabel", "title", "mission", "instrument", "productCat1", "productCat2",
                                   "bbox", "description", "data_created_date", "serviceTypes")} for d in products.values()]
    (OUT / "trek_catalog.json").write_text(json.dumps({"retrieved": NOW, "products": cat}), encoding="utf-8")


def ingest_nomenclature(client):
    docs = trek_search(client, facetKeys="itemType", facetValues="nomenclature")
    out = []
    for d in docs:
        m = re.match(r"POINT \(([-\d.]+) ([-\d.]+)\)", d.get("shape", ""))
        if not m:
            continue
        out.append({"name": d["title"], "feature_type": d.get("productCat2", "Unknown"),
                    "lon": float(m.group(1)), "lat": float(m.group(2))})
    (OUT / "nomenclature.json").write_text(json.dumps({
        "retrieved": NOW, "source": "IAU Gazetteer of Planetary Nomenclature via NASA Mars Trek search index",
        "source_url": TREK_SEARCH, "features": out}), encoding="utf-8")
    print("nomenclature", len(out))


def read_point_shapefile(zf: zipfile.ZipFile, stem: str):
    """Minimal reader for point shapefiles (shape type 1) + dBase III attributes."""
    dbf = zf.read(stem + ".dbf")
    n, hl, rl = struct.unpack("<IHH", dbf[4:12])
    fields, o = [], 32
    while dbf[o] != 0x0D:
        fields.append((dbf[o:o + 11].split(b"\0")[0].decode(), dbf[o + 16]))
        o += 32
    rows = []
    for i in range(n):
        rec, p, row = dbf[hl + i * rl: hl + (i + 1) * rl], 1, {}
        for name, ln in fields:
            row[name] = rec[p:p + ln].decode("latin1").strip()
            p += ln
        rows.append(row)
    return rows


def ingest_hydrous(client):
    r = get(client, TREK_STREAM, label="Hydrous_Mineral_Detections_CRISM_clon0")
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    out, seen = [], set()
    for stem, inst, mission in (("Hydrous_Mineral_Detections_CRISM_clon0", "CRISM", "Mars Reconnaissance Orbiter"),
                                ("Hydrous_Mineral_Detections_OMEGA_clon0", "OMEGA", "Mars Express")):
        for row in read_point_shapefile(zf, stem):
            lat, lon = float(row["Latitude"]), float(row["Long_East"])
            key = (round(lon, 3), round(lat, 3), inst)
            if key in seen:
                continue
            seen.add(key)
            out.append({"lon": lon, "lat": lat, "instrument": inst, "mission": mission})
    (OUT / "hydrous_minerals.json").write_text(json.dumps({
        "retrieved": NOW,
        "source": "Hydrous Mineral Detections (OMEGA, CRISM), distributed by NASA Mars Trek",
        "source_url": TREK_STREAM + "?label=Hydrous_Mineral_Detections_CRISM_clon0",
        "reference": "Carter, J., Poulet, F., Bibring, J.-P., Mangold, N., Murchie, S. (2013), Hydrous minerals on Mars "
                     "as seen by the CRISM and OMEGA imaging spectrometers: Updated global view, JGR Planets 118, 831-858.",
        "limitations": "Point locations of detections only; the distributed file does not carry the mineral class of "
                       "each detection. Absence of a point is not evidence of absence (coverage is targeted).",
        "detections": out}), encoding="utf-8")
    print("hydrous", len(out))


def ingest_rovers(client):
    out = {"retrieved": NOW, "rovers": {}}
    for key, name, base in (("perseverance", "Perseverance (Mars 2020)", "https://mars.nasa.gov/mmgis-maps/M20/Layers/json/M20_"),
                            ("curiosity", "Curiosity (MSL)", "https://mars.nasa.gov/mmgis-maps/MSL/Layers/json/MSL_")):
        wps = get(client, base + "waypoints.json").json()["features"]
        tr = get(client, base + "traverse.json").json()["features"]
        waypoints = []
        for f in wps:
            p = f["properties"]
            if p.get("final", p.get("drive_type")) not in ("y", "final"):
                continue
            waypoints.append({"sol": p["sol"], "lon": round(p["lon"], 6), "lat": round(p["lat"], 6),
                              "elev_m": round(p["elev_geoid"], 1), "dist_total_m": round(p.get("dist_total_m") or 0, 1)})
        waypoints.sort(key=lambda w: w["sol"])
        line = []
        for f in tr:
            g = f["geometry"]
            segs = g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]
            for seg in segs:
                line.extend([round(c[0], 6), round(c[1], 6)] for c in seg)
        step = max(1, len(line) // 4000)
        line = line[::step] + [line[-1]]
        out["rovers"][key] = {"name": name, "source": "NASA/JPL-Caltech rover localisation (MMGIS map layers)",
                              "source_url": base + "waypoints.json", "latest_sol": waypoints[-1]["sol"],
                              "waypoints": waypoints, "traverse": line}
        print(key, len(waypoints), len(line))
    (OUT / "rover_traverses.json").write_text(json.dumps(out), encoding="utf-8")


def ingest_weather(client):
    rems = get(client, "https://mars.nasa.gov/rss/api/", feed="weather", category="msl", feedtype="json").json()
    meda = get(client, "https://mars.nasa.gov/rss/api/", feed="weather", category="mars2020", feedtype="json").json()
    (OUT / "weather_snapshot.json").write_text(json.dumps({
        "retrieved": NOW, "rems": {"soles": rems["soles"][:700]}, "meda": meda}), encoding="utf-8")
    print("weather", len(rems["soles"]), len(meda["sols"]))


def main():
    with httpx.Client(headers={"User-Agent": "mars-x-ingest/1.0"}) as client:
        steps = [ingest_layers, ingest_nomenclature, ingest_hydrous, ingest_rovers, ingest_weather]
        only = sys.argv[1:]
        for fn in steps:
            if only and fn.__name__.replace("ingest_", "") not in only:
                continue
            fn(client)


if __name__ == "__main__":
    main()
