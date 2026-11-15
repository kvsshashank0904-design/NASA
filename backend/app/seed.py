"""Create tables (SQLite dev) and load catalogue data. Idempotent."""
from __future__ import annotations

import logging

from sqlalchemy import func, select, text

from .db import IS_POSTGRES, Base, SessionLocal, engine
from .models import Dataset, Location, Observation, ScienceTarget, ScientificReference
from .services import catalog

log = logging.getLogger("marsx.seed")


def init_db() -> None:
    if not IS_POSTGRES:
        # SQLite dev database: create directly. PostgreSQL deployments run `alembic upgrade head`.
        Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(Dataset)) == 0:
            retrieved = catalog.trek_layers()["retrieved"]
            for d in catalog.DATASETS:
                db.add(Dataset(**d, retrieved_at=retrieved))
            for rid, cit, url in catalog.REFERENCES:
                db.add(ScientificReference(id=rid, citation=cit, url=url))
            db.commit()
        if db.scalar(select(func.count()).select_from(Location)) == 0:
            src = catalog.nomenclature()["source"]
            for f in catalog.nomenclature()["features"]:
                db.add(Location(name=f["name"], feature_type=f["feature_type"], kind="nomenclature", lon=f["lon"], lat=f["lat"], source=src))
            for name, lon, lat, desc in catalog.LANDING_SITES:
                db.add(Location(name=name, feature_type="Landing site", kind="landing_site", lon=lon, lat=lat, description=desc,
                                source="NASA mission records; position cross-checked against Mars Trek HiRISE landing-site mosaics"))
            db.commit()
        if db.scalar(select(func.count()).select_from(ScienceTarget)) == 0:
            for t in catalog.resolve_targets():
                db.add(ScienceTarget(id=t["id"], name=t["name"], category=t["category"], lon=t["lon"], lat=t["lat"], summary=t["summary"],
                                     evidence=t["evidence"], hypothesis=t["hypothesis"], minerals=t["minerals"], scores=t["scores"],
                                     coordinate_source=t["coordinate_source"], datasets=t["datasets"], reference_ids=t["refs"]))
            db.commit()
        if db.scalar(select(func.count()).select_from(Observation)) == 0:
            snap = catalog.weather_snapshot()
            for s in snap["rems"]["soles"]:
                db.add(Observation(dataset_id="rems_weather", station="rems", sol=int(s["sol"]), terrestrial_date=s["terrestrial_date"],
                                   ls=_f(s.get("ls")), lon=137.4, lat=-4.6,
                                   values={k: s.get(k) for k in ("min_temp", "max_temp", "pressure", "min_gts_temp", "max_gts_temp", "atmo_opacity", "local_uv_irradiance_index")}))
            for s in snap["meda"]["sols"]:
                db.add(Observation(dataset_id="meda_weather", station="meda", sol=int(s["sol"]), terrestrial_date=s["terrestrial_date"],
                                   ls=_f(s.get("ls")), lon=77.4, lat=18.4, values={k: s.get(k) for k in ("min_temp", "max_temp", "pressure")}))
            db.commit()
        if IS_POSTGRES:
            # keep PostGIS geometry columns in step with lon/lat (columns are created by the Alembic migration)
            for tbl in ("locations", "science_targets"):
                db.execute(text(f"UPDATE {tbl} SET geom = ST_SetSRID(ST_MakePoint(lon, lat), 949900) WHERE geom IS NULL"))
            db.commit()
    log.info("database ready")


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
