from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class Company(BaseModel):
    id: str
    name: str


class Site(BaseModel):
    """A construction site: the operational location that environmental data belongs to."""

    id: str
    name: str
    location_name: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class WorkZone(BaseModel):
    """An area of a site. It owns the environmental classification of the work done in it."""

    id: str
    site_id: str
    name: str
    environment: Environment


class Task(BaseModel):
    id: str
    name: str
    duration_hours: int
    required_skill: str
    required_workers: int = 1
    work_zone_id: str  # the WorkZone the task is performed in
    environment: Environment  # DERIVED from the WorkZone (see demo_data); H5 reads this value
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


class WildfireRestriction(BaseModel):
    """CONFIGURED operational rule derived from an applicable environmental signal (Deepfire).
    It is an operational rule of this prototype, not a legal prohibition and not a Deepfire
    statement. `to` is exclusive."""

    model_config = ConfigDict(populate_by_name=True)

    from_time: str = Field(alias="from")  # "HH:MM"
    to_time: str = Field(alias="to")
    outdoor_work_allowed: bool = False
    source: str = "deepfire"
    rule: str = ""  # human-readable description of the configured rule


class RejectedAssignment(BaseModel):
    """ONE specific proposed assignment a worker declined: this worker must not perform this task
    in this replanning. It is NOT unavailability for the day and says nothing about the worker
    (no reason is recorded)."""

    model_config = ConfigDict(extra="forbid")

    worker_id: str
    task_id: str


class ScheduleInput(BaseModel):
    workers: list[Worker]
    tasks: list[Task]
    heat_windows: list[HeatRiskWindow]  # produced by the T1 Heat Risk Engine
    wildfire_restrictions: list[WildfireRestriction] = []  # H9; empty = none applied
    rejected_assignments: list[RejectedAssignment] = []  # H10; empty = none
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


class ZoneView(BaseModel):
    id: str
    name: str
    environment: Environment


class SiteView(BaseModel):
    """SAFE presentation metadata of the site: identity, location, zones and which zone each task
    belongs to. No scheduling constraints."""

    company_name: str
    id: str
    name: str
    location_name: str
    latitude: float
    longitude: float
    zones: list[ZoneView]
    task_zones: dict[str, str]  # task_id -> work_zone_id


class RiskContext(BaseModel):
    site_id: str  # the site whose location these risk windows belong to
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
    site: SiteView
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


# --- Assignment rejection ("NOT" from a worker) -> trusted replanning ---


MAX_REJECTION_HISTORY = 10  # bounds the server-side replay (one solve per round)


class AssignmentRejectionRequest(BaseModel):
    """The client names the rejected assignment(s). No schedule, constraints or worker/task
    metadata are accepted: everything is resolved from backend-owned data.

    Exactly one of:
      * `rejected_assignment`: a single rejection against the baseline candidate (original form);
      * `rejection_history`: ORDERED cumulative rejections. The server replays them from the
        baseline: each pair must exist in the candidate produced by the previous rounds.
    """

    model_config = ConfigDict(extra="forbid")

    scenario: Literal["baseline"]
    rejected_assignment: RejectedAssignment | None = None
    rejection_history: list[RejectedAssignment] | None = Field(
        default=None, min_length=1, max_length=MAX_REJECTION_HISTORY
    )

    @model_validator(mode="after")
    def _exactly_one_form(self) -> "AssignmentRejectionRequest":
        if (self.rejected_assignment is None) == (self.rejection_history is None):
            raise ValueError("provide exactly one of rejected_assignment or rejection_history")
        return self

    def rejections(self) -> list[RejectedAssignment]:
        return [self.rejected_assignment] if self.rejected_assignment else list(self.rejection_history or [])


class AppliedRejection(BaseModel):
    worker_id: str
    worker_name: str
    task_id: str
    task_name: str
    start: str  # where the rejected assignment sat in the candidate plan
    end: str
    description: str


class AssignmentRejectionResponse(OptimizeResponse):
    """OptimizeResponse for the replanning that forbids the rejected worker+task pair.
    `current_plan` is the candidate that was rejected; `current_plan_validation` re-validates it
    (it violates H10 by construction); `schedule`/`validation` are the new plan.
    `rejection` is the LAST rejection; `rejection_history` lists every round applied, in order."""

    rejection: AppliedRejection
    rejection_history: list[AppliedRejection]


# --- Norrsken / Deepfire wildfire signal (configured operational rule, not a safety statement) ---


class HotspotEvidence(BaseModel):
    """Public satellite detection metadata. A hotspot is a candidate fire signal, NOT a confirmed fire."""

    id: str
    distance_km: float
    observed_at: str
    confidence: str
    source: str


class WildfireAssessment(BaseModel):
    # APPLICABLE_SIGNAL | NO_APPLICABLE_SIGNAL | STALE_SIGNAL | UNAVAILABLE
    # NO_APPLICABLE_SIGNAL, STALE_SIGNAL and UNAVAILABLE never mean "low risk" or "safe".
    status: str
    site_id: str
    data_source: str
    queried_at: str
    # CONFIGURED DEMO OPERATIONAL RULE PARAMETERS: not Deepfire recommendations, legal thresholds,
    # wildfire safety distances or official exclusion zones (see `parameters_note`).
    radius_km: float  # configured applicability radius around the site
    fresh_hours: int  # configured observation window
    parameters_note: str
    hotspots_in_radius: int
    nearest_km: float | None = None
    latest_observed_at: str | None = None
    evidence: list[HotspotEvidence] = []
    affected_zone_ids: list[str] = []
    affected_task_ids: list[str] = []
    restriction: WildfireRestriction | None = None
    rule_description: str
    disclaimer: str
    error: str | None = None  # error TYPE only; never credentials or tokens


class WildfireOptimizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: Literal["baseline"]


class WildfireOptimizeResponse(OptimizeResponse):
    """OptimizeResponse evaluated under the wildfire assessment. status may also be
    SIGNAL_UNAVAILABLE / SIGNAL_STALE: no plan is presented as wildfire-cleared in those cases."""

    wildfire: WildfireAssessment


class DemoOptimizeResponse(BaseModel):
    data_label: str
    weather_source: str
    heat_windows: list[HeatRiskWindow]
    current_plan: list[ScheduledTask]
    current_plan_conflicts: list[HeatConflict]
    result: ScheduleResult
