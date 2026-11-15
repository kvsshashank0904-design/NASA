"""Terrain intelligence: slope, roughness, hazard classification, profiles, overlays."""
from __future__ import annotations

import io
import math

import numpy as np
from scipy import ndimage

from ..mars import great_circle_points, haversine_m
from .dem import Q_INTERPOLATED, Q_MEASURED, Q_NODATA, DemGrid, get_dem

# Hazard classes. Slope thresholds are *planning assumptions* for a crewed rover,
# not NASA flight rules; they are exposed as request parameters.
H_NOMINAL, H_CAUTION, H_HIGH, H_IMPASSABLE, H_UNKNOWN = 0, 1, 2, 3, 4
HAZARD_LABELS = {H_NOMINAL: "nominal", H_CAUTION: "caution", H_HIGH: "high", H_IMPASSABLE: "impassable",
                 H_UNKNOWN: "unknown (no elevation data)"}
QUALITY_LABELS = {Q_MEASURED: "measured", Q_INTERPOLATED: "interpolated between measurements", Q_NODATA: "no data"}


def fill_nan(z: np.ndarray) -> np.ndarray:
    """Nearest-neighbour fill so derivative filters do not spread NaN; callers re-mask afterwards."""
    mask = np.isnan(z)
    if not mask.any():
        return z
    if mask.all():
        return np.zeros_like(z)
    idx = ndimage.distance_transform_edt(mask, return_distances=False, return_indices=True)
    return z[tuple(idx)]


def slope_deg(grid: DemGrid) -> np.ndarray:
    """Slope magnitude (degrees) by central differences at the grid's own baseline.

    East-west spacing is scaled by cos(latitude) per row because both DEMs are
    plate-carree on the Mars sphere.
    """
    z = fill_nan(grid.z.astype(np.float64))
    dzdy = np.gradient(z, grid.dy_m, axis=0)
    dzdx = np.gradient(z, axis=1) / grid.dx_m()[:, None]
    s = np.degrees(np.arctan(np.hypot(dzdx, dzdy))).astype(np.float32)
    s[np.isnan(grid.z)] = np.nan
    return s


def roughness_m(grid: DemGrid) -> np.ndarray:
    """RMS elevation residual (m) from the 3x3 local mean, i.e. relief at the DEM pixel scale.

    This is roughness at the DEM baseline (20 m or 463 m), NOT rock abundance.
    """
    z = fill_nan(grid.z.astype(np.float64))
    resid = z - ndimage.uniform_filter(z, 3, mode="nearest")
    r = np.sqrt(np.maximum(ndimage.uniform_filter(resid ** 2, 3, mode="nearest"), 0.0)).astype(np.float32)
    r[np.isnan(grid.z)] = np.nan
    return r


def hazard_classes(grid: DemGrid, slope: np.ndarray, caution_deg: float = 10.0, high_deg: float = 20.0,
                   max_deg: float = 30.0) -> np.ndarray:
    h = np.full(slope.shape, H_NOMINAL, dtype=np.uint8)
    h[slope >= caution_deg] = H_CAUTION
    h[slope >= high_deg] = H_HIGH
    h[slope >= max_deg] = H_IMPASSABLE
    h[grid.quality == Q_NODATA] = H_UNKNOWN
    return h


def analyze_region(west: float, south: float, east: float, north: float, max_cells: int = 250_000,
                   caution_deg: float = 10.0, high_deg: float = 20.0, max_deg: float = 30.0) -> dict:
    grid = get_dem(west, south, east, north)
    stride = max(1, math.ceil(math.sqrt(grid.z.size / max_cells)))
    grid = grid.downsample(stride)
    s = slope_deg(grid)
    r = roughness_m(grid)
    h = hazard_classes(grid, s, caution_deg, high_deg, max_deg)
    n = h.size
    valid = ~np.isnan(grid.z)
    return {
        "grid": grid, "slope": s, "roughness": r, "hazard": h,
        "summary": {
            "bbox": grid.bbox,
            "dem": grid.info(),
            "cells": int(n),
            "elevation_m": {"min": _f(np.nanmin(grid.z)), "max": _f(np.nanmax(grid.z)), "mean": _f(np.nanmean(grid.z))} if valid.any() else None,
            "slope_deg": {"mean": _f(np.nanmean(s)), "p95": _f(np.nanpercentile(s, 95)), "max": _f(np.nanmax(s))} if valid.any() else None,
            "roughness_m": {"mean": _f(np.nanmean(r)), "p95": _f(np.nanpercentile(r, 95))} if valid.any() else None,
            "hazard_fraction": {HAZARD_LABELS[k]: round(float((h == k).sum()) / n, 4) for k in HAZARD_LABELS},
            "quality_fraction": {QUALITY_LABELS[k]: round(float((grid.quality == k).sum()) / n, 4) for k in QUALITY_LABELS},
            "thresholds_deg": {"caution": caution_deg, "high": high_deg, "impassable": max_deg},
            "hazard_basis": "INFERRED from DEM slope at the stated resolution. No hazards here are directly observed; "
                            "features smaller than the DEM pixel are invisible to this analysis."
                            + (" With MOLA (463 m baselines) 'nominal' only means no regional slope hazard was resolved, "
                               "not that the terrain is safe." if grid.source.startswith("mola") else ""),
        },
    }


def _f(v) -> float | None:
    v = float(v)
    return None if math.isnan(v) else round(v, 2)


