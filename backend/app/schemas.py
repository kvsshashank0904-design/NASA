from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Point(BaseModel):
    lon: float = Field(ge=-360, le=360, description="East-positive longitude, degrees")
    lat: float = Field(ge=-90, le=90, description="Planetocentric latitude, degrees")


class Weights(BaseModel):
    distance: float | None = Field(default=None, ge=0, le=20)
    slope: float | None = Field(default=None, ge=0, le=20)
    roughness: float | None = Field(default=None, ge=0, le=20)
    hazard: float | None = Field(default=None, ge=0, le=20)
    energy: float | None = Field(default=None, ge=0, le=20)


class VehicleIn(BaseModel):
    mass_kg: float = Field(default=3000, gt=0, le=50000)
    rolling_resistance: float = Field(default=0.15, gt=0, le=1)
    drivetrain_efficiency: float = Field(default=0.7, gt=0, le=1)
    speed_kmh: float = Field(default=8, gt=0, le=60)
    hotel_power_w: float = Field(default=600, ge=0, le=50000)
    battery_wh: float | None = Field(default=None, gt=0, le=5_000_000)


class RoutePlanRequest(BaseModel):
    start: Point
    goal: Point
    weights: Weights | None = None
    max_slope_deg: float = Field(default=25, gt=0, le=45)
    caution_deg: float = Field(default=10, gt=0, le=45)
    high_deg: float = Field(default=20, gt=0, le=45)
    safety_margin: float = Field(default=0.2, ge=0, le=0.8)
    unknown_penalty: float = Field(default=1.0, ge=0, le=20)
    vehicle: VehicleIn | None = None
    mode: Literal["rover", "eva"] = "rover"
    endurance_h: float = Field(default=8, gt=0, le=24, description="EVA life-support limit, hours (mode = eva)")
    include_return: bool = True
    mission_id: int | None = None

    @model_validator(mode="after")
    def _order(self):
        if not (self.caution_deg <= self.high_deg <= self.max_slope_deg):
            raise ValueError("thresholds must satisfy caution_deg <= high_deg <= max_slope_deg")
        return self


class HazardRequest(BaseModel):
    center: Point | None = None
    radius_km: float | None = Field(default=None, gt=0, le=250)
    bbox: list[float] | None = Field(default=None, min_length=4, max_length=4, description="[west, south, east, north]")
    caution_deg: float = Field(default=10, gt=0, le=45)
    high_deg: float = Field(default=20, gt=0, le=45)
    max_slope_deg: float = Field(default=30, gt=0, le=60)

    @model_validator(mode="after")
    def _one(self):
        if self.bbox is None and (self.center is None or self.radius_km is None):
            raise ValueError("provide either bbox or center + radius_km")
        return self


class MissionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    start: Point
    goal: Point | None = None
    objectives: list[str] = Field(default_factory=list, max_length=30)
    target_ids: list[str] = Field(default_factory=list, max_length=30)
    constraints: dict | None = None


class MissionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    status: Literal["planned", "active", "completed", "aborted"] | None = None
    goal: Point | None = None
    objectives: list[str] | None = None
    target_ids: list[str] | None = None
    selected_route_id: int | None = None
    return_route_id: int | None = None


class MissionLogIn(BaseModel):
    kind: str = Field(default="note", max_length=40)
    message: str = Field(min_length=1, max_length=4000)
    data: dict | None = None


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=40)
    context: dict | None = None


class SimulationRequest(BaseModel):
    plan_id: str | None = None
    profile: str | None = None
    route: list[list[float]] | None = Field(default=None, description="[[lon, lat, elev_m], ...] when no plan_id")
    return_route: list[list[float]] | None = None
    scenario: str = "nominal"
    vehicle: VehicleIn | None = None
    battery_wh: float | None = Field(default=None, gt=0, le=5_000_000)
    dwell_min: float = Field(default=30, ge=0, le=600)
    safety_margin: float = Field(default=0.2, ge=0, le=0.8)
    objectives: list[str] = Field(default_factory=list)
    mission_id: int | None = None

    @model_validator(mode="after")
    def _src(self):
        if not self.plan_id and not self.route:
            raise ValueError("provide plan_id or route")
        return self
