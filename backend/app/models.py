from datetime import datetime
from enum import Enum
from typing import Literal

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


# --- Scheduling (T2). All times are "HH:MM" on hourly boundaries. ---


class Environment(str, Enum):
    OUTDOOR = "OUTDOOR"
    PARTIAL = "PARTIAL"
    INDOOR = "INDOOR"


class Intensity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Worker(BaseModel):
    id: str
    name: str
    skills: list[str]
    available_from: str
    available_to: str


class Task(BaseModel):
    id: str
    name: str
    duration_hours: int
    required_skill: str
    required_workers: int = 1
    environment: Environment
    intensity: Intensity
    dependencies: list[str] = []  # ids of tasks that must finish first
    mandatory_deadline: str | None = None  # task must end by this time


class ScheduledTask(BaseModel):
    """One task assigned to one worker. A task needing N workers yields N entries."""

    task_id: str
    task_name: str
    worker_id: str
    worker_name: str
    start: str
    end: str


class ScheduleInput(BaseModel):
    workers: list[Worker]
    tasks: list[Task]
    heat_windows: list[HeatRiskWindow]  # produced by the T1 Heat Risk Engine
    current_plan: list[ScheduledTask] = []


class Change(BaseModel):
    task_id: str
    task_name: str
    old_start: str
    old_end: str
    new_start: str
    new_end: str
    old_worker_id: str
    new_worker_id: str
    worker_changed: bool


class ScheduleResult(BaseModel):
    status: str  # "FEASIBLE" | "INFEASIBLE" | "UNKNOWN"
    solver: str
    schedule: list[ScheduledTask]
    changes: list[Change]
    violations: list[str]
    message: str | None = None


class HeatConflict(BaseModel):
    task_id: str
    task_name: str
    start: str
    end: str
    window_from: str
    window_to: str
    risk: Risk


class ForecastResponse(BaseModel):
    location: str
    source: str
    fallback_reason: str | None = None
    disclaimer: str
    hourly: list[WeatherHour]
    risk_windows: list[HeatRiskWindow]


# --- Independent validation (T3) ---


class ValidationViolation(BaseModel):
    constraint: str  # "H1".."H8", or "STRUCTURE" for unusable candidate data
    code: str
    message: str
    task_id: str | None = None
    worker_id: str | None = None


class ValidationResult(BaseModel):
    valid: bool
    violations: list[ValidationViolation]
    hard_constraints_checked: list[str]


class ValidateRequest(BaseModel):
    candidate_schedule: list[ScheduledTask]
    workers: list[Worker]
    tasks: list[Task]
    heat_windows: list[HeatRiskWindow]


# --- Trusted optimization flow (T4). The backend owns the whole operational context. ---


class OptimizeRequest(BaseModel):
    """Deliberately tiny: it only names a backend-owned scenario.

    Any other field (workers, tasks, current_plan, heat_windows, constraints, status...) is
    rejected (422) instead of being silently ignored or trusted.
    """

    model_config = ConfigDict(extra="forbid")

    scenario: Literal["baseline"]


class RiskContext(BaseModel):
    source: str  # "fixture" (synthetic demo) | "open_meteo"
    description: str
    windows: list[HeatRiskWindow]


class WorkerStatus(BaseModel):
    """Backend-owned SAFE worker metadata for presentation: id, display name, skills and current
    availability. `available` is False when the worker cannot be assigned. Availability windows
    and other scheduling constraints are deliberately not exposed."""

    id: str
    name: str
    skills: list[str]
    available: bool


class OptimizeResponse(BaseModel):
    scenario: str
    data_label: str
    risk: RiskContext
    workers: list[WorkerStatus]
    current_plan: list[ScheduledTask]
    current_plan_conflicts: list[HeatConflict]
    current_plan_validation: ValidationResult
    # "FEASIBLE" | "INFEASIBLE" | "UNKNOWN" (solver) | "VALIDATION_FAILED" (candidate rejected)
    status: str
    solver: str
    validated: bool  # True only if a candidate exists AND the independent validator accepted it
    schedule: list[ScheduledTask]  # empty unless validated
    changes: list[Change]
    validation: ValidationResult | None = None  # None when the solver produced no candidate
    message: str | None = None


# --- Dynamic replanning (T6). The client names a supported event; the backend applies it. ---


class WorkerUnavailableEvent(BaseModel):
    """Synthetic operational event: the operator marks a worker unavailable. No reason is
    modelled or stored. `worker_id` is validated at runtime against the backend-owned scenario
    (unknown ids -> 422), so there is no duplicated allowlist."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["worker_unavailable"]
    worker_id: str


class ReplanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: Literal["baseline"]
    event: WorkerUnavailableEvent


class AppliedEvent(BaseModel):
    type: str
    worker_id: str
    worker_name: str
    description: str


class ReplanResponse(OptimizeResponse):
    """Same shape as OptimizeResponse, evaluated under the UPDATED context:
    `current_plan` is the previously validated plan, `current_plan_validation` is that plan
    re-validated under the updated context, and `schedule`/`validation` are the replan."""

    event: AppliedEvent


class DemoOptimizeResponse(BaseModel):
    data_label: str
    weather_source: str
    heat_windows: list[HeatRiskWindow]
    current_plan: list[ScheduledTask]
    current_plan_conflicts: list[HeatConflict]
    result: ScheduleResult
