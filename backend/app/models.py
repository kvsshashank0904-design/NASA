"""Relational schema. Portable columns live here; on PostgreSQL the Alembic migration
additionally adds PostGIS geometry columns (SRID 949900, Mars 2000 sphere) with GiST
indexes, kept in sync by triggers. Distances are always computed on the Mars sphere in
application code - PostGIS `geography` assumes Earth's WGS84 spheroid and must not be used.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    mission: Mapped[str | None] = mapped_column(String(120), index=True)
    instrument: Mapped[str | None] = mapped_column(String(120), index=True)
    category: Mapped[str] = mapped_column(String(60), index=True)
    source: Mapped[str] = mapped_column(String(255))
    source_url: Mapped[str] = mapped_column(Text)
    observation_time: Mapped[str | None] = mapped_column(String(255))
    coverage: Mapped[str | None] = mapped_column(String(255))
    resolution: Mapped[str | None] = mapped_column(String(120))
    data_format: Mapped[str | None] = mapped_column(String(255))
    processing: Mapped[str | None] = mapped_column(Text)
    limitations: Mapped[str | None] = mapped_column(Text)
    integration: Mapped[str] = mapped_column(String(60))   # live | snapshot | lazy-cache | reference
    retrieved_at: Mapped[str | None] = mapped_column(String(40))


class ScientificReference(Base):
    __tablename__ = "scientific_references"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    citation: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)


class Location(Base):
    __tablename__ = "locations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    feature_type: Mapped[str] = mapped_column(String(80), index=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)     # nomenclature | landing_site
    lon: Mapped[float] = mapped_column(Float)
    lat: Mapped[float] = mapped_column(Float)
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(255))
    __table_args__ = (Index("ix_locations_lonlat", "lon", "lat"),)


class ScienceTarget(Base):
    __tablename__ = "science_targets"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    category: Mapped[str] = mapped_column(String(80), index=True)
    lon: Mapped[float] = mapped_column(Float)
    lat: Mapped[float] = mapped_column(Float)
    summary: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str | None] = mapped_column(Text)         # what has been observed
    hypothesis: Mapped[str | None] = mapped_column(Text)       # interpretation, not established fact
    minerals: Mapped[list | None] = mapped_column(JSON)
    scores: Mapped[dict | None] = mapped_column(JSON)          # relevance / geology / confidence priors
    coordinate_source: Mapped[str] = mapped_column(Text)
    datasets: Mapped[list | None] = mapped_column(JSON)
    reference_ids: Mapped[list | None] = mapped_column(JSON)
    __table_args__ = (Index("ix_targets_lonlat", "lon", "lat"),)


class Observation(Base):
    __tablename__ = "observations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    station: Mapped[str] = mapped_column(String(60), index=True)
    sol: Mapped[int] = mapped_column(Integer, index=True)
    terrestrial_date: Mapped[str | None] = mapped_column(String(20))
    ls: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    lat: Mapped[float | None] = mapped_column(Float)
    values: Mapped[dict] = mapped_column(JSON)


class Mission(Base):
    __tablename__ = "missions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(40), default="planned")
    start_lon: Mapped[float] = mapped_column(Float)
    start_lat: Mapped[float] = mapped_column(Float)
    goal_lon: Mapped[float | None] = mapped_column(Float)
    goal_lat: Mapped[float | None] = mapped_column(Float)
    objectives: Mapped[list | None] = mapped_column(JSON)
    target_ids: Mapped[list | None] = mapped_column(JSON)
    constraints: Mapped[dict | None] = mapped_column(JSON)
    selected_route_id: Mapped[int | None] = mapped_column(Integer)
    return_route_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    routes: Mapped[list["Route"]] = relationship(back_populates="mission", cascade="all, delete-orphan")
    logs: Mapped[list["MissionLog"]] = relationship(back_populates="mission", cascade="all, delete-orphan")


class Route(Base):
    __tablename__ = "routes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mission_id: Mapped[int | None] = mapped_column(ForeignKey("missions.id"), index=True)
    plan_id: Mapped[str] = mapped_column(String(40), index=True)
    profile: Mapped[str] = mapped_column(String(40))
    distance_m: Mapped[float] = mapped_column(Float)
    energy_wh: Mapped[float | None] = mapped_column(Float)
    duration_h: Mapped[float | None] = mapped_column(Float)
    dem_source: Mapped[str] = mapped_column(String(60))
    geometry: Mapped[dict] = mapped_column(JSON)                # GeoJSON LineString (lon, lat, elev)
    metrics: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    mission: Mapped[Mission | None] = relationship(back_populates="routes")
    segments: Mapped[list["RouteSegment"]] = relationship(back_populates="route", cascade="all, delete-orphan")


class RouteSegment(Base):
    """Contiguous stretch of a route with one hazard class and one data-quality class."""
    __tablename__ = "route_segments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    start_m: Mapped[float] = mapped_column(Float)
    end_m: Mapped[float] = mapped_column(Float)
    hazard: Mapped[str] = mapped_column(String(40))
    quality: Mapped[str] = mapped_column(String(40))
    route: Mapped[Route] = relationship(back_populates="segments")


class HazardGeometry(Base):
    """Hazard zones. `basis` records whether a zone is inferred from a DEM or injected by a simulation."""
    __tablename__ = "hazard_geometries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mission_id: Mapped[int | None] = mapped_column(ForeignKey("missions.id"), index=True)
    basis: Mapped[str] = mapped_column(String(40))             # inferred | simulated
    hazard: Mapped[str] = mapped_column(String(40))
    west: Mapped[float] = mapped_column(Float)
    south: Mapped[float] = mapped_column(Float)
    east: Mapped[float] = mapped_column(Float)
    north: Mapped[float] = mapped_column(Float)
    detail: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MissionLog(Base):
    __tablename__ = "mission_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mission_id: Mapped[int] = mapped_column(ForeignKey("missions.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    mission: Mapped[Mission] = relationship(back_populates="logs")


class CachedResource(Base):
    __tablename__ = "cached_resources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(255), unique=True)
    kind: Mapped[str] = mapped_column(String(60))
    source_url: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
