"""Backend-owned operational context: the single composition point for POST /optimize.

Clients only name a scenario; workers, tasks, current plan and risk windows come from here.
Risk windows are produced by the T1 engine (`build_windows`) - no thresholds are duplicated.
"""

from collections.abc import Callable
from dataclasses import dataclass

from app.demo_data import CURRENT_PLAN, DATA_LABEL, TASKS, WORKERS
from app.models import RiskContext, ScheduledTask, Task, Worker
from app.services.heat_risk import build_windows
from app.services.weather import get_forecast


@dataclass(frozen=True)
class OperationalContext:
    scenario: str
    data_label: str
    workers: list[Worker]
    tasks: list[Task]
    current_plan: list[ScheduledTask]
    risk: RiskContext


def load_baseline_context() -> OperationalContext:
    # Reproducible demo: always the SYNTHETIC fixture weather (never presented as live data).
    # Live Open-Meteo evidence is GET /forecast.
    weather = get_forecast(demo=True)
    return OperationalContext(
        scenario="baseline",
        data_label=DATA_LABEL,
        workers=list(WORKERS),
        tasks=list(TASKS),
        current_plan=list(CURRENT_PLAN),
        risk=RiskContext(
            source=weather.source,
            description=(
                "SYNTHETIC DEMO DATA fixture (not a live forecast). "
                "Prototype operational thresholds, not a certified WBGT."
            ),
            windows=build_windows(weather.hours),
        ),
    )


SCENARIOS: dict[str, Callable[[], OperationalContext]] = {"baseline": load_baseline_context}


def load_scenario(name: str) -> OperationalContext:
    return SCENARIOS[name]()
