"""Property-based tests: they check constraints, not one exact OR-Tools solution."""

import pytest
from fastapi.testclient import TestClient

from app.demo_data import CURRENT_PLAN, TASKS, WORKERS
from app.main import app
from app.models import ScheduleInput
from app.services.heat_risk import build_windows
from app.services.scheduler import find_heat_conflicts, schedule
from app.services.weather import load_fixture

WORKERS_BY_ID = {w.id: w for w in WORKERS}
TASKS_BY_ID = {t.id: t for t in TASKS}


def h(hhmm: str) -> int:
    return int(hhmm.split(":")[0])


@pytest.fixture(scope="module")
def heat_windows():
    # Single source of truth: T1 engine on the synthetic fixture.
    return build_windows(load_fixture().hours)


@pytest.fixture(scope="module")
def result(heat_windows):
    return schedule(
        ScheduleInput(workers=WORKERS, tasks=TASKS, heat_windows=heat_windows, current_plan=CURRENT_PLAN)
    )


def test_demo_dataset_is_feasible(result):
    assert result.status == "FEASIBLE"
    assert result.solver == "ortools"
    assert result.violations == []
    assert {p.task_id for p in result.schedule} == set(TASKS_BY_ID)


def test_workers_have_required_skill(result):
    for p in result.schedule:
        assert TASKS_BY_ID[p.task_id].required_skill in WORKERS_BY_ID[p.worker_id].skills


def test_tasks_inside_worker_availability(result):
    for p in result.schedule:
        w = WORKERS_BY_ID[p.worker_id]
        assert h(w.available_from) <= h(p.start) and h(p.end) <= h(w.available_to)


def test_dependencies_respected(result):
    by_task = {p.task_id: p for p in result.schedule}
    for t in TASKS:
        for dep in t.dependencies:
            assert h(by_task[t.id].start) >= h(by_task[dep].end)
    assert h(by_task["t_unload"].end) <= h(by_task["t_concrete"].start)
    assert h(by_task["t_concrete"].end) <= h(by_task["t_assembly"].start)


def test_no_worker_double_booking(result):
    for wid in WORKERS_BY_ID:
        spans = sorted((h(p.start), h(p.end)) for p in result.schedule if p.worker_id == wid)
        for (_, prev_end), (next_start, _) in zip(spans, spans[1:]):
            assert prev_end <= next_start


def test_no_outdoor_high_task_overlaps_high_window(result, heat_windows):
    high = [w for w in heat_windows if w.risk.value == "HIGH"]
    assert [(w.from_time, w.to_time) for w in high] == [("12:00", "16:00")]
    for p in result.schedule:
        t = TASKS_BY_ID[p.task_id]
        if t.environment.value == "OUTDOOR" and t.intensity.value == "HIGH":
            assert h(p.end) <= 12 or h(p.start) >= 16, p


def test_durations_preserved(result):
    for p in result.schedule:
        assert h(p.end) - h(p.start) == TASKS_BY_ID[p.task_id].duration_hours


def test_impossible_dataset_is_infeasible(heat_windows):
    # Concrete pouring needs unloading first (>= 1h) then 2h itself; a 09:00 deadline cannot be met.
    tasks = [
        t.model_copy(update={"mandatory_deadline": "09:00"}) if t.id == "t_concrete" else t
        for t in TASKS
    ]
    res = schedule(ScheduleInput(workers=WORKERS, tasks=tasks, heat_windows=heat_windows))
    assert res.status == "INFEASIBLE"
    assert res.schedule == []


def test_current_plan_conflicts_with_heat_restriction(heat_windows):
    conflicts = find_heat_conflicts(CURRENT_PLAN, TASKS, heat_windows)
    assert {c.task_id for c in conflicts} >= {"t_concrete", "t_assembly"}
    # the electrical (PARTIAL/MEDIUM) and documentation (INDOOR) tasks are not restricted
    assert not {c.task_id for c in conflicts} & {"t_electrical", "t_docs"}


def test_plan_stability_unaffected_tasks_preserved(result, heat_windows):
    by_task = {p.task_id: p for p in result.schedule}
    cur = {p.task_id: p for p in CURRENT_PLAN}
    for task_id in ("t_electrical", "t_docs"):  # not affected by the heat restriction
        new, old = by_task[task_id], cur[task_id]
        assert (new.worker_id, new.start, new.end) == (old.worker_id, old.start, old.end)


def test_plan_stability_only_heat_sensitive_chain_moves(result, heat_windows):
    # For the demo fixture: no worker reassignments, and only the outdoor+high tasks move.
    assert not any(c.worker_changed for c in result.changes)
    heat_sensitive = {
        t.id for t in TASKS if t.environment.value == "OUTDOOR" and t.intensity.value == "HIGH"
    }
    assert {c.task_id for c in result.changes} <= heat_sensitive
    assert find_heat_conflicts(result.schedule, TASKS, heat_windows) == []


def test_demo_optimize_endpoint():
    body = TestClient(app).get("/demo/optimize").json()
    assert body["weather_source"] == "fixture"
    assert body["result"]["status"] == "FEASIBLE"
    assert body["current_plan_conflicts"]
    assert body["result"]["changes"]
