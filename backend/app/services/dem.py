"""Elevation access with lazy, cached, windowed reads of real NASA DEMs.

Two sources, both verified:

* MGS MOLA MEGDR 128 px/deg (463 m/px at the equator), PDS Geosciences Node.
  The .IMG products are raw big-endian int16 rasters, so we fetch only the
  latitude bands we need with HTTP Range requests and cache them as .npy.
  The companion MEGC "counts" product (shots per pixel) tells us which pixels
  are interpolated rather than measured.
* Mars 2020 TRN CTX stereo DTM mosaic of Jezero crater at 20 m/px
  (USGS Astrogeology), a 9.7 MB GeoTIFF downloaded once on first use.

Coordinates: planetocentric latitude, east-positive longitude, sphere radius
3,396,190 m. Elevations are metres relative to the MOLA areoid.
"""
from __future__ import annotations

import logging
import math
import threading
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import numpy as np

from ..config import settings
from ..mars import MARS_RADIUS_M, lon360, norm_lon

log = logging.getLogger("marsx.dem")

Q_MEASURED, Q_INTERPOLATED, Q_NODATA = 0, 1, 2

MOLA_BASE = "https://pds-geosciences.wustl.edu/mgs/mgs-m-mola-5-megdr-l3-v1/mgsl_300x/meg128/"
MOLA_PPD = 128
MOLA_TILE_ROWS, MOLA_TILE_COLS = 5632, 11520        # 44 deg x 90 deg
MOLA_LAT_TOPS = [(88, "88n"), (44, "44n"), (0, "00n"), (-44, "44s")]
MOLA_MAX_WINDOW_DEG = 10.0

MOLA16_BASE = "https://pds-geosciences.wustl.edu/mgs/mgs-m-mola-5-megdr-l3-v1/mgsl_300x/meg016/"
GALE_HIRISE_URL = "https://planetarymaps.usgs.gov/mosaic/Mars/MSL/MSL_Gale_DEM_Mosaic_1m_v3.tif"
JEZERO_HIRISE_URL = ("https://planetarymaps.usgs.gov/mosaic/mars2020_trn/HiRISE/"
                     "JEZ_hirise_soc_006_DTM_MOLAtopography_DeltaGeoid_1m_Eqc_latTs0_lon0_blend40.tif")
MOLA128_MAX_SPAN_DEG = 4.0      # larger windows switch to the 16 px/deg global grid
CTX_URL = ("https://planetarymaps.usgs.gov/mosaic/mars2020_trn/CTX/"
           "JEZ_ctx_B_soc_008_DTM_MOLAtopography_DeltaGeoid_20m_Eqc_latTs0_lon0.tif")
CTX_FILE = "jezero_ctx_dtm_20m.tif"

SOURCES = {
    "mola": {
        "id": "mola_megdr_128",
        "name": "MGS MOLA MEGDR 128 px/deg topography",
        "mission": "Mars Global Surveyor", "instrument": "MOLA",
        "resolution_m": 463.0,
        "vertical_datum": "MOLA areoid (GMM-2B)",
        "source_url": MOLA_BASE,
        "limitations": "463 m/px gridded laser altimetry; many pixels (especially near the equator) are interpolated "
                       "between ground tracks. Resolves regional slopes only - cannot detect rocks, dunes, scarps or "
                       "any hazard smaller than several hundred metres.",
    },
    "ctx": {
        "id": "jezero_ctx_dtm_20m",
        "name": "Mars 2020 TRN CTX stereo DTM mosaic, Jezero crater, 20 m",
        "mission": "Mars Reconnaissance Orbiter", "instrument": "CTX",
        "resolution_m": 20.0,
        "vertical_datum": "MOLA areoid (tied to MOLA)",
        "source_url": CTX_URL,
        "limitations": "20 m/px stereo photogrammetry; resolves slopes at 20 m baselines. Cannot resolve boulders, "
                       "sand ripples or metre-scale scarps; stereo matching artefacts possible in bland terrain.",
    },
}


SOURCES["mola16"] = {
    "id": "mola_megdr_16",
    "name": "MGS MOLA MEGDR 16 px/deg global topography",
    "mission": "Mars Global Surveyor", "instrument": "MOLA",
    "resolution_m": 3705.0,
    "vertical_datum": "MOLA areoid (GMM-2B)",
    "source_url": MOLA16_BASE,
    "limitations": "3.7 km/px global grid, used for long-range planning and the 3D relief of the globe. Shows regional "
                   "topography only (basins, volcanoes, canyon walls); useless for local hazard assessment.",
}
SOURCES["hirise_gale"] = {
    "id": "gale_hirise_dem_1m",
    "name": "MSL Gale crater HiRISE DEM mosaic, 1 m (v3)",
    "mission": "Mars Reconnaissance Orbiter", "instrument": "HiRISE",
    "resolution_m": 1.0,
    "vertical_datum": "MOLA areoid (tied to MOLA)",
    "source_url": GALE_HIRISE_URL,
    "limitations": "1 m/px stereo DEM read in windows and resampled to 2 m. Resolves ridges, hollows and scarps of a few "
                   "metres; individual rocks under ~2 m and loose sand are still invisible. Stereo artefacts are possible.",
}
SOURCES["hirise_jezero"] = {
    "id": "jezero_hirise_dtm_1m",
    "name": "Mars 2020 TRN HiRISE DTM mosaic, Jezero crater, 1 m",
    "mission": "Mars Reconnaissance Orbiter", "instrument": "HiRISE",
    "resolution_m": 1.0,
    "vertical_datum": "MOLA areoid (tied to MOLA)",
    "source_url": JEZERO_HIRISE_URL,
    "limitations": "1 m/px stereo DTM read in windows and resampled to 2 m. Resolves metre-scale relief; rocks under ~2 m "
                   "and loose sand are still invisible. Stereo artefacts are possible.",
}


