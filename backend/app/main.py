from fastapi import FastAPI

from app.models import (
    DemoOptimizeResponse,
    ForecastResponse,
    OptimizeRequest,
    OptimizeResponse,
    ScheduleInput,
    ValidateRequest,
    ValidationResult,
)
from app.services.heat_risk import build_windows
from app.services.optimization import run_optimization
from app.services.scenario import load_baseline_context, load_scenario
from app.services.scheduler import find_heat_conflicts, schedule
from app.services.validator import validate_schedule
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


@app.post("/optimize", response_model=OptimizeResponse)
def optimize(request: OptimizeRequest) -> OptimizeResponse:
    """Frontend-facing flow. The backend owns workers/tasks/plan/risk windows; the client only
    names a scenario. Solver output is independently validated before being exposed."""
    return run_optimization(load_scenario(request.scenario))


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
    weather = get_forecast(demo=demo)
    return ForecastResponse(
        location=weather.location,
        source=weather.source,
        fallback_reason=weather.fallback_reason,
        disclaimer=DISCLAIMER,
        hourly=weather.hours,
        risk_windows=build_windows(weather.hours),
    )
