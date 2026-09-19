"""Assignment rejection: a worker declined ONE proposed assignment ("NOT") -> new trusted plan.

Semantics (fixed by the product): the worker cannot perform THIS task in THIS proposed assignment.
It does not mean the worker is unavailable for the day, unfit or unsafe, and it never relaxes a
hard constraint. The backend resolves everything from its own scenario data and computes the
candidate plan being rejected itself; the client only names the worker+task pair.
"""

from collections.abc import Callable
from dataclasses import replace

from app.models import (
    AppliedRejection,
    AssignmentRejectionResponse,
    OptimizeResponse,
    RejectedAssignment,
)
from app.services.optimization import run_optimization
from app.services.scenario import UnknownWorkerError, load_scenario
from app.services.scheduler import schedule


class UnknownTaskError(ValueError):
    """The rejection names a task that does not exist in the backend-owned scenario."""


class AssignmentNotInCandidateError(ValueError):
    """The worker+task pair is not part of the candidate plan being rejected."""


def run_assignment_rejection(
    scenario: str,
    rejected: RejectedAssignment,
    scheduler_fn: Callable = schedule,
) -> AssignmentRejectionResponse:
    base = load_scenario(scenario)
    workers = {w.id: w for w in base.workers}
    tasks = {t.id: t for t in base.tasks}
    if rejected.worker_id not in workers:
        raise UnknownWorkerError(f"Unknown worker {rejected.worker_id!r}")
    if rejected.task_id not in tasks:
        raise UnknownTaskError(f"Unknown task {rejected.task_id!r}")

    # The candidate plan being rejected = the validated baseline optimization, computed here.
    candidate = run_optimization(base)
    if candidate.status != "FEASIBLE" or not candidate.validated:
        raise RuntimeError(f"Baseline candidate is not validated (status={candidate.status})")
    proposed = next(
        (p for p in candidate.schedule if p.worker_id == rejected.worker_id and p.task_id == rejected.task_id),
        None,
    )
    if proposed is None:
        raise AssignmentNotInCandidateError(
            f"{workers[rejected.worker_id].name} is not assigned to {tasks[rejected.task_id].name} "
            f"in the proposed plan"
        )

    updated = replace(base, current_plan=list(candidate.schedule), rejected_assignments=[rejected])
    result = run_optimization(updated, scheduler_fn=scheduler_fn)

    return AssignmentRejectionResponse(
        **{name: getattr(result, name) for name in OptimizeResponse.model_fields},
        rejection=AppliedRejection(
            worker_id=proposed.worker_id, worker_name=proposed.worker_name,
            task_id=proposed.task_id, task_name=proposed.task_name,
            start=proposed.start, end=proposed.end,
            description=(
                f"{proposed.worker_name} declined {proposed.task_name} ({proposed.start}-{proposed.end}). "
                f"Only this worker+task pair is excluded from the new plan; the worker remains available "
                f"for other tasks and no reason is recorded."
            ),
        ),
    )