class DemUnavailable(RuntimeError):
    pass


@dataclass
class DemGrid:
    z: np.ndarray                 # (rows, cols) float32 metres, row 0 = north, NaN = no data
    quality: np.ndarray           # uint8: Q_MEASURED / Q_INTERPOLATED / Q_NODATA
    lats: np.ndarray              # cell-centre latitudes, descending
    lons: np.ndarray              # cell-centre longitudes, ascending, may exceed 180 when wrapping
    source: str                   # "mola" | "ctx"
    stride: int = 1
    meta: dict = field(default_factory=dict)

    @property
    def dlat(self) -> float:
        return float(abs(self.lats[0] - self.lats[-1]) / max(1, len(self.lats) - 1))

    @property
    def dlon(self) -> float:
        return float(abs(self.lons[-1] - self.lons[0]) / max(1, len(self.lons) - 1))

    @property
    def dy_m(self) -> float:
        return math.radians(self.dlat) * MARS_RADIUS_M

    def dx_m(self) -> np.ndarray:
        """East-west ground spacing per row: both sources are plate-carree, so it shrinks with cos(lat)."""
        return math.radians(self.dlon) * MARS_RADIUS_M * np.cos(np.radians(self.lats))

    @property
    def cell_m(self) -> float:
        return float(max(self.dy_m, float(np.max(self.dx_m()))))

    @property
    def bbox(self) -> list[float]:
        return [float(self.lons[0] - self.dlon / 2), float(self.lats[-1] - self.dlat / 2),
                float(self.lons[-1] + self.dlon / 2), float(self.lats[0] + self.dlat / 2)]

    def info(self) -> dict:
        s = dict(SOURCES[self.source])
        s["effective_resolution_m"] = round(self.cell_m, 1)
        s["stride"] = self.stride
        return s

    def index(self, lon: float, lat: float) -> tuple[int, int]:
        lon = self._unwrap(lon)
        r = int(round((self.lats[0] - lat) / self.dlat)) if self.dlat else 0
        c = int(round((lon - self.lons[0]) / self.dlon)) if self.dlon else 0
        return min(max(r, 0), len(self.lats) - 1), min(max(c, 0), len(self.lons) - 1)

    def _unwrap(self, lon: float) -> float:
        while lon < self.lons[0] - 180:
            lon += 360
        while lon > self.lons[0] + 180:
            lon -= 360
        return lon

    def contains(self, lon: float, lat: float) -> bool:
        lon = self._unwrap(lon)
        b = self.bbox
        return b[0] <= lon <= b[2] and b[1] <= lat <= b[3]

    def sample(self, lon: float, lat: float) -> tuple[float, int]:
        """Bilinear elevation (m) and worst quality flag of the contributing cells."""
        lon = self._unwrap(lon)
        fr = (self.lats[0] - lat) / self.dlat if self.dlat else 0.0
        fc = (lon - self.lons[0]) / self.dlon if self.dlon else 0.0
        r0 = int(np.clip(math.floor(fr), 0, len(self.lats) - 1)); r1 = min(r0 + 1, len(self.lats) - 1)
        c0 = int(np.clip(math.floor(fc), 0, len(self.lons) - 1)); c1 = min(c0 + 1, len(self.lons) - 1)
        tr, tc = float(np.clip(fr - r0, 0, 1)), float(np.clip(fc - c0, 0, 1))
        vals = np.array([self.z[r0, c0], self.z[r0, c1], self.z[r1, c0], self.z[r1, c1]], dtype=float)
        w = np.array([(1 - tr) * (1 - tc), (1 - tr) * tc, tr * (1 - tc), tr * tc])
        q = int(max(self.quality[r0, c0], self.quality[r0, c1], self.quality[r1, c0], self.quality[r1, c1]))
        ok = ~np.isnan(vals)
        if not ok.any() or w[ok].sum() <= 0:
            return float("nan"), Q_NODATA
        return float((vals[ok] * w[ok]).sum() / w[ok].sum()), q

    def downsample(self, stride: int) -> "DemGrid":
        if stride <= 1:
            return self
        rows, cols = (self.z.shape[0] // stride) * stride, (self.z.shape[1] // stride) * stride
        if rows < stride or cols < stride:
            return self
        zb = self.z[:rows, :cols].reshape(rows // stride, stride, cols // stride, stride)
        qb = self.quality[:rows, :cols].reshape(rows // stride, stride, cols // stride, stride)
        with np.errstate(all="ignore"):
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                z = np.nanmean(zb, axis=(1, 3)).astype(np.float32)
        q = qb.max(axis=(1, 3)).astype(np.uint8)
        q[np.isnan(z)] = Q_NODATA
        lats = self.lats[:rows].reshape(-1, stride).mean(axis=1)
        lons = self.lons[:cols].reshape(-1, stride).mean(axis=1)
        return DemGrid(z, q, lats, lons, self.source, self.stride * stride, dict(self.meta))


# --------------------------------------------------------------------------- MOLA

_lock = threading.Lock()
_band_mem: dict[str, np.ndarray] = {}


def _http_get(url: str, headers: dict | None = None) -> bytes:
    if settings.offline:
        raise DemUnavailable(f"offline mode: {url} is not cached")
    try:
        with httpx.Client(timeout=settings.http_timeout_s, follow_redirects=True,
                          headers={"User-Agent": "mars-x/1.0"}) as c:
            r = c.get(url, headers=headers or {})
            r.raise_for_status()
            return r.content
    except httpx.HTTPError as e:
        raise DemUnavailable(f"could not fetch {url}: {e}") from e


def _band_key(kind: str, lat_code: str, lon_code: int, band: int) -> tuple[str, str]:
    name = f"meg{kind}{lat_code}{lon_code:03d}hb"
    return name, f"{name}_b{band:02d}"


def _band_path(key: str) -> Path:
    return settings.cache_dir / "mola128" / f"{key}.npy"


def _fetch_band(kind: str, lat_code: str, lon_code: int, band: int) -> None:
    """Download one 1-degree band to the disk cache (no-op when present). Safe to call from several threads."""
    name, key = _band_key(kind, lat_code, lon_code, band)
    path = _band_path(key)
    if path.exists():
        return
    bps = 2 if kind == "t" else 1
    row_bytes = MOLA_TILE_COLS * bps
    start = band * MOLA_PPD * row_bytes
    end = start + MOLA_PPD * row_bytes - 1
    log.info("fetching MOLA band %s (%0.1f MB)", key, (end - start) / 1e6)
    raw = _http_get(MOLA_BASE + name + ".img", {"Range": f"bytes={start}-{end}"})
    if len(raw) != MOLA_PPD * row_bytes:
        raise DemUnavailable(f"unexpected MOLA range response size {len(raw)} for {key}")
    arr = np.frombuffer(raw, dtype=">i2" if kind == "t" else "u1").reshape(MOLA_PPD, MOLA_TILE_COLS)
    arr = arr.astype(np.int16 if kind == "t" else np.uint8)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{threading.get_ident()}.tmp")
    with open(tmp, "wb") as f:
        np.save(f, arr)
    tmp.replace(path)


def _mola_band(kind: str, lat_code: str, lon_code: int, band: int) -> np.ndarray:
    """One 1-degree latitude band (128 rows x 11520 cols) of a MEGDR tile. kind: 't' topography, 'c' counts."""
    _, key = _band_key(kind, lat_code, lon_code, band)
    arr = _band_mem.get(key)
    if arr is not None:
        return arr
    _fetch_band(kind, lat_code, lon_code, band)
    arr = np.load(_band_path(key))
    with _lock:
        if len(_band_mem) > 64:
            _band_mem.pop(next(iter(_band_mem)))
        _band_mem[key] = arr
    return arr


def mola128_cached(lon: float, lat: float) -> bool:
    """True when the 128 px/deg bands around a point are already on disk (so a read costs no network)."""
    if not -87.9 < lat < 87.9:
        return False
    band_g = int(math.floor((88.0 - lat) * MOLA_PPD)) // MOLA_PPD
    tile_i = band_g // 44
    lon_tile = int(lon360(lon) * MOLA_PPD) // MOLA_TILE_COLS
    return all(_band_path(_band_key(k, MOLA_LAT_TOPS[tile_i][1], lon_tile * 90, band_g - tile_i * 44)[1]).exists() for k in "tc")


def mola_window(west: float, south: float, east: float, north: float) -> DemGrid:
    """MOLA grid covering the bbox (east-positive degrees; west may be > east when crossing the antimeridian)."""
    south, north = max(south, -87.999), min(north, 87.999)
    if north <= south:
        raise DemUnavailable("MOLA MEGDR 128 px/deg tiles cover 88S-88N only")
    w360, e360 = lon360(west), lon360(east)
    if e360 <= w360:
        e360 += 360.0
    if (e360 - w360) > MOLA_MAX_WINDOW_DEG or (north - south) > MOLA_MAX_WINDOW_DEG:
        raise DemUnavailable(f"requested window exceeds {MOLA_MAX_WINDOW_DEG} degrees; narrow the analysis region")
    gr0 = int(math.floor((88.0 - north) * MOLA_PPD)); gr1 = int(math.ceil((88.0 - south) * MOLA_PPD))
    gc0 = int(math.floor(w360 * MOLA_PPD)); gc1 = int(math.ceil(e360 * MOLA_PPD))
    gr1, gc1 = max(gr1, gr0 + 2), max(gc1, gc0 + 2)
    rows, cols = gr1 - gr0, gc1 - gc0
    z = np.empty((rows, cols), dtype=np.float32)
    cnt = np.empty((rows, cols), dtype=np.uint8)
    total_cols = 360 * MOLA_PPD
    # fetch every missing band in parallel before assembling (first use of a region is network-bound)
    need = set()
    for band_g in range(gr0 // MOLA_PPD, (gr1 - 1) // MOLA_PPD + 1):
        tile_i = band_g // 44
        for lt in {(c % total_cols) // MOLA_TILE_COLS for c in (gc0, gc1 - 1)}:
            for kind in "tc":
                need.add((kind, MOLA_LAT_TOPS[tile_i][1], lt * 90, band_g - tile_i * 44))
    missing = [k for k in need if not _band_path(_band_key(*k)[1]).exists()]
    if missing:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(lambda k: _fetch_band(*k), missing))
    for band_g in range(gr0 // MOLA_PPD, (gr1 - 1) // MOLA_PPD + 1):
        tile_i = band_g // 44                      # which latitude tile (0..3)
        lat_code = MOLA_LAT_TOPS[tile_i][1]
        band = band_g - tile_i * 44
        ra, rb = max(gr0, band_g * MOLA_PPD), min(gr1, (band_g + 1) * MOLA_PPD)
        c = gc0
        while c < gc1:
            cm = c % total_cols
            lon_tile = cm // MOLA_TILE_COLS
            cend = min(gc1, c + (MOLA_TILE_COLS - cm % MOLA_TILE_COLS))
            sl_r = slice(ra - band_g * MOLA_PPD, rb - band_g * MOLA_PPD)
            sl_c = slice(cm - lon_tile * MOLA_TILE_COLS, cm - lon_tile * MOLA_TILE_COLS + (cend - c))
            z[ra - gr0: rb - gr0, c - gc0: cend - gc0] = _mola_band("t", lat_code, lon_tile * 90, band)[sl_r, sl_c]
            cnt[ra - gr0: rb - gr0, c - gc0: cend - gc0] = _mola_band("c", lat_code, lon_tile * 90, band)[sl_r, sl_c]
            c = cend
    lats = 88.0 - (np.arange(gr0, gr1) + 0.5) / MOLA_PPD
    lons = (np.arange(gc0, gc1) + 0.5) / MOLA_PPD
    if lons[0] >= 180.0:
        lons = lons - 360.0
    quality = np.where(cnt > 0, Q_MEASURED, Q_INTERPOLATED).astype(np.uint8)
    return DemGrid(z, quality, lats, lons, "mola")


# --------------------------------------------------------------------------- CTX (Jezero)

_ctx: DemGrid | None = None
_ctx_failed: str | None = None


def _read_geotiff(path: Path) -> tuple[np.ndarray, float, float, float]:
    """Returns (array, x0_m, y0_m, pixel_m). Uses rasterio when importable, else Pillow + GeoTIFF tags."""
    try:
        import rasterio  # optional: native DLLs can be blocked by OS policy on some hosts
        with rasterio.open(path) as ds:
            arr = ds.read(1).astype(np.float32)
            t = ds.transform
            nod = ds.nodata
            if nod is not None:
                arr[arr == np.float32(nod)] = np.nan
            return arr, t.c, t.f, t.a
    except Exception as e:  # noqa: BLE001 - fall back to the pure-Python reader
        log.info("rasterio unavailable (%s); reading GeoTIFF with Pillow", type(e).__name__)
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    im = Image.open(path)
    scale, tie = im.tag_v2[33550], im.tag_v2[33922]
    arr = np.array(im, dtype=np.float32)
    arr[arr < -1e30] = np.nan
    return arr, float(tie[3]), float(tie[4]), float(scale[0])


def ctx_grid() -> DemGrid | None:
    """Full Jezero CTX DTM as a DemGrid, or None when it cannot be obtained."""
    global _ctx, _ctx_failed
    if _ctx is not None or _ctx_failed:
        return _ctx
    path = settings.cache_dir / CTX_FILE
    with _lock:
        try:
            if not path.exists():
                log.info("downloading Jezero CTX DTM (9.7 MB)")
                path.write_bytes(_http_get(CTX_URL))
            arr, x0, y0, px = _read_geotiff(path)
        except Exception as e:  # noqa: BLE001
            _ctx_failed = str(e)
            log.warning("CTX DTM unavailable: %s", e)
            return None
        rows, cols = arr.shape
        # Equirectangular, standard parallel 0, sphere R: lon = x / R, lat = y / R
        lons = np.degrees((x0 + (np.arange(cols) + 0.5) * px) / MARS_RADIUS_M)
        lats = np.degrees((y0 - (np.arange(rows) + 0.5) * px) / MARS_RADIUS_M)
        quality = np.where(np.isnan(arr), Q_NODATA, Q_MEASURED).astype(np.uint8)
        _ctx = DemGrid(arr, quality, lats, lons, "ctx")
    return _ctx


def ctx_window(west: float, south: float, east: float, north: float) -> DemGrid | None:
    g = ctx_grid()
    if g is None:
        return None
    b = g.bbox
    if west < b[0] or east > b[2] or south < b[1] or north > b[3] or east <= west:
        return None
    r0, c0 = g.index(west, north)
    r1, c1 = g.index(east, south)
    if r1 - r0 < 2 or c1 - c0 < 2:
        r1, c1 = min(r0 + 3, g.z.shape[0] - 1), min(c0 + 3, g.z.shape[1] - 1)
    sub = DemGrid(g.z[r0:r1 + 1, c0:c1 + 1], g.quality[r0:r1 + 1, c0:c1 + 1], g.lats[r0:r1 + 1], g.lons[c0:c1 + 1], "ctx")
    if np.isnan(sub.z).mean() > 0.5:
        return None
    return sub


def ctx_footprint() -> list[float] | None:
    g = ctx_grid()
    return g.bbox if g is not None else None


# --------------------------------------------------------------------------- MOLA 16 px/deg (global)

MOLA16_PPD, MOLA16_ROWS, MOLA16_COLS = 16, 2880, 5760
_mola16: tuple[np.ndarray, np.ndarray] | None = None
_mola16_lock = threading.Lock()


def mola16_ready() -> bool:
    return _mola16 is not None or all((settings.cache_dir / f"mola16_{k}.npy").exists() for k in "tc")


def mola16() -> tuple[np.ndarray, np.ndarray]:
    """Global 16 px/deg topography (int16 m) and shot counts; 2 x 33 MB downloaded once, then local."""
    global _mola16
    if _mola16 is not None:
        return _mola16
    with _mola16_lock:
        if _mola16 is not None:
            return _mola16
        out = []
        for kind in "tc":
            path = settings.cache_dir / f"mola16_{kind}.npy"
            if not path.exists():
                log.info("downloading global MOLA 16 px/deg (%s), 33 MB", kind)
                raw = _http_get(f"{MOLA16_BASE}meg{kind}90n000eb.img")
                if len(raw) != MOLA16_ROWS * MOLA16_COLS * 2:
                    raise DemUnavailable(f"unexpected size for global MOLA 16 px/deg ({len(raw)} bytes)")
                arr = np.frombuffer(raw, dtype=">i2").reshape(MOLA16_ROWS, MOLA16_COLS).astype(np.int16)
                tmp = path.with_suffix(".tmp")
                with open(tmp, "wb") as f:
                    np.save(f, arr)
                tmp.replace(path)
            out.append(np.load(path, mmap_mode="r"))
        _mola16 = (out[0], out[1])
    return _mola16


def mola16_window(west: float, south: float, east: float, north: float) -> DemGrid:
    z, cnt = mola16()
    south, north = max(south, -89.9), min(north, 89.9)
    w360, e360 = lon360(west), lon360(east)
    if e360 <= w360:
        e360 += 360.0
    r0 = int(math.floor((90.0 - north) * MOLA16_PPD))
    r1 = min(max(int(math.ceil((90.0 - south) * MOLA16_PPD)), r0 + 3), MOLA16_ROWS)
    c0 = int(math.floor(w360 * MOLA16_PPD))
    c1 = max(int(math.ceil(e360 * MOLA16_PPD)), c0 + 3)
    cols = np.arange(c0, c1) % MOLA16_COLS
    zz = np.asarray(z[r0:r1])[:, cols].astype(np.float32)
    cc = np.asarray(cnt[r0:r1])[:, cols]
    lats = 90.0 - (np.arange(r0, r1) + 0.5) / MOLA16_PPD
    lons = (np.arange(c0, c1) + 0.5) / MOLA16_PPD
    if lons[0] >= 180.0:
        lons = lons - 360.0
    return DemGrid(zz, np.where(cc > 0, Q_MEASURED, Q_INTERPOLATED).astype(np.uint8), lats, lons, "mola16")


def mola16_sample_grid(lons: np.ndarray, lats: np.ndarray) -> np.ndarray:
    """Bilinear elevations (m) for a lat x lon mesh from the global grid; used for globe terrain tiles."""
    from scipy import ndimage
    z, _ = mola16()
    rr = np.clip((90.0 - lats) * MOLA16_PPD - 0.5, 0, MOLA16_ROWS - 1)
    cc = np.mod(lons, 360.0) * MOLA16_PPD - 0.5
    if cc.max() - cc.min() > MOLA16_COLS / 2:        # tile touches the 0/360 seam: unwrap
        cc = np.where(cc < MOLA16_COLS / 2, cc + MOLA16_COLS, cc)
    r0, r1 = int(max(0, math.floor(rr.min()) - 1)), int(min(MOLA16_ROWS, math.ceil(rr.max()) + 2))
    c0, c1 = int(math.floor(cc.min()) - 1), int(math.ceil(cc.max()) + 2)
    sub = np.asarray(z[r0:r1])[:, np.arange(c0, c1) % MOLA16_COLS].astype(np.float32)
    R, Cc = np.meshgrid(rr - r0, cc - c0, indexing="ij")
    return ndimage.map_coordinates(sub, [R, Cc], order=1, mode="nearest")


# --------------------------------------------------------------------------- HiRISE 1 m patches (windowed reads)

HIRES_PATCHES = {
    # id: source, bbox [west, south, east, north], resample step in native 1 m pixels
    "gale_boxwork": {"source": "hirise_gale", "bbox": [137.368, -4.831, 137.397, -4.793], "step": 2,
                     "title": "Mount Sharp boxwork region (Curiosity sols ~4500-5073)"},
    "jezero_delta": {"source": "hirise_jezero", "bbox": [77.394, 18.424, 77.461, 18.470], "step": 2,
                     "title": "Jezero landing site to western delta front"},
}
_patches: dict[str, DemGrid] = {}


def _tiff_layout(url: str) -> dict:
    """Minimal classic-TIFF reader over HTTP Range: size, strip table, compression, georeferencing tags."""
    import struct

    def rng(a: int, n: int) -> bytes:
        return _http_get(url, {"Range": f"bytes={a}-{a + n - 1}"})

    b = rng(0, 8)
    if b[:4] != b"II*\x00":
        raise DemUnavailable("unsupported TIFF flavour (expected little-endian classic TIFF)")
    off = struct.unpack("<I", b[4:8])[0]
    d = rng(off, 2 + 64 * 12)
    n = struct.unpack("<H", d[:2])[0]
    tags = {}
    for i in range(n):
        t, ty, cnt = struct.unpack("<HHI", d[2 + i * 12: 10 + i * 12])
        tags[t] = (ty, cnt, d[10 + i * 12: 14 + i * 12])
    fmt = {3: ("H", 2), 4: ("I", 4), 12: ("d", 8)}

    def val(t, default=None):
        if t not in tags:
            return default
        ty, cnt, raw = tags[t]
        ch, sz = fmt[ty]
        size = sz * cnt
        data = raw[:size] if size <= 4 else rng(struct.unpack("<I", raw)[0], size)
        v = struct.unpack(f"<{cnt}{ch}", data)
        return v[0] if cnt == 1 else v

    nodata = None
    if 42113 in tags:
        _, cnt, raw = tags[42113]
        txt = raw[:cnt] if cnt <= 4 else rng(struct.unpack("<I", raw)[0], cnt)
        nodata = float(txt.decode("latin1").strip("\0 "))
    lay = {"width": val(256), "height": val(257), "compression": val(259), "predictor": val(317, 1),
           "rows_per_strip": val(278), "scale": val(33550), "tie": val(33922),
           "strip_offsets_at": struct.unpack("<I", tags[273][2])[0], "strip_counts_at": struct.unpack("<I", tags[279][2])[0],
           "nodata": nodata}
    if lay["rows_per_strip"] != 1 or val(258) != 32 or val(339) != 3:
        raise DemUnavailable("unsupported TIFF layout (expected one 32-bit float row per strip)")
    return lay


def _decode_lzw_rows(blobs: list[bytes], width: int, predictor: int) -> np.ndarray:
    """Decode LZW-compressed float32 strips by wrapping them in an in-memory TIFF that Pillow (libtiff) can open."""
    import io
    import struct
    from PIL import Image
    n = len(blobs)
    entries = [(256, 4, 1, width), (257, 4, 1, n), (258, 3, 1, 32), (259, 3, 1, 5), (262, 3, 1, 1), (277, 3, 1, 1),
               (278, 4, 1, 1), (284, 3, 1, 1), (317, 3, 1, predictor), (339, 3, 1, 3)]
    ifd_off = 8
    ifd_len = 2 + (len(entries) + 2) * 12 + 4
    offs_at = ifd_off + ifd_len
    cnts_at = offs_at + 4 * n
    data_at = cnts_at + 4 * n
    offsets, pos = [], data_at
    for bl in blobs:
        offsets.append(pos)
        pos += len(bl)
    entries += [(273, 4, n, offs_at if n > 1 else offsets[0]), (279, 4, n, cnts_at if n > 1 else len(blobs[0]))]
    entries.sort()
    buf = io.BytesIO()
    buf.write(b"II*\x00" + struct.pack("<I", ifd_off) + struct.pack("<H", len(entries)))
    for t, ty, cnt, v in entries:
        buf.write(struct.pack("<HHI", t, ty, cnt) + (struct.pack("<HH", v, 0) if ty == 3 and cnt == 1 else struct.pack("<I", v)))
    buf.write(struct.pack("<I", 0))
    buf.write(struct.pack(f"<{n}I", *offsets) + struct.pack(f"<{n}I", *[len(bl) for bl in blobs]))
    for bl in blobs:
        buf.write(bl)
    buf.seek(0)
    return np.array(Image.open(buf), dtype=np.float32)


def build_patch(pid: str) -> DemGrid:
    """Read a window of a 1 m HiRISE DEM over HTTP (row by row), resample, and cache it as .npz."""
    import struct
    from concurrent.futures import ThreadPoolExecutor
    spec = HIRES_PATCHES[pid]
    url = SOURCES[spec["source"]]["source_url"]
    lay = _tiff_layout(url)
    px, x0, y0 = lay["scale"][0], lay["tie"][3], lay["tie"][4]
    west, south, east, north = spec["bbox"]
    step = spec["step"]
    # equirectangular, standard parallel 0, lon0 0 on the Mars sphere: x = R*lon, y = R*lat
    c0 = max(0, int((math.radians(west) * MARS_RADIUS_M - x0) / px))
    c1 = min(lay["width"], int(math.ceil((math.radians(east) * MARS_RADIUS_M - x0) / px)))
    r0 = max(0, int((y0 - math.radians(north) * MARS_RADIUS_M) / px))
    r1 = min(lay["height"], int(math.ceil((y0 - math.radians(south) * MARS_RADIUS_M) / px)))
    if c1 - c0 < 10 or r1 - r0 < 10:
        raise DemUnavailable(f"patch {pid} lies outside the source DEM")
    rows = list(range(r0, r1, step))
    offs = struct.unpack(f"<{r1 - r0}I", _http_get(url, {"Range": f"bytes={lay['strip_offsets_at'] + 4 * r0}-{lay['strip_offsets_at'] + 4 * r1 - 1}"}))
    cnts = struct.unpack(f"<{r1 - r0}I", _http_get(url, {"Range": f"bytes={lay['strip_counts_at'] + 4 * r0}-{lay['strip_counts_at'] + 4 * r1 - 1}"}))
    log.info("building HiRISE patch %s: %d rows x %d cols at %g m", pid, len(rows), (c1 - c0) // step, px * step)
    client = httpx.Client(timeout=settings.http_timeout_s, follow_redirects=True, headers={"User-Agent": "mars-x/1.0"})

    def fetch(r: int) -> bytes:
        o = offs[r - r0]
        if lay["compression"] == 1:                      # uncompressed: read just the needed columns of the row
            a, b = o + 4 * c0, o + 4 * c1 - 1
        else:                                            # LZW: the whole compressed row is needed
            a, b = o, o + cnts[r - r0] - 1
        for attempt in range(4):
            try:
                resp = client.get(url, headers={"Range": f"bytes={a}-{b}"})
                resp.raise_for_status()
                return resp.content
            except httpx.HTTPError:
                if attempt == 3:
                    raise
        return b""

    try:
        with ThreadPoolExecutor(max_workers=12) as ex:
            blobs = list(ex.map(fetch, rows))
    except httpx.HTTPError as e:
        raise DemUnavailable(f"could not read HiRISE DEM window: {e}") from e
    finally:
        client.close()
    if lay["compression"] == 1:
        arr = np.stack([np.frombuffer(bl, dtype="<f4") for bl in blobs])[:, ::step]
    elif lay["compression"] == 5:
        full = np.concatenate([_decode_lzw_rows(blobs[i:i + 200], lay["width"], lay["predictor"]) for i in range(0, len(blobs), 200)])
        arr = full[:, c0:c1:step]
    else:
        raise DemUnavailable(f"unsupported TIFF compression {lay['compression']}")
    arr = np.array(arr, dtype=np.float32)
    nod = lay["nodata"]
    if nod is not None:
        arr[(arr == np.float32(nod)) | (arr < -1e30)] = np.nan
    lats = np.degrees((y0 - (np.array(rows) + 0.5) * px) / MARS_RADIUS_M)
    lons = np.degrees((x0 + (np.arange(c0, c1, step) + 0.5) * px) / MARS_RADIUS_M)
    out = settings.cache_dir / "hires"
    out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out / f"{pid}.npz", z=arr, lats=lats, lons=lons)
    _patches.pop(pid, None)
    return _load_patch(pid)


def _load_patch(pid: str) -> DemGrid | None:
    if pid in _patches:
        return _patches[pid]
    path = settings.cache_dir / "hires" / f"{pid}.npz"
    if not path.exists():
        return None
    d = np.load(path)
    z = d["z"]
    g = DemGrid(z, np.where(np.isnan(z), Q_NODATA, Q_MEASURED).astype(np.uint8), d["lats"], d["lons"], HIRES_PATCHES[pid]["source"],
                meta={"patch": pid})
    _patches[pid] = g
    return g


def patches() -> list[DemGrid]:
    return [g for g in (_load_patch(p) for p in HIRES_PATCHES) if g is not None]


def _sub(g: DemGrid, west: float, south: float, east: float, north: float) -> DemGrid | None:
    """Sub-window of a local grid; None when the request is not inside its footprint."""
    b = g.bbox
    if west < b[0] - 1e-9 or east > b[2] + 1e-9 or south < b[1] - 1e-9 or north > b[3] + 1e-9 or east <= west:
        return None
    r0, c0 = g.index(west, north)
    r1, c1 = g.index(east, south)
    if r1 - r0 < 2 or c1 - c0 < 2:
        r1, c1 = min(r0 + 3, g.z.shape[0] - 1), min(c0 + 3, g.z.shape[1] - 1)
    sub = DemGrid(g.z[r0:r1 + 1, c0:c1 + 1], g.quality[r0:r1 + 1, c0:c1 + 1], g.lats[r0:r1 + 1], g.lons[c0:c1 + 1], g.source, meta=dict(g.meta))
    return None if np.isnan(sub.z).mean() > 0.5 else sub


def local_grids() -> list[DemGrid]:
    """Local high-resolution grids, best first: HiRISE patches, then the Jezero CTX DTM."""
    out = patches()
    c = ctx_grid()
    if c is not None:
        out.append(c)
    return out


# --------------------------------------------------------------------------- public API

def get_dem(west: float, south: float, east: float, north: float, prefer: str = "auto") -> DemGrid:
    """Best available DEM for the bbox: HiRISE patch > CTX 20 m (Jezero) > MOLA 463 m > MOLA 3.7 km (large windows)."""
    west, east = norm_lon(west), norm_lon(east)
    if prefer == "auto":
        for g in local_grids():
            sub = _sub(g, west, south, east, north)
            if sub is not None:
                return sub
    span_lon = (lon360(east) - lon360(west)) % 360.0
    small = span_lon <= MOLA128_MAX_SPAN_DEG and (north - south) <= MOLA128_MAX_SPAN_DEG and abs(north) < 87.9 and abs(south) < 87.9
    if small and prefer != "mola16":
        return mola_window(west, south, east, north)
    return mola16_window(west, south, east, north)


def dem_for_route(lon1: float, lat1: float, lon2: float, lat2: float, west: float, south: float, east: float, north: float) -> DemGrid:
    """DEM for a route: if both endpoints sit inside one local grid, use it and clip the padded window to its footprint."""
    for g in local_grids():
        if g.contains(lon1, lat1) and g.contains(lon2, lat2):
            b = g.bbox
            sub = _sub(g, max(west, b[0]), max(south, b[1]), min(east, b[2]), min(north, b[3]))
            if sub is not None:
                return sub
    return get_dem(west, south, east, north, prefer="global")


def sample_elevation(lon: float, lat: float) -> dict:
    """Point elevation from the best source that needs no large download, with provenance."""
    lon = norm_lon(lon)
    for g in local_grids():
        if g.contains(lon, lat):
            z, q = g.sample(lon, lat)
            if not math.isnan(z):
                return {"elevation_m": round(z, 1), "quality": q, "source": SOURCES[g.source]}
    if mola128_cached(lon, lat) or not mola16_ready():
        d = 2.0 / MOLA_PPD
        m = mola_window(lon - d, lat - d, lon + d, lat + d)
        src = "mola"
    else:   # answer instantly from the global grid instead of pulling 4 MB of 128 px/deg bands for one click
        d = 2.0 / MOLA16_PPD
        m = mola16_window(lon - d, lat - d, lon + d, lat + d)
        src = "mola16"
    z, q = m.sample(lon, lat)
    return {"elevation_m": None if math.isnan(z) else round(z, 1), "quality": q, "source": SOURCES[src]}


def terrain_tile(level: int, x: int, y: int, size: int = 33) -> np.ndarray:
    """Heightmap (size x size float32, row 0 = north) for a geographic 2x1 tile; hi-res grids where they cover the tile."""
    span = 180.0 / (2 ** level)
    west, north = -180.0 + x * span, 90.0 - y * span
    lons = west + np.linspace(0.0, span, size)
    lats = north - np.linspace(0.0, span, size)
    h = mola16_sample_grid(lons, lats)
    if level >= 9:
        for g in local_grids():
            b = g.bbox
            if west + span < b[0] or west > b[2] or north < b[1] or north - span > b[3]:
                continue
            rr = (g.lats[0] - lats) / g.dlat
            cc = (lons - g.lons[0]) / g.dlon
            inside_r = (rr >= 0) & (rr <= len(g.lats) - 1)
            inside_c = (cc >= 0) & (cc <= len(g.lons) - 1)
            if not inside_r.any() or not inside_c.any():
                continue
            ri = np.clip(np.round(rr).astype(int), 0, len(g.lats) - 1)
            ci = np.clip(np.round(cc).astype(int), 0, len(g.lons) - 1)
            local = g.z[np.ix_(ri, ci)]
            mask = inside_r[:, None] & inside_c[None, :] & ~np.isnan(local)
            h = np.where(mask, local, h)
            break
    return h.astype(np.float32)


def cache_status() -> dict:
    d = settings.cache_dir / "mola128"
    files = list(d.glob("*.npy")) if d.exists() else []
    ctx = settings.cache_dir / CTX_FILE
    return {
        "mola_bands_cached": len(files),
        "mola_cache_mb": round(sum(f.stat().st_size for f in files) / 1e6, 1),
        "mola16_global_cached": mola16_ready(),
        "hires_patches": {pid: (settings.cache_dir / "hires" / f"{pid}.npz").exists() for pid in HIRES_PATCHES},
        "ctx_dtm_cached": ctx.exists(),
        "ctx_dtm_mtime": ctx.stat().st_mtime if ctx.exists() else None,
        "cache_dir": str(settings.cache_dir),
    }
