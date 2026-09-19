"""OR-Tools CP-SAT scheduler.

Consumes the operational heat windows/constraints produced by the T1 Heat Risk Engine
(it never recomputes weather risk). Time is modelled in integer hourly slots:
slot 0 = 07:00 ... slot 11 = 18:00. Public inputs/outputs use "HH:MM".

Hard constraints:
  H1 worker availability   H2 skill match      H3 required workers
  H4 dependencies          H5 heat restriction H6 exact duration
  H7 mandatory deadline    H8 no double-booking
"""

from ortools.sat.python import cp_model

from app.models import (
    Change,
    Environment,
    HeatConflict,
    HeatRiskWindow,
    Intensity,
    ScheduledTask,
    ScheduleInput,
    ScheduleResult,
    Task,
)

SOLVER_NAME = "ortools"
DAY_START_HOUR = 7
DAY_END_HOUR = 18
HORIZON = DAY_END_HOUR - DAY_START_HOUR  # slots; last slot boundary = 18:00
MAX_SOLVE_SECONDS = 10.0
SHIFT_WEIGHT_PER_HOUR = 1  # cost of moving a task by one hour from the current plan
WORKER_CHANGE_WEIGHT = 2  # cost of assigning a different worker than in the current plan


def hhmm_to_slot(value: str) -> int:
    hour, minute = value.split(":")
    if minute != "00":
        raise ValueError(f"Only hourly times are supported, got {value!r}")
    return int(hour) - DAY_START_HOUR


def slot_to_hhmm(slot: int) -> str:
    return f"{DAY_START_HOUR + slot:02d}:00"


def is_heat_restricted(task: Task) -> bool:
    """H5 applies only to OUTDOOR + HIGH intensity (not INDOOR, not PARTIAL/MEDIUM)."""
    return task.environment == Environment.OUTDOOR and task.intensity == Intensity.HIGH


def prohibited_windows(heat_windows: list[HeatRiskWindow]) -> list[tuple[HeatRiskWindow, int, int]]:
    """Windows where T1 says outdoor high-intensity work is not allowed, as slot ranges."""
    return [
        (w, hhmm_to_slot(w.from_time), hhmm_to_slot(w.to_time))
        for w in heat_windows
        if not w.constraints.outdoor_high_intensity_allowed
    ]


def find_heat_conflicts(
    plan: list[ScheduledTask], tasks: list[Task], heat_windows: list[HeatRiskWindow]
) -> list[HeatConflict]:
    """Entries of `plan` that overlap a window where outdoor high-intensity work is not allowed."""
    by_id = {t.id: t for t in tasks}
    conflicts = []
    for item in plan:
        if not is_heat_restricted(by_id[item.task_id]):
            continue
        s, e = hhmm_to_slot(item.start), hhmm_to_slot(item.end)
        for window, a, b in prohibited_windows(heat_windows):
            if s < b and a < e:  # half-open interval overlap
                conflicts.append(
                    HeatConflict(
                        task_id=item.task_id, task_name=item.task_name,
                        start=item.start, end=item.end,
                        window_from=window.from_time, window_to=window.to_time, risk=window.risk,
                    )
                )
    return conflicts


def _result(status: str, message: str | None = None, **kwargs) -> ScheduleResult:
    return ScheduleResult(
        status=status, solver=SOLVER_NAME, schedule=kwargs.get("schedule", []),
        changes=kwargs.get("changes", []), violations=[], message=message,
    )


def _diff(new: list[ScheduledTask], current: list[ScheduledTask]) -> list[Change]:
    old_by_task = {}
    for item in current:
        old_by_task.setdefault(item.task_id, item)  # MVP: compare first assignment per task
    changes = []
    for item in new:
        old = old_by_task.get(item.task_id)
        if old is None:
            continue
        if (old.start, old.end, old.worker_id) != (item.start, item.end, item.worker_id):
            changes.append(
                Change(
                    task_id=item.task_id, task_name=item.task_name,
                    old_start=old.start, old_end=old.end, new_start=item.start, new_end=item.end,
                    old_worker_id=old.worker_id, new_worker_id=item.worker_id,
                    worker_changed=old.worker_id != item.worker_id,
                )
            )
            old_by_task.pop(item.task_id)  # only report a task once
    return changes


