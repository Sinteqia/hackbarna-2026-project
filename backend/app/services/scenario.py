"""Backend-owned operational context: the single composition point for POST /optimize.

Clients only name a scenario; workers, tasks, current plan and risk windows come from here.
Risk windows are produced by the T1 engine (`build_windows`) - no thresholds are duplicated.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace

from app.demo_data import COMPANY, CURRENT_PLAN, DATA_LABEL, SITE, TASKS, WORKERS, ZONES
from app.models import (
    Company,
    RiskContext,
    ScheduledTask,
    Site,
    SiteView,
    Task,
    WildfireRestriction,
    Worker,
    WorkerStatus,
    WorkZone,
    ZoneView,
)
from app.services.heat_risk import build_windows
from app.services.weather import get_forecast


@dataclass(frozen=True)
class OperationalContext:
    scenario: str
    data_label: str
    company: Company
    site: Site
    zones: list[WorkZone]
    workers: list[Worker]
    tasks: list[Task]
    current_plan: list[ScheduledTask]
    risk: RiskContext  # environmental risk windows for `site`
    # None = no wildfire assessment took part; a list (maybe empty) = it did (H9 is then checked).
    wildfire_restrictions: list[WildfireRestriction] | None = None


def load_baseline_context() -> OperationalContext:
    # Reproducible demo: always the SYNTHETIC fixture weather (never presented as live data).
    # The forecast is requested for the Site's own coordinates; live Open-Meteo evidence for the
    # same site is GET /forecast.
    weather = get_forecast(SITE, demo=True)
    return OperationalContext(
        scenario="baseline",
        data_label=DATA_LABEL,
        company=COMPANY,
        site=SITE,
        zones=list(ZONES),
        workers=list(WORKERS),
        tasks=list(TASKS),
        current_plan=list(CURRENT_PLAN),
        risk=RiskContext(
            site_id=SITE.id,
            source=weather.source,
            description=(
                f"SYNTHETIC DEMO DATA fixture standing in for {SITE.name} (not a live forecast). "
                "Prototype operational thresholds, not a certified WBGT."
            ),
            windows=build_windows(weather.hours),
        ),
    )


def site_view(context: OperationalContext) -> SiteView:
    """Safe presentation metadata: site identity/location, zones, and each task's zone."""
    return SiteView(
        company_name=context.company.name,
        id=context.site.id,
        name=context.site.name,
        location_name=context.site.location_name,
        latitude=context.site.latitude,
        longitude=context.site.longitude,
        zones=[ZoneView(id=z.id, name=z.name, environment=z.environment) for z in context.zones],
        task_zones={t.id: t.work_zone_id for t in context.tasks},
    )


# "Unavailable" = empty availability window, so the existing H1 mechanism (solver and independent
# validator) applies unchanged. No reason is stored.
UNAVAILABLE_WINDOW = ("00:00", "00:00")


def worker_roster(context: OperationalContext) -> list[WorkerStatus]:
    """Safe presentation metadata for the workers of a scenario (single source for all responses)."""
    return [
        WorkerStatus(id=w.id, name=w.name, skills=list(w.skills), available=is_worker_available(w))
        for w in context.workers
    ]


class UnknownWorkerError(ValueError):
    """The event names a worker that does not exist in the backend-owned scenario."""


def is_worker_available(worker: Worker) -> bool:
    return worker.available_from < worker.available_to  # empty window == unavailable


def apply_worker_unavailable(
    context: OperationalContext, worker_id: str, current_plan: list[ScheduledTask]
) -> OperationalContext:
    """Return a NEW context in which `worker_id` cannot be assigned work; the input is untouched.
    `current_plan` becomes the plan in force (the previously validated one)."""
    if worker_id not in {w.id for w in context.workers}:
        raise UnknownWorkerError(f"Unknown worker {worker_id!r}")
    start, end = UNAVAILABLE_WINDOW
    workers = [
        w.model_copy(update={"available_from": start, "available_to": end}) if w.id == worker_id else w
        for w in context.workers
    ]
    return replace(context, workers=workers, current_plan=list(current_plan))


SCENARIOS: dict[str, Callable[[], OperationalContext]] = {"baseline": load_baseline_context}


def load_scenario(name: str) -> OperationalContext:
    return SCENARIOS[name]()
