from fastapi import FastAPI

from app.demo_data import CURRENT_PLAN, DATA_LABEL, TASKS, WORKERS
from app.models import DemoOptimizeResponse, ForecastResponse, ScheduleInput
from app.services.heat_risk import build_windows
from app.services.scheduler import find_heat_conflicts, schedule
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
    weather = get_forecast(demo=True)  # always the synthetic fixture: reproducible demo
    windows = build_windows(weather.hours)
    result = schedule(
        ScheduleInput(
            workers=WORKERS, tasks=TASKS, heat_windows=windows, current_plan=CURRENT_PLAN
        )
    )
    return DemoOptimizeResponse(
        data_label=DATA_LABEL,
        weather_source=weather.source,
        heat_windows=windows,
        current_plan=CURRENT_PLAN,
        current_plan_conflicts=find_heat_conflicts(CURRENT_PLAN, TASKS, windows),
        result=result,
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
