"""Independent deterministic schedule validator (pure Python).

INDEPENDENCE RULE: this module must not import OR-Tools or the scheduler, and must not
trust any solver status. It recomputes H1-H8 from the candidate data alone. It only shares
the plain data models (workers, tasks, heat windows, scheduled tasks) with the rest of the app.

Intervals are half-open [start, end): a task ending at 12:00 does not overlap one starting at 12:00.
The validator checks the operational constraint (outdoor_high_intensity_allowed) it is given;
it does not compute heat risk.
"""

import re
from typing import NamedTuple

from app.models import (
    Environment,
    HeatRiskWindow,
    Intensity,
    ScheduledTask,
    Task,
    ValidationResult,
    ValidationViolation,
    Worker,
)

HARD_CONSTRAINTS = ["H1", "H2", "H3", "H4", "H5", "H6", "H7", "H8"]
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")


def _minutes(value: str) -> int | None:
    """'HH:MM' -> minutes since midnight ('24:00' allowed); None if unusable."""
    if not _TIME_RE.match(value):
        return None
    hours, minutes = (int(x) for x in value.split(":"))
    total = hours * 60 + minutes
    if minutes > 59 or total > 24 * 60:
        return None
    return total


class _Assignment(NamedTuple):
    task_id: str
    worker_id: str
    start: int
    end: int


