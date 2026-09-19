"""Assignment rejection: a worker declined ONE proposed assignment ("NOT") -> new trusted plan.

Semantics (fixed by the product): the worker cannot perform THIS task in THIS proposed assignment.
It does not mean the worker is unavailable for the day, unfit or unsafe, and it never relaxes a
hard constraint. The backend resolves everything from its own scenario data; the client only names
the worker+task pair(s).

Cumulative rejections: rejections are ORDERED. The server replays them from the baseline candidate:
round k must name a pair that exists in the candidate produced by rounds 1..k-1 (each replan is
solved by OR-Tools and independently validated). Rejected pairs accumulate as H10 constraints.
Nothing about earlier rounds is trusted from the client except the pairs themselves.
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
    """The worker+task pair is not part of the candidate plan being rejected in that round."""


class DuplicateRejectionError(ValueError):
    """The same worker+task pair appears more than once in the rejection history."""


class NoCandidateError(ValueError):
    """An earlier round left no validated plan, so a later rejection has no candidate to apply to."""


def run_assignment_rejection(
    scenario: str,
    rejected: RejectedAssignment | list[RejectedAssignment],
    scheduler_fn: Callable = schedule,
) -> AssignmentRejectionResponse:
    history = [rejected] if isinstance(rejected, RejectedAssignment) else list(rejected)
    base = load_scenario(scenario)
    workers = {w.id: w for w in base.workers}
    tasks = {t.id: t for t in base.tasks}

    # Cheap checks first, before any solving: ids exist and no pair is repeated.
    seen: set[tuple[str, str]] = set()
    for r in history:
        if r.worker_id not in workers:
            raise UnknownWorkerError(f"Unknown worker {r.worker_id!r}")
        if r.task_id not in tasks:
            raise UnknownTaskError(f"Unknown task {r.task_id!r}")
        if (r.worker_id, r.task_id) in seen:
            raise DuplicateRejectionError(
                f"{workers[r.worker_id].name} + {tasks[r.task_id].name} appears more than once in the rejection history"
            )
        seen.add((r.worker_id, r.task_id))

    # Round 0 candidate = the validated baseline optimization, computed here (never client-supplied).
    candidate = run_optimization(base)
    if candidate.status != "FEASIBLE" or not candidate.validated:
        raise RuntimeError(f"Baseline candidate is not validated (status={candidate.status})")
    candidate_plan = candidate.schedule

    applied: list[AppliedRejection] = []
    result: OptimizeResponse | None = None
    for i, rej in enumerate(history):
        proposed = next(
            (p for p in candidate_plan if p.worker_id == rej.worker_id and p.task_id == rej.task_id), None
        )
        if proposed is None:
            where = "in the plan produced by the previous rejection(s)" if i else "in the proposed plan"
            raise AssignmentNotInCandidateError(
                f"{workers[rej.worker_id].name} is not assigned to {tasks[rej.task_id].name} {where}"
            )
        # H10 accumulates: every pair rejected so far, this round included.
        updated = replace(base, current_plan=list(candidate_plan), rejected_assignments=list(history[: i + 1]))
        result = run_optimization(updated, scheduler_fn=scheduler_fn)
        applied.append(
            AppliedRejection(
                worker_id=proposed.worker_id, worker_name=proposed.worker_name,
                task_id=proposed.task_id, task_name=proposed.task_name,
                start=proposed.start, end=proposed.end,
                description=(
                    f"{proposed.worker_name} declined {proposed.task_name} ({proposed.start}-{proposed.end}). "
                    f"Only this worker+task pair is excluded from the new plan; the worker remains available "
                    f"for other tasks and no reason is recorded."
                ),
            )
        )
        if i < len(history) - 1:  # a later round needs a validated candidate from this one
            if result.status != "FEASIBLE" or not result.validated:
                raise NoCandidateError(
                    f"Rejection {i + 1} left no validated plan ({result.status}); later rejections have no candidate"
                )
            candidate_plan = result.schedule

    assert result is not None  # history is never empty (validated by the request model)
    return AssignmentRejectionResponse(
        **{name: getattr(result, name) for name in OptimizeResponse.model_fields},
        rejection=applied[-1],
        rejection_history=applied,
    )
