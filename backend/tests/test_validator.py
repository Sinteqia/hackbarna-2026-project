"""Validator tests: hand-built and mutated candidates; the validator never asks OR-Tools."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.demo_data import CURRENT_PLAN, TASKS, WORKERS
from app.main import app
from app.models import ScheduledTask, ScheduleInput
from app.services.heat_risk import build_windows
from app.services.scheduler import schedule
from app.services.validator import HARD_CONSTRAINTS, validate_schedule
from app.services.weather import load_fixture

NAMES = {t.id: t.name for t in TASKS}
WNAMES = {w.id: w.name for w in WORKERS}


def item(task_id, worker_id, start, end):
    return ScheduledTask(
        task_id=task_id, task_name=NAMES[task_id], worker_id=worker_id,
        worker_name=WNAMES[worker_id], start=start, end=end,
    )


def valid_plan():
    """Hand-written valid candidate (NOT produced by the solver)."""
    return [
        item("t_unload", "w_marc", "07:00", "08:00"),
        item("t_concrete", "w_alex", "08:00", "10:00"),
        item("t_assembly", "w_marc", "10:00", "12:00"),
        item("t_electrical", "w_laura", "12:00", "14:00"),
        item("t_docs", "w_joan", "16:00", "17:00"),
    ]


def replace(plan, task_id, **changes):
    return [p.model_copy(update=changes) if p.task_id == task_id else p for p in plan]


def with_task(task_id, **changes):
    return [t.model_copy(update=changes) if t.id == task_id else t for t in TASKS]


@pytest.fixture(scope="module")
def windows():
    return build_windows(load_fixture().hours)  # T1 operational windows (12:00-16:00 HIGH)


def validate(plan, windows, tasks=TASKS):
    return validate_schedule(plan, WORKERS, tasks, windows)


def constraints(result):
    return {v.constraint for v in result.violations}


def test_independence_no_solver_imports():
    source = Path(__file__).resolve().parents[1].joinpath("app/services/validator.py").read_text(encoding="utf-8")
    imports = [l for l in source.splitlines() if l.startswith(("import ", "from "))]
    assert not any("ortools" in l or "scheduler" in l for l in imports)


def test_hand_written_valid_plan_is_valid(windows):
    r = validate(valid_plan(), windows)
    assert r.valid and r.violations == []
    assert r.hard_constraints_checked == HARD_CONSTRAINTS


def test_optimized_ortools_candidate_is_valid(windows):
    result = schedule(ScheduleInput(workers=WORKERS, tasks=TASKS, heat_windows=windows, current_plan=CURRENT_PLAN))
    r = validate(result.schedule, windows)
    assert r.valid and r.violations == []


def test_current_plan_is_invalid_only_because_of_heat(windows):
    r = validate(CURRENT_PLAN, windows)
    assert not r.valid
    assert constraints(r) == {"H5"}
    assert {v.task_id for v in r.violations} == {"t_concrete", "t_assembly"}


def test_h1_outside_availability(windows):
    r = validate(replace(valid_plan(), "t_electrical", start="07:00", end="09:00"), windows)
    assert "H1" in constraints(r) and not r.valid


def test_h2_wrong_skill(windows):
    r = validate(replace(valid_plan(), "t_assembly", worker_id="w_alex"), windows)
    assert "H2" in constraints(r)


def test_h3_insufficient_required_workers(windows):
    r = validate(valid_plan(), windows, tasks=with_task("t_docs", required_workers=2))
    assert "H3" in constraints(r)


def test_h3_same_worker_twice_does_not_count_as_two_workers(windows):
    dup = valid_plan() + [item("t_docs", "w_joan", "16:00", "17:00")]
    r = validate(dup, windows, tasks=with_task("t_docs", required_workers=2))
    assert constraints(r) == {"H3", "STRUCTURE"}
    assert "DUPLICATE_ASSIGNMENT" in {v.code for v in r.violations}


def test_h3_two_distinct_workers_valid(windows):
    # Marc (GENERAL, until 16:00) and Joan (GENERAL) both do documentation at 15:00-16:00
    plan = replace(valid_plan(), "t_docs", start="15:00", end="16:00")
    plan.append(item("t_docs", "w_marc", "15:00", "16:00"))
    assert validate(plan, windows, tasks=with_task("t_docs", required_workers=2)).valid


def test_h4_broken_dependency(windows):
    r = validate(replace(valid_plan(), "t_assembly", start="08:00", end="10:00"), windows)
    assert constraints(r) == {"H4"}


def test_h5_outdoor_high_in_heat_window(windows):
    r = validate(replace(valid_plan(), "t_assembly", start="13:00", end="15:00"), windows)
    assert constraints(r) == {"H5"}
    assert r.violations[0].task_id == "t_assembly"


def test_h5_does_not_apply_to_partial_medium_or_indoor(windows):
    # electrical (PARTIAL/MEDIUM) 12:00-14:00 and documentation (INDOOR) 13:00-14:00 inside the window
    plan = replace(valid_plan(), "t_docs", start="13:00", end="14:00")
    assert validate(plan, windows).valid


def test_h6_incorrect_duration(windows):
    r = validate(replace(valid_plan(), "t_electrical", start="12:00", end="15:00"), windows)
    assert constraints(r) == {"H6"}


def test_h7_missed_deadline(windows):
    r = validate(valid_plan(), windows, tasks=with_task("t_docs", mandatory_deadline="16:00"))
    assert constraints(r) == {"H7"}


def test_no_deadline_no_h7(windows):
    r = validate(valid_plan(), windows, tasks=with_task("t_docs", mandatory_deadline=None))
    assert r.valid


def test_h8_double_booking(windows):
    r = validate(replace(valid_plan(), "t_docs", worker_id="w_marc", start="07:00", end="08:00"), windows)
    assert constraints(r) == {"H8"}


def test_boundary_back_to_back_is_not_overlap(windows):
    # Marc: unloading 07:00-08:00 then documentation 08:00-09:00
    r = validate(replace(valid_plan(), "t_docs", worker_id="w_marc", start="08:00", end="09:00"), windows)
    assert r.valid


def test_structural_unknown_task_worker_interval_and_missing(windows):
    plan = valid_plan()[:-1]  # documentation missing
    plan += [
        ScheduledTask(task_id="t_ghost", task_name="x", worker_id="w_marc", worker_name="Marc", start="09:00", end="10:00"),
        ScheduledTask(task_id="t_docs", task_name="d", worker_id="w_nobody", worker_name="?", start="16:00", end="17:00"),
        ScheduledTask(task_id="t_docs", task_name="d", worker_id="w_joan", worker_name="Joan", start="17:00", end="16:00"),
        ScheduledTask(task_id="t_docs", task_name="d", worker_id="w_joan", worker_name="Joan", start="lunch", end="17:00"),
    ]
    r = validate(plan, windows)
    codes = {v.code for v in r.violations}
    assert {"UNKNOWN_TASK", "UNKNOWN_WORKER", "INVALID_INTERVAL", "UNPARSEABLE_TIME"} <= codes
    assert not r.valid


def test_structural_missing_task(windows):
    r = validate(valid_plan()[:-1], windows)
    assert [v.code for v in r.violations] == ["MISSING_TASK"]


def test_validate_endpoint():
    client = TestClient(app)
    windows = [w.model_dump(by_alias=True, mode="json") for w in build_windows(load_fixture().hours)]

    def post(plan):
        return client.post("/validate", json={
            "candidate_schedule": [p.model_dump(mode="json") for p in plan],
            "workers": [w.model_dump(mode="json") for w in WORKERS],
            "tasks": [t.model_dump(mode="json") for t in TASKS],
            "heat_windows": windows,
        }).json()

    ok = post(valid_plan())
    assert ok["valid"] is True and ok["violations"] == []
    bad = post(CURRENT_PLAN)
    assert bad["valid"] is False
    assert {v["task_id"] for v in bad["violations"] if v["constraint"] == "H5"} == {"t_concrete", "t_assembly"}