def validate_schedule(
    candidate_schedule: list[ScheduledTask],
    workers: list[Worker],
    tasks: list[Task],
    heat_windows: list[HeatRiskWindow],
) -> ValidationResult:
    violations: list[ValidationViolation] = []

    def add(constraint: str, code: str, message: str, task_id=None, worker_id=None) -> None:
        violations.append(
            ValidationViolation(
                constraint=constraint, code=code, message=message, task_id=task_id, worker_id=worker_id
            )
        )

    workers_by_id = {w.id: w for w in workers}
    tasks_by_id = {t.id: t for t in tasks}

    # ---- structural defence: keep only assignments that can be checked safely ----
    for t in tasks:
        for dep in t.dependencies:
            if dep not in tasks_by_id:
                add("STRUCTURE", "UNKNOWN_DEPENDENCY", f"{t.id} depends on unknown task {dep}", task_id=t.id)

    usable: list[_Assignment] = []
    seen: set[tuple[str, str]] = set()
    tasks_with_entries: set[str] = set()
    for item in candidate_schedule:
        if item.task_id not in tasks_by_id:
            add("STRUCTURE", "UNKNOWN_TASK", f"Unknown task_id {item.task_id!r}", task_id=item.task_id)
            continue
        tasks_with_entries.add(item.task_id)
        if item.worker_id not in workers_by_id:
            add("STRUCTURE", "UNKNOWN_WORKER", f"Unknown worker_id {item.worker_id!r}",
                task_id=item.task_id, worker_id=item.worker_id)
            continue
        start, end = _minutes(item.start), _minutes(item.end)
        if start is None or end is None:
            add("STRUCTURE", "UNPARSEABLE_TIME", f"Bad time in {item.task_id}: {item.start}-{item.end}",
                task_id=item.task_id, worker_id=item.worker_id)
            continue
        if end <= start:
            add("STRUCTURE", "INVALID_INTERVAL", f"{item.task_id} ends ({item.end}) not after start ({item.start})",
                task_id=item.task_id, worker_id=item.worker_id)
            continue
        if (item.task_id, item.worker_id) in seen:
            add("STRUCTURE", "DUPLICATE_ASSIGNMENT", f"{item.worker_id} assigned to {item.task_id} more than once",
                task_id=item.task_id, worker_id=item.worker_id)
            continue
        seen.add((item.task_id, item.worker_id))
        usable.append(_Assignment(item.task_id, item.worker_id, start, end))

    for t in tasks:
        if t.id not in tasks_with_entries:
            add("STRUCTURE", "MISSING_TASK", f"Task {t.id} has no assignment", task_id=t.id)

    by_task: dict[str, list[_Assignment]] = {}
    for a in usable:
        by_task.setdefault(a.task_id, []).append(a)

    # A multi-worker task must run at one common interval.
    for task_id, group in by_task.items():
        if len({(a.start, a.end) for a in group}) > 1:
            add("STRUCTURE", "TASK_INTERVAL_MISMATCH", f"Workers of {task_id} have different intervals", task_id=task_id)

    for a in usable:
        task, worker = tasks_by_id[a.task_id], workers_by_id[a.worker_id]

        # H1 worker availability: the whole assignment inside the worker's availability
        av_from, av_to = _minutes(worker.available_from), _minutes(worker.available_to)
        if av_from is None or av_to is None or a.start < av_from or a.end > av_to:
            when = f"{a.start // 60:02d}:{a.start % 60:02d}-{a.end // 60:02d}:{a.end % 60:02d}"
            if av_from is not None and av_to is not None and av_to <= av_from:  # empty availability
                message = f"{worker.name} is unavailable, but {task.name} is scheduled {when}"
            else:
                message = (
                    f"{worker.name} is available {worker.available_from}-{worker.available_to}, "
                    f"but {task.name} is scheduled {when}"
                )
            add("H1", "OUTSIDE_AVAILABILITY", message, task_id=a.task_id, worker_id=a.worker_id)

        # H2 skill match
        if task.required_skill not in worker.skills:
            add("H2", "MISSING_SKILL", f"{worker.name} lacks skill {task.required_skill} for {task.name}",
                task_id=a.task_id, worker_id=a.worker_id)

        # H6 exact duration
        if a.end - a.start != task.duration_hours * 60:
            add("H6", "WRONG_DURATION",
                f"{task.name} lasts {(a.end - a.start) / 60:g}h, declared {task.duration_hours}h",
                task_id=a.task_id, worker_id=a.worker_id)

        # H7 mandatory deadline
        if task.mandatory_deadline is not None:
            deadline = _minutes(task.mandatory_deadline)
            if deadline is None or a.end > deadline:
                add("H7", "DEADLINE_MISSED", f"{task.name} ends after mandatory deadline {task.mandatory_deadline}",
                    task_id=a.task_id, worker_id=a.worker_id)

        # H5 heat restriction: OUTDOOR + HIGH must not overlap a window that forbids it
        if task.environment == Environment.OUTDOOR and task.intensity == Intensity.HIGH:
            for window in heat_windows:
                if window.constraints.outdoor_high_intensity_allowed:
                    continue
                w_start, w_end = _minutes(window.from_time), _minutes(window.to_time)
                if w_start is None or w_end is None:
                    continue
                if a.start < w_end and w_start < a.end:
                    add("H5", "HEAT_WINDOW_OVERLAP",
                        f"{task.name} (OUTDOOR, HIGH intensity) overlaps {window.risk.value} window "
                        f"{window.from_time}-{window.to_time} where outdoor high-intensity work is not allowed",
                        task_id=a.task_id, worker_id=a.worker_id)

    # H3 required workers: distinct workers per task
    for task_id, group in by_task.items():
        distinct = len({a.worker_id for a in group})
        required = tasks_by_id[task_id].required_workers
        if distinct != required:
            add("H3", "WRONG_WORKER_COUNT",
                f"{tasks_by_id[task_id].name} has {distinct} distinct worker(s), requires {required}",
                task_id=task_id)

    # H4 dependencies: successor start >= predecessor end
    for t in tasks:
        if t.id not in by_task:
            continue
        succ_start = min(a.start for a in by_task[t.id])
        for dep in t.dependencies:
            if dep not in by_task:
                continue
            pred_end = max(a.end for a in by_task[dep])
            if succ_start < pred_end:
                add("H4", "DEPENDENCY_BROKEN", f"{t.name} starts before its predecessor {dep} has finished",
                    task_id=t.id)

    # H8 no double-booking (half-open intervals)
    by_worker: dict[str, list[_Assignment]] = {}
    for a in usable:
        by_worker.setdefault(a.worker_id, []).append(a)
    for worker_id, group in by_worker.items():
        for i, first in enumerate(group):
            for second in group[i + 1:]:
                if first.start < second.end and second.start < first.end:
                    add("H8", "DOUBLE_BOOKING",
                        f"{workers_by_id[worker_id].name} is booked on {first.task_id} and {second.task_id} at the same time",
                        task_id=second.task_id, worker_id=worker_id)

    return ValidationResult(
        valid=not violations, violations=violations, hard_constraints_checked=list(HARD_CONSTRAINTS)
    )
