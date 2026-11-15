"""Initial schema: every table in app/models.py, plus PostGIS geometry on PostgreSQL.

Portable part (all dialects): the tables, columns and indexes declared in app/models.py.

PostgreSQL-only part:
  * CREATE EXTENSION postgis
  * a custom spatial_ref_sys row, SRID 949900 = GCS Mars 2000 sphere (r = 3,396,190 m),
    the reference surface of Mars Trek, the MOLA MEGDR and the Mars 2020 CTX DTM
  * geom geometry(Point, 949900) on locations and science_targets,
    geom geometry(LineString, 949900) on routes, each with a GiST index
  * triggers that keep geom in step with lon/lat (and with routes.geometry GeoJSON)

PostGIS `geography` must NOT be used for Mars data: geography computes on Earth's WGS84
spheroid regardless of the SRID's parameters, so every distance and area would be wrong.
Geometry columns here are for spatial indexing / bbox queries only; distances are computed
on the Mars sphere in application code (app/mars.py).

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-15
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MARS_SRID = 949900
MARS_SRTEXT = ('GEOGCS["GCS_Mars_2000_Sphere",DATUM["D_Mars_2000_Sphere",'
               'SPHEROID["Mars_2000_Sphere_IAU_IAG",3396190.0,0.0]],'
               'PRIMEM["Reference_Meridian",0.0],UNIT["Degree",0.0174532925199433]]')
MARS_PROJ4 = "+proj=longlat +a=3396190 +b=3396190 +no_defs"

TZ = sa.DateTime(timezone=True)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("id", sa.String(120), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("mission", sa.String(120), nullable=True),
        sa.Column("instrument", sa.String(120), nullable=True),
        sa.Column("category", sa.String(60), nullable=False),
        sa.Column("source", sa.String(255), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("observation_time", sa.String(255), nullable=True),
        sa.Column("coverage", sa.String(255), nullable=True),
        sa.Column("resolution", sa.String(120), nullable=True),
        sa.Column("data_format", sa.String(255), nullable=True),
        sa.Column("processing", sa.Text(), nullable=True),
        sa.Column("limitations", sa.Text(), nullable=True),
        sa.Column("integration", sa.String(60), nullable=False),
        sa.Column("retrieved_at", sa.String(40), nullable=True),
    )
    op.create_index("ix_datasets_mission", "datasets", ["mission"])
    op.create_index("ix_datasets_instrument", "datasets", ["instrument"])
    op.create_index("ix_datasets_category", "datasets", ["category"])

    op.create_table(
        "scientific_references",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("citation", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
    )

    op.create_table(
        "locations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("feature_type", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source", sa.String(255), nullable=False),
    )
    op.create_index("ix_locations_name", "locations", ["name"])
    op.create_index("ix_locations_feature_type", "locations", ["feature_type"])
    op.create_index("ix_locations_kind", "locations", ["kind"])
    op.create_index("ix_locations_lonlat", "locations", ["lon", "lat"])

    op.create_table(
        "science_targets",
        sa.Column("id", sa.String(120), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("hypothesis", sa.Text(), nullable=True),
        sa.Column("minerals", sa.JSON(), nullable=True),
        sa.Column("scores", sa.JSON(), nullable=True),
        sa.Column("coordinate_source", sa.Text(), nullable=False),
        sa.Column("datasets", sa.JSON(), nullable=True),
        sa.Column("reference_ids", sa.JSON(), nullable=True),
    )
    op.create_index("ix_science_targets_name", "science_targets", ["name"])
    op.create_index("ix_science_targets_category", "science_targets", ["category"])
    op.create_index("ix_targets_lonlat", "science_targets", ["lon", "lat"])

    op.create_table(
        "observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_id", sa.String(120), sa.ForeignKey("datasets.id"), nullable=False),
        sa.Column("station", sa.String(60), nullable=False),
        sa.Column("sol", sa.Integer(), nullable=False),
        sa.Column("terrestrial_date", sa.String(20), nullable=True),
        sa.Column("ls", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("values", sa.JSON(), nullable=False),
    )
    op.create_index("ix_observations_dataset_id", "observations", ["dataset_id"])
    op.create_index("ix_observations_station", "observations", ["station"])
    op.create_index("ix_observations_sol", "observations", ["sol"])

    op.create_table(
        "missions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("start_lon", sa.Float(), nullable=False),
        sa.Column("start_lat", sa.Float(), nullable=False),
        sa.Column("goal_lon", sa.Float(), nullable=True),
        sa.Column("goal_lat", sa.Float(), nullable=True),
        sa.Column("objectives", sa.JSON(), nullable=True),
        sa.Column("target_ids", sa.JSON(), nullable=True),
        sa.Column("constraints", sa.JSON(), nullable=True),
        sa.Column("selected_route_id", sa.Integer(), nullable=True),
        sa.Column("return_route_id", sa.Integer(), nullable=True),
        sa.Column("created_at", TZ, nullable=False),
    )

    op.create_table(
        "routes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mission_id", sa.Integer(), sa.ForeignKey("missions.id"), nullable=True),
        sa.Column("plan_id", sa.String(40), nullable=False),
        sa.Column("profile", sa.String(40), nullable=False),
        sa.Column("distance_m", sa.Float(), nullable=False),
        sa.Column("energy_wh", sa.Float(), nullable=True),
        sa.Column("duration_h", sa.Float(), nullable=True),
        sa.Column("dem_source", sa.String(60), nullable=False),
        sa.Column("geometry", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
    )
    op.create_index("ix_routes_mission_id", "routes", ["mission_id"])
    op.create_index("ix_routes_plan_id", "routes", ["plan_id"])

    op.create_table(
        "route_segments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("route_id", sa.Integer(), sa.ForeignKey("routes.id"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("start_m", sa.Float(), nullable=False),
        sa.Column("end_m", sa.Float(), nullable=False),
        sa.Column("hazard", sa.String(40), nullable=False),
        sa.Column("quality", sa.String(40), nullable=False),
    )
    op.create_index("ix_route_segments_route_id", "route_segments", ["route_id"])

    op.create_table(
        "hazard_geometries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mission_id", sa.Integer(), sa.ForeignKey("missions.id"), nullable=True),
        sa.Column("basis", sa.String(40), nullable=False),
        sa.Column("hazard", sa.String(40), nullable=False),
        sa.Column("west", sa.Float(), nullable=False),
        sa.Column("south", sa.Float(), nullable=False),
        sa.Column("east", sa.Float(), nullable=False),
        sa.Column("north", sa.Float(), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("created_at", TZ, nullable=False),
    )
    op.create_index("ix_hazard_geometries_mission_id", "hazard_geometries", ["mission_id"])

    op.create_table(
        "mission_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mission_id", sa.Integer(), sa.ForeignKey("missions.id"), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("created_at", TZ, nullable=False),
    )
    op.create_index("ix_mission_logs_mission_id", "mission_logs", ["mission_id"])

    op.create_table(
        "cached_resources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(255), nullable=False, unique=True),
        sa.Column("kind", sa.String(60), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("fetched_at", TZ, nullable=False),
    )

    if _is_postgres():
        _postgis_upgrade()


def _postgis_upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    # Custom CRS for the IAU 2000 Mars sphere. Geometry only - never geography (see module docstring).
    op.execute(
        "INSERT INTO spatial_ref_sys (srid, auth_name, auth_srid, srtext, proj4text) "
        f"VALUES ({MARS_SRID}, 'MARSX', {MARS_SRID}, '{MARS_SRTEXT}', '{MARS_PROJ4}') "
        "ON CONFLICT (srid) DO NOTHING"
    )
    op.execute(f"ALTER TABLE locations ADD COLUMN geom geometry(Point, {MARS_SRID})")
    op.execute(f"ALTER TABLE science_targets ADD COLUMN geom geometry(Point, {MARS_SRID})")
    op.execute(f"ALTER TABLE routes ADD COLUMN geom geometry(LineString, {MARS_SRID})")
    op.execute("CREATE INDEX ix_locations_geom ON locations USING GIST (geom)")
    op.execute("CREATE INDEX ix_science_targets_geom ON science_targets USING GIST (geom)")
    op.execute("CREATE INDEX ix_routes_geom ON routes USING GIST (geom)")

    # Keep geom in step with the portable columns the application writes.
    op.execute(f"""
        CREATE OR REPLACE FUNCTION marsx_point_geom() RETURNS trigger AS $$
        BEGIN
            NEW.geom := ST_SetSRID(ST_MakePoint(NEW.lon, NEW.lat), {MARS_SRID});
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute(f"""
        CREATE OR REPLACE FUNCTION marsx_route_geom() RETURNS trigger AS $$
        BEGIN
            IF NEW.geometry IS NOT NULL AND (NEW.geometry ->> 'type') = 'LineString' THEN
                -- route GeoJSON carries (lon, lat, elevation_m); the indexed geometry is 2-D
                NEW.geom := ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON(NEW.geometry::text), {MARS_SRID}));
            ELSE
                NEW.geom := NULL;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    for tbl in ("locations", "science_targets"):
        op.execute(f"CREATE TRIGGER trg_{tbl}_geom BEFORE INSERT OR UPDATE OF lon, lat ON {tbl} "
                   "FOR EACH ROW EXECUTE FUNCTION marsx_point_geom()")
    op.execute("CREATE TRIGGER trg_routes_geom BEFORE INSERT OR UPDATE OF geometry ON routes "
               "FOR EACH ROW EXECUTE FUNCTION marsx_route_geom()")


def downgrade() -> None:
    if _is_postgres():
        for tbl in ("locations", "science_targets", "routes"):
            op.execute(f"DROP TRIGGER IF EXISTS trg_{tbl}_geom ON {tbl}")
        op.execute("DROP FUNCTION IF EXISTS marsx_point_geom()")
        op.execute("DROP FUNCTION IF EXISTS marsx_route_geom()")
    for tbl in ("cached_resources", "mission_logs", "hazard_geometries", "route_segments", "routes", "missions",
                "observations", "science_targets", "locations", "scientific_references", "datasets"):
        op.drop_table(tbl)
    if _is_postgres():
        # The postgis extension is left installed; only the MARS-X CRS row is removed.
        op.execute(f"DELETE FROM spatial_ref_sys WHERE srid = {MARS_SRID}")
