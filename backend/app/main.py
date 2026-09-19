from fastapi import FastAPI, HTTPException

from app.demo_data import SITE
from app.models import (
    AssignmentRejectionRequest,
    AssignmentRejectionResponse,
    DemoOptimizeResponse,
    ForecastResponse,
    OptimizeRequest,
    OptimizeResponse,
    ReplanRequest,
    ReplanResponse,
    ScheduleInput,
    SiteView,
    ValidateRequest,
    ValidationResult,
    WildfireOptimizeRequest,
    WildfireOptimizeResponse,
    WorkerStatus,
)
from app.services.heat_risk import build_windows
from app.services.optimization import run_optimization
from app.services.rejection import (
    AssignmentNotInCandidateError,
    UnknownTaskError,
    run_assignment_rejection,
)
from app.services.replan import run_replan
from app.services.scenario import (
    UnknownWorkerError,
    load_baseline_context,
    load_scenario,
    site_view,
    worker_roster,
)
from app.services.scheduler import find_heat_conflicts, schedule
from app.services.validator import validate_schedule
from app.services.wildfire import run_wildfire_optimization
from app.services.weather import get_forecast

DISCLAIMER = (
    "Prototype Heat Risk Engine: operational demo thresholds only. "
    "Not a certified WBGT, not an occupational-risk assessment, not medical or legal advice."
)

app = FastAPI()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/demo/optimize", response_model=DemoOptimizeResponse)
def demo_optimize() -> DemoOptimizeResponse:
    """Demo flow: fixture weather -> T1 risk windows -> constraints -> OR-Tools alternative plan."""
    ctx = load_baseline_context()
    result = schedule(
        ScheduleInput(
            workers=ctx.workers, tasks=ctx.tasks,
            heat_windows=ctx.risk.windows, current_plan=ctx.current_plan,
        )
    )
    return DemoOptimizeResponse(
        data_label=ctx.data_label,
        weather_source=ctx.risk.source,
        heat_windows=ctx.risk.windows,
        current_plan=ctx.current_plan,
        current_plan_conflicts=find_heat_conflicts(ctx.current_plan, ctx.tasks, ctx.risk.windows),
        result=result,
    )


@app.get("/scenarios/{scenario}/site", response_model=SiteView)
def scenario_site(scenario: str) -> SiteView:
    """Safe Site/WorkZone metadata (name, location, zones, task->zone) for the UI."""
    try:
        return site_view(load_scenario(scenario))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown scenario {scenario!r}") from None


@app.get("/scenarios/{scenario}/workers", response_model=list[WorkerStatus])
def scenario_workers(scenario: str) -> list[WorkerStatus]:
    """Safe worker metadata (id, name, skills, availability) of a backend-owned scenario, so the
    UI can show the operational worker table before any optimization has run."""
    try:
        return worker_roster(load_scenario(scenario))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown scenario {scenario!r}") from None


@app.post("/optimize", response_model=OptimizeResponse)
def optimize(request: OptimizeRequest) -> OptimizeResponse:
    """Frontend-facing flow. The backend owns workers/tasks/plan/risk windows; the client only
    names a scenario. Solver output is independently validated before being exposed."""
    return run_optimization(load_scenario(request.scenario))


@app.post("/replan/assignment-rejection", response_model=AssignmentRejectionResponse)
def replan_assignment_rejection(request: AssignmentRejectionRequest) -> AssignmentRejectionResponse:
    """A worker declined ONE proposed assignment ("NOT"). The backend forbids only that
    worker+task pair (H10), replans with OR-Tools and independently validates the result.
    Unknown worker/task, or a pair that is not in the proposed plan, is rejected (422)."""
    try:
        return run_assignment_rejection(request.scenario, request.rejected_assignment)
    except (UnknownWorkerError, UnknownTaskError, AssignmentNotInCandidateError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/wildfire/optimize", response_model=WildfireOptimizeResponse)
def wildfire_optimize(request: WildfireOptimizeRequest) -> WildfireOptimizeResponse:
    """Norrsken flow: the BACKEND queries Deepfire for the Site's location, applies the configured
    wildfire operational rule (H9) and optimizes + independently validates under it. The client
    only names the scenario; it can neither supply nor override the signal or the rule."""
    return run_wildfire_optimization(request.scenario)


@app.post("/replan", response_model=ReplanResponse)
def replan(request: ReplanRequest) -> ReplanResponse:
    """Apply a supported synthetic operational event (worker_unavailable) to the backend-owned
    baseline context, then replan with OR-Tools and independently validate the result."""
    try:
        return run_replan(request.scenario, request.event)
    except UnknownWorkerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/validate", response_model=ValidationResult)
def validate(request: ValidateRequest) -> ValidationResult:
    """LOW-LEVEL validator endpoint for tests/tooling: validates against the context supplied
    in the request. It is NOT an authoritative trust boundary (the caller supplies heat_windows);
    the trusted flow is POST /optimize."""
    return validate_schedule(
        request.candidate_schedule, request.workers, request.tasks, request.heat_windows
    )


@app.get("/forecast", response_model=ForecastResponse)
def forecast(demo: bool = False) -> ForecastResponse:
    """Weather -> operational heat risk windows. `?demo=true` forces the synthetic fixture."""
    weather = get_forecast(SITE, demo=demo)  # coordinates come from the backend-owned Site
    return ForecastResponse(
        location=weather.location,
        source=weather.source,
        fallback_reason=weather.fallback_reason,
        disclaimer=DISCLAIMER,
        hourly=weather.hours,
        risk_windows=build_windows(weather.hours),
    )