def schedule(data: ScheduleInput) -> ScheduleResult:
    task_ids = {t.id for t in data.tasks}
    for t in data.tasks:
        unknown = [d for d in t.dependencies if d not in task_ids]
        if unknown:
            raise ValueError(f"Task {t.id} depends on unknown task(s): {unknown}")

    forbidden = prohibited_windows(data.heat_windows)
    model = cp_model.CpModel()
    starts: dict[str, cp_model.IntVar] = {}
    max_start_sum = 0  # max possible value of sum(starts): each start is bounded by HORIZON - d
    assign: dict[tuple[str, str], cp_model.IntVar] = {}
    worker_intervals: dict[str, list] = {w.id: [] for w in data.workers}

    for t in data.tasks:
        d = t.duration_hours  # H6: fixed-size intervals preserve duration exactly
        candidates = [w for w in data.workers if t.required_skill in w.skills]  # H2
        if len(candidates) < t.required_workers:
            return _result("INFEASIBLE", f"Not enough workers with skill {t.required_skill} for {t.id}")
        if d > HORIZON:
            return _result("INFEASIBLE", f"Task {t.id} does not fit in the operational day")

        start = model.NewIntVar(0, HORIZON - d, f"start_{t.id}")
        starts[t.id] = start
        max_start_sum += HORIZON - d  # upper bound of this task's start (see objective)
        if t.mandatory_deadline:  # H7
            model.Add(start + d <= hhmm_to_slot(t.mandatory_deadline))

        literals = []
        for w in candidates:
            lit = model.NewBoolVar(f"assign_{t.id}_{w.id}")
            assign[t.id, w.id] = lit
            model.Add(start >= hhmm_to_slot(w.available_from)).OnlyEnforceIf(lit)  # H1
            model.Add(start + d <= hhmm_to_slot(w.available_to)).OnlyEnforceIf(lit)  # H1
            worker_intervals[w.id].append(
                model.NewOptionalFixedSizeIntervalVar(start, d, lit, f"iv_{t.id}_{w.id}")
            )
            literals.append(lit)
        model.Add(sum(literals) == t.required_workers)  # H3

        if is_heat_restricted(t):  # H5: finish before the window or start after it
            for i, (_, a, b) in enumerate(forbidden):
                before = model.NewBoolVar(f"before_{t.id}_{i}")
                model.Add(start + d <= a).OnlyEnforceIf(before)
                model.Add(start >= b).OnlyEnforceIf(before.Not())

    for t in data.tasks:  # H4
        for dep in t.dependencies:
            dep_task = next(x for x in data.tasks if x.id == dep)
            model.Add(starts[t.id] >= starts[dep] + dep_task.duration_hours)

    for intervals in worker_intervals.values():  # H8
        model.AddNoOverlap(intervals)

    # Objective: PLAN STABILITY dominates efficiency (soft constraints only; H1-H8 stay hard).
    #  - penalize |new start - current start| (per hour) and worker reassignment
    #  - secondary tie-breaker: earlier starts, sum(starts)
    # stability_cost is an integer, so any solution with a lower stability_cost gains at least
    # STABILITY_SCALE, which exceeds the largest possible sum(starts) swing (0..max_start_sum).
    # Hence stability is lexicographically dominant over the tie-breaker.
    current_by_task: dict[str, ScheduledTask] = {}
    for item in data.current_plan:
        current_by_task.setdefault(item.task_id, item)  # MVP: first assignment per task
    stability_terms = []
    for t in data.tasks:
        cur = current_by_task.get(t.id)
        if cur is None:
            continue
        deviation = model.NewIntVar(0, HORIZON, f"dev_{t.id}")
        model.AddAbsEquality(deviation, starts[t.id] - hhmm_to_slot(cur.start))
        stability_terms.append(SHIFT_WEIGHT_PER_HOUR * deviation)
        if (t.id, cur.worker_id) in assign:  # else reassignment is unavoidable: constant cost
            stability_terms.append(WORKER_CHANGE_WEIGHT * (1 - assign[t.id, cur.worker_id]))
    stability_scale = max_start_sum + 1
    model.Minimize(stability_scale * sum(stability_terms) + sum(starts.values()))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = MAX_SOLVE_SECONDS
    solver.parameters.num_workers = 1  # deterministic runs
    solver.parameters.random_seed = 0
    status = solver.Solve(model)

    if status == cp_model.INFEASIBLE:
        return _result("INFEASIBLE", "No schedule satisfies all hard constraints")
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return _result("UNKNOWN", f"Solver ended without a solution ({solver.StatusName(status)})")

    workers_by_id = {w.id: w for w in data.workers}
    tasks_by_id = {t.id: t for t in data.tasks}
    plan = []
    for (task_id, worker_id), lit in assign.items():
        if solver.Value(lit):
            s = solver.Value(starts[task_id])
            plan.append(
                ScheduledTask(
                    task_id=task_id, task_name=tasks_by_id[task_id].name,
                    worker_id=worker_id, worker_name=workers_by_id[worker_id].name,
                    start=slot_to_hhmm(s), end=slot_to_hhmm(s + tasks_by_id[task_id].duration_hours),
                )
            )
    plan.sort(key=lambda p: (p.start, p.task_id))
    return _result("FEASIBLE", schedule=plan, changes=_diff(plan, data.current_plan))
