"""Dynamic replanning: apply a supported operational event to the backend-owned context.

Flow: baseline optimization (validated) -> apply event -> re-validate the previous plan under the
UPDATED context -> OR-Tools replan -> independent validation. All of it reuses run_optimization;
nothing is supplied by the client except the event identity.
"""

from collections.abc import Callable

from app.models import AppliedEvent, OptimizeResponse, ReplanResponse, WorkerUnavailableEvent
from app.services.optimization import run_optimization
from app.services.scenario import UnknownWorkerError, apply_worker_unavailable, load_scenario
from app.services.scheduler import schedule


def run_replan(
    scenario: str,
    event: WorkerUnavailableEvent,
    scheduler_fn: Callable = schedule,
) -> ReplanResponse:
    base = load_scenario(scenario)
    if event.worker_id not in {w.id for w in base.workers}:  # runtime check vs the owned scenario
        raise UnknownWorkerError(f"Unknown worker {event.worker_id!r}")

    baseline = run_optimization(base)
    if baseline.status != "FEASIBLE" or not baseline.validated:
        # Internal invariant: the demo baseline must be a validated plan to be replanned.
        raise RuntimeError(f"Baseline plan is not validated (status={baseline.status})")

    updated = apply_worker_unavailable(base, event.worker_id, baseline.schedule)
    # current_plan == previously validated plan, so run_optimization re-validates it under the
    # updated context (current_plan_validation) and diffs the replan against it (changes).
    result = run_optimization(updated, scheduler_fn=scheduler_fn)

    worker = next(w for w in base.workers if w.id == event.worker_id)
    return ReplanResponse(
        **{name: getattr(result, name) for name in OptimizeResponse.model_fields},
        event=AppliedEvent(
            type=event.type,
            worker_id=worker.id,
            worker_name=worker.name,
            description=f"Synthetic operational event: {worker.name} cannot be assigned work",
        ),
    )
