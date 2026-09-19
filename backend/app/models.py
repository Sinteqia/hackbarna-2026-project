from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Risk(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


class WeatherHour(BaseModel):
    """One normalized hourly weather reading (local time, no timezone)."""

    time: datetime
    temperature_c: float
    relative_humidity_pct: float | None = None
    apparent_temperature_c: float | None = None


class Constraints(BaseModel):
    """Operational constraints derived from the risk level."""

    outdoor_high_intensity_allowed: bool


class HeatRiskWindow(BaseModel):
    """Consecutive hours sharing the same operational risk. `to` is exclusive."""

    model_config = ConfigDict(populate_by_name=True)

    from_time: str = Field(alias="from")  # "HH:MM"
    to_time: str = Field(alias="to")  # "HH:MM", end of the last hour
    risk: Risk
    constraints: Constraints


class WeatherForecast(BaseModel):
    location: str
    source: str  # "open_meteo" | "fixture"
    fallback_reason: str | None = None  # set when fixture used after a live failure
    hours: list[WeatherHour]


class ForecastResponse(BaseModel):
    location: str
    source: str
    fallback_reason: str | None = None
    disclaimer: str
    hourly: list[WeatherHour]
    risk_windows: list[HeatRiskWindow]
