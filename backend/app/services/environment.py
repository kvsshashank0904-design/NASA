"""Environmental and survival intelligence from REMS (Curiosity), MEDA (Perseverance) and RAD.

Every value is tagged with one of four kinds so the UI can never present a
historical observation as live weather:
    latest_observation | historical_observation | derived_estimate | simulated
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timezone

import httpx

from ..config import settings
from ..mars import solar_flux_toa
from . import catalog

log = logging.getLogger("marsx.env")

FEEDS = {
    "rems": "https://mars.nasa.gov/rss/api/?feed=weather&category=msl&feedtype=json",
    "meda": "https://mars.nasa.gov/rss/api/?feed=weather&category=mars2020&feedtype=json",
}
STATIONS = {
    "rems": {"station": "Curiosity REMS", "mission": "Mars Science Laboratory", "instrument": "REMS",
             "location": "Gale crater (about 4.6S, 137.4E)", "dataset_id": "rems_weather"},
    "meda": {"station": "Perseverance MEDA", "mission": "Mars 2020", "instrument": "MEDA",
             "location": "Jezero crater (about 18.4N, 77.4E)", "dataset_id": "meda_weather"},
}

# Published MSL/RAD values (Hassler et al., 2014). Constants from the paper, not processed by MARS-X.
RAD = {
    "kind": "historical_observation",
    "instrument": "RAD", "mission": "Mars Science Laboratory (Curiosity)",
    "surface_gcr_dose_rate_mGy_per_day": {"value": 0.21, "uncertainty": 0.04},
    "surface_gcr_dose_equivalent_mSv_per_day": {"value": 0.64, "uncertainty": 0.12},
    "cruise_dose_equivalent_mSv_per_day": {"value": 1.84, "uncertainty": 0.33},
    "period": "2012-08 to 2013-06, Gale crater floor (about -4.4 km), near solar maximum",
    "reference": "Hassler et al. (2014) Science 343, 1244797; cruise value from Zeitlin et al. (2013) Science 340, 1080",
    "limitations": "Site- and epoch-specific averages. Galactic cosmic ray dose is higher near solar minimum and at higher "
                   "elevations; solar particle events add short, unpredictable spikes. Not a live measurement.",
    "dataset_id": "rad_surface",
}

_cache: dict[str, tuple[float, dict, str]] = {}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fetch(key: str) -> tuple[dict, str, str]:
    """Returns (payload, provenance, retrieved_iso). provenance: 'live feed' or 'bundled snapshot'."""
    now = time.time()
    if key in _cache and now - _cache[key][0] < settings.weather_ttl_s:
        return _cache[key][1], _cache[key][2], datetime.fromtimestamp(_cache[key][0], timezone.utc).isoformat(timespec="seconds")
    disk = settings.cache_dir / f"weather_{key}.json"
    if not settings.offline:
        try:
            with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "mars-x/1.0"}) as c:
                r = c.get(FEEDS[key])
                r.raise_for_status()
                data = r.json()
            if key == "rems":
                data = {"soles": data["soles"][:1400]}
            disk.write_text(json.dumps(data), encoding="utf-8")
            _cache[key] = (now, data, "live feed")
            return data, "live feed", datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="seconds")
        except Exception as e:  # noqa: BLE001 - any network/parse failure falls back to cache
            log.warning("weather feed %s unavailable: %s", key, e)
    if disk.exists():
        data = json.loads(disk.read_text(encoding="utf-8"))
        ts = datetime.fromtimestamp(disk.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
        return data, "local cache (feed unreachable)", ts
    snap = catalog.weather_snapshot()
    return snap[key], "bundled snapshot (feed unreachable)", snap["retrieved"]


def _rems_sols() -> tuple[list[dict], str, str]:
    data, prov, ts = _fetch("rems")
    out = []
    for s in data["soles"]:
        out.append({"sol": int(s["sol"]), "terrestrial_date": s["terrestrial_date"], "ls": _num(s.get("ls")),
                    "min_air_temp_c": _num(s.get("min_temp")), "max_air_temp_c": _num(s.get("max_temp")),
                    "min_ground_temp_c": _num(s.get("min_gts_temp")), "max_ground_temp_c": _num(s.get("max_gts_temp")),
                    "pressure_pa": _num(s.get("pressure")), "atmo_opacity": None if s.get("atmo_opacity") in (None, "--") else s["atmo_opacity"],
                    "uv_index": None if s.get("local_uv_irradiance_index") in (None, "--") else s["local_uv_irradiance_index"],
                    "sunrise": s.get("sunrise"), "sunset": s.get("sunset")})
    out.sort(key=lambda x: -x["sol"])
    return out, prov, ts


def _meda_sols() -> tuple[list[dict], str, str]:
    data, prov, ts = _fetch("meda")
    out = [{"sol": int(s["sol"]), "terrestrial_date": s["terrestrial_date"], "ls": _num(s.get("ls")),
            "min_air_temp_c": _num(s.get("min_temp")), "max_air_temp_c": _num(s.get("max_temp")),
            "pressure_pa": _num(s.get("pressure")), "sunrise": s.get("sunrise"), "sunset": s.get("sunset")}
           for s in data["sols"]]
    out.sort(key=lambda x: -x["sol"])
    return out, prov, ts


def _latest_complete(sols: list[dict]) -> dict | None:
    return next((s for s in sols if s["min_air_temp_c"] is not None and s["pressure_pa"] is not None), sols[0] if sols else None)


def _age_days(d: str) -> int | None:
    try:
        return (date.today() - date.fromisoformat(d)).days
    except ValueError:
        return None


def observations(station: str, limit: int = 60) -> dict:
    if station not in STATIONS:
        raise KeyError(station)
    sols, prov, ts = _rems_sols() if station == "rems" else _meda_sols()
    latest = _latest_complete(sols)
    age = _age_days(latest["terrestrial_date"]) if latest else None
    return {
        **STATIONS[station], "provenance": prov, "retrieved": ts,
        "latest": {"kind": "latest_observation", "age_days": age,
                   "note": f"Most recent sol in the feed, observed {age} days ago. This is not live weather." if age is not None else None,
                   **(latest or {})},
        "history": {"kind": "historical_observation", "sols": sols[:limit]},
        "unavailable": (["wind speed/direction (REMS wind sensor damaged at landing)", "humidity (not populated in the feed)"] if station == "rems"
                        else ["wind", "dust opacity", "humidity", "UV (not published in this feed; see PDS Atmospheres Node)"]),
    }


def _risk(latest: dict | None, station: str) -> dict:
    """Derived, transparent 0-100 EVA environmental risk index. A planning heuristic, not a NASA standard."""
    if not latest:
        return {"kind": "derived_estimate", "value": None, "factors": [], "note": "no observation available"}
    factors = []
    tmin = latest.get("min_air_temp_c")
    if tmin is not None:
        factors.append({"factor": "cold (night minimum air temperature)", "input": f"{tmin} C",
                        "score": round(min(1.0, max(0.0, (-tmin - 20) / 80)), 2), "weight": 0.35})
    if latest.get("min_air_temp_c") is not None and latest.get("max_air_temp_c") is not None:
        swing = latest["max_air_temp_c"] - latest["min_air_temp_c"]
        factors.append({"factor": "diurnal thermal cycling", "input": f"{swing:.0f} C swing", "score": round(min(1.0, swing / 100), 2), "weight": 0.2})
    uv = latest.get("uv_index")
    if uv:
        factors.append({"factor": "UV irradiance class (REMS)", "input": uv,
                        "score": {"Low": 0.2, "Moderate": 0.45, "High": 0.7, "Very_High": 0.9, "Very High": 0.9}.get(uv, 0.5), "weight": 0.2})
    op = latest.get("atmo_opacity")
    if op:
        factors.append({"factor": "atmospheric opacity class (REMS)", "input": op, "score": 0.15 if op == "Sunny" else 0.7, "weight": 0.25})
    wsum = sum(f["weight"] for f in factors)
    value = round(100 * sum(f["score"] * f["weight"] for f in factors) / wsum, 0) if wsum else None
    return {"kind": "derived_estimate", "value": value, "factors": factors, "station": STATIONS[station]["station"],
            "based_on_sol": latest.get("sol"), "based_on_date": latest.get("terrestrial_date"),
            "note": "Heuristic index from the latest available sol summary; radiation and wind are not included "
                    "(no current data). Not a NASA operational metric."}


def summary() -> dict:
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "stations": {}, "radiation": RAD}
    for key in STATIONS:
        try:
            o = observations(key, limit=30)
        except Exception as e:  # noqa: BLE001
            out["stations"][key] = {**STATIONS[key], "error": str(e)}
            continue
        latest = o["latest"]
        solar = None
        if latest.get("ls") is not None:
            solar = {"kind": "derived_estimate", "top_of_atmosphere_w_m2": round(solar_flux_toa(latest["ls"]), 1), "ls_deg": latest["ls"],
                     "note": "Orbital geometry only (Mars-Sun distance at this Ls). Surface irradiance is lower and depends on "
                             "dust opacity and sun elevation, which are not available here."}
        out["stations"][key] = {**o, "solar_context": solar, "risk": _risk(latest, key)}
    out["legend"] = {
        "latest_observation": "Most recent value published by the instrument feed - check its date.",
        "historical_observation": "Past measurements.",
        "derived_estimate": "Computed by MARS-X from observations with stated assumptions.",
        "simulated": "Scenario values that are not measurements (only in Mission Simulation).",
    }
    return out


def nearest_station(lon: float, lat: float) -> dict:
    from ..mars import haversine_m
    pos = {"rems": (137.4, -4.6), "meda": (77.4, 18.4)}
    d = {k: haversine_m(lon, lat, *v) for k, v in pos.items()}
    k = min(d, key=d.get)
    return {"station": k, "distance_km": round(d[k] / 1000, 1),
            "representativeness": ("local" if d[k] < 50_000 else
                                   "NOT representative of this location - nearest station is "
                                   f"{d[k] / 1000:.0f} km away; Mars has only two operating surface weather stations")}