def terrain_profile(lon1: float, lat1: float, lon2: float, lat2: float, samples: int = 200) -> dict:
    dist = haversine_m(lon1, lat1, lon2, lat2)
    pad_lat = max(0.02, abs(lat2 - lat1) * 0.05)
    pad_lon = max(0.02, abs(lon2 - lon1) * 0.05)
    grid = get_dem(min(lon1, lon2) - pad_lon, min(lat1, lat2) - pad_lat, max(lon1, lon2) + pad_lon, max(lat1, lat2) + pad_lat)
    samples = int(min(max(samples, 2), max(2, dist / grid.cell_m * 2 + 2), 1000))
    pts = great_circle_points(lon1, lat1, lon2, lat2, samples)
    out, prev = [], None
    for i, (lo, la) in enumerate(pts):
        z, q = grid.sample(lo, la)
        d = dist * i / (samples - 1)
        slope = None
        if prev is not None and not math.isnan(z) and prev[1] is not None and d > prev[0]:
            slope = round(math.degrees(math.atan((z - prev[1]) / (d - prev[0]))), 2)
        zz = None if math.isnan(z) else round(z, 1)
        out.append({"distance_m": round(d, 1), "lon": round(lo, 6), "lat": round(la, 6), "elevation_m": zz,
                    "slope_deg": slope, "quality": QUALITY_LABELS[q]})
        prev = (d, zz)
    zs = [p["elevation_m"] for p in out if p["elevation_m"] is not None]
    ups = [b - a for a, b in zip(zs, zs[1:]) if b > a]
    downs = [a - b for a, b in zip(zs, zs[1:]) if b < a]
    return {
        "distance_m": round(dist, 1), "samples": out, "dem": grid.info(),
        "ascent_m": round(sum(ups), 1), "descent_m": round(sum(downs), 1),
        "min_elevation_m": min(zs) if zs else None, "max_elevation_m": max(zs) if zs else None,
        "note": "Straight great-circle profile; slopes are along-track at the sample spacing.",
    }


# --------------------------------------------------------------------------- overlays

def _ramp(v: np.ndarray, stops: list[tuple[float, tuple[int, int, int]]]) -> np.ndarray:
    xs = [s[0] for s in stops]
    out = np.zeros(v.shape + (3,), dtype=np.float32)
    for ch in range(3):
        out[..., ch] = np.interp(v, xs, [s[1][ch] for s in stops])
    return out


HAZARD_COLORS = {H_NOMINAL: (46, 204, 113, 70), H_CAUTION: (241, 196, 15, 150), H_HIGH: (230, 126, 34, 185),
                 H_IMPASSABLE: (231, 76, 60, 215), H_UNKNOWN: (120, 120, 140, 200)}


def overlay_png(kind: str, analysis: dict) -> bytes:
    """RGBA PNG covering analysis['grid'].bbox; rows are evenly spaced in latitude (plate carree)."""
    from PIL import Image
    grid: DemGrid = analysis["grid"]
    if kind == "slope":
        s = np.nan_to_num(analysis["slope"], nan=0.0)
        rgb = _ramp(s, [(0, (20, 60, 160)), (5, (40, 170, 200)), (10, (240, 220, 70)), (20, (240, 130, 40)), (30, (220, 40, 40)), (60, (130, 0, 60))])
        a = np.clip(60 + s * 9, 60, 220)
    elif kind == "elevation":
        z = analysis["grid"].z
        lo, hi = np.nanmin(z), np.nanmax(z)
        t = np.nan_to_num((z - lo) / max(1e-6, hi - lo), nan=0.0)
        rgb = _ramp(t, [(0, (30, 40, 120)), (0.35, (40, 150, 150)), (0.6, (210, 190, 110)), (0.85, (200, 110, 60)), (1, (250, 245, 235))])
        a = np.full(z.shape, 170.0)
    elif kind == "roughness":
        r = np.nan_to_num(analysis["roughness"], nan=0.0)
        t = np.clip(r / max(1e-6, float(np.nanpercentile(analysis["roughness"], 99))), 0, 1)
        rgb = _ramp(t, [(0, (30, 30, 60)), (0.5, (160, 80, 170)), (1, (255, 220, 120))])
        a = 50 + t * 170
    elif kind == "quality":
        q = grid.quality
        rgb = np.zeros(q.shape + (3,), dtype=np.float32)
        rgb[q == Q_MEASURED] = (60, 200, 255)
        rgb[q == Q_INTERPOLATED] = (255, 170, 60)
        rgb[q == Q_NODATA] = (120, 120, 140)
        a = np.where(q == Q_MEASURED, 60.0, 170.0)
    elif kind == "hazard":
        h = analysis["hazard"]
        rgba = np.zeros(h.shape + (4,), dtype=np.uint8)
        for k, col in HAZARD_COLORS.items():
            rgba[h == k] = col
        return _png(rgba)
    else:
        raise ValueError(f"unknown overlay kind {kind}")
    a = np.where(np.isnan(grid.z), 0, a)
    rgba = np.dstack([rgb, a]).astype(np.uint8)
    return _png(rgba)


def _png(rgba: np.ndarray) -> bytes:
    from PIL import Image
    im = Image.fromarray(rgba, "RGBA")
    # upscale small rasters so the overlay is crisp cells rather than blurred by the GPU
    scale = max(1, min(8, 1024 // max(rgba.shape[0], rgba.shape[1])))
    if scale > 1:
        im = im.resize((rgba.shape[1] * scale, rgba.shape[0] * scale), Image.NEAREST)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=False)
    return buf.getvalue()
