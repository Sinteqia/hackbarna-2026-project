"""Worker "NOT" -> reject ONE proposed assignment -> trusted replanning (H10). Synthetic data only."""

import pytest
from fastapi.testclient import TestClient

from app.demo_data import SITE, TASKS, WORKERS
from app.main import app
from app.models import RejectedAssignment, ScheduleInput
from app.services.heat_risk import build_windows
from app.services.scenario import load_baseline_context
from app.services.scheduler import schedule
from app.services.validator import validate_schedule
from app.services.weather import load_fixture

client = TestClient(app)
URL = "/replan/assignment-rejection"


def reject(worker_id, task_id, **extra):
    return client.post(URL, json={"scenario": "baseline",
                                  "rejected_assignment": {"worker_id": worker_id, "task_id": task_id}, **extra})


@pytest.fixture(scope="module")
def baseline():
    return client.post("/optimize", json={"scenario": "baseline"}).json()


@pytest.fixture(scope="module")
def marc_assembly():
    """The documented example: Marc declines Outdoor assembly (10:00-12:00)."""
    r = reject("w_marc", "t_assembly")
    assert r.status_code == 200
    return r.json()


def by_task(plan):
    return {p["task_id"]: p for p in plan}


# ---------------- A/B/C: a valid alternative exists ----------------


def test_candidate_before_rejection_has_marc_on_assembly(baseline):
    p = by_task(baseline["schedule"])["t_assembly"]
    assert (p["worker_id"], p["start"], p["end"]) == ("w_marc", "10:00", "12:00")


def test_rejection_yields_a_different_valid_assignment(marc_assembly, baseline):
    assert marc_assembly["status"] == "FEASIBLE" and marc_assembly["solver"] == "ortools"
    assert marc_assembly["validated"] is True
    new = by_task(marc_assembly["schedule"])["t_assembly"]
    assert new["worker_id"] != "w_marc"  # A: another worker performs it
    assert (new["worker_id"], new["start"], new["end"]) == ("w_joan", "10:00", "12:00")
    # only that assignment changed; the plan is otherwise preserved
    assert [c["task_id"] for c in marc_assembly["changes"]] == ["t_assembly"]
    assert marc_assembly["changes"][0]["old_worker_id"] == "w_marc" and marc_assembly["changes"][0]["worker_changed"]


def test_rejected_pair_is_absent_and_worker_is_not_globally_removed(marc_assembly):
    assert not any(p["worker_id"] == "w_marc" and p["task_id"] == "t_assembly" for p in marc_assembly["schedule"])  # B
    # NOT != unavailable: Marc still performs the other task he had (Material unloading)
    assert by_task(marc_assembly["schedule"])["t_unload"]["worker_id"] == "w_marc"
    assert {w["id"]: w["available"] for w in marc_assembly["workers"]}["w_marc"] is True


def test_all_existing_hard_constraints_remain_satisfied(marc_assembly):
    v = marc_assembly["validation"]
    assert v["valid"] is True and v["violations"] == []
    assert v["hard_constraints_checked"] == [f"H{i}" for i in range(1, 9)] + ["H10"]  # C (H9 only with wildfire)
    # independent re-validation of the returned schedule with the ordinary constraints only
    ctx = load_baseline_context()
    from app.models import ScheduledTask
    plan = [ScheduledTask(**p) for p in marc_assembly["schedule"]]
    again = validate_schedule(plan, ctx.workers, ctx.tasks, ctx.risk.windows)
    assert again.valid and again.hard_constraints_checked == [f"H{i}" for i in range(1, 9)]
    for p in plan:  # heat still respected for outdoor/high tasks
        if p.task_id in ("t_unload", "t_concrete", "t_assembly"):
            assert p.end <= "12:00" or p.start >= "16:00"


def test_response_exposes_the_rejected_pair_and_revalidates_the_rejected_candidate(marc_assembly):
    rej = marc_assembly["rejection"]
    assert (rej["worker_id"], rej["task_id"], rej["start"], rej["end"]) == ("w_marc", "t_assembly", "10:00", "12:00")
    assert "not unavailable" not in rej["description"] and "no reason is recorded" in rej["description"]
    prev = marc_assembly["current_plan_validation"]  # the rejected candidate, checked independently
    assert prev["valid"] is False
    assert [(v["constraint"], v["task_id"], v["worker_id"]) for v in prev["violations"]] == [
        ("H10", "t_assembly", "w_marc")]
    assert marc_assembly["scenario"] == "baseline"


def test_other_rejections_with_an_alternative(baseline):
    for worker, task, expected in (("w_marc", "t_unload", "w_joan"), ("w_joan", "t_docs", "w_marc")):
        body = reject(worker, task).json()
        assert body["status"] == "FEASIBLE" and body["validated"] is True
        got = by_task(body["schedule"])[task]["worker_id"]
        assert got == expected and got != worker


# ---------------- D/E/F + malformed: request validation ----------------


def test_unknown_worker_rejected():  # D
    r = reject("w_ghost", "t_assembly")
    assert r.status_code == 422 and "w_ghost" in r.json()["detail"]


def test_unknown_task_rejected():  # E
    r = reject("w_marc", "t_ghost")
    assert r.status_code == 422 and "t_ghost" in r.json()["detail"]


@pytest.mark.parametrize("worker, task", [("w_laura", "t_assembly"),  # both exist, pair not in candidate
                                          ("w_alex", "t_docs"),
                                          ("w_marc", "t_docs")])
def test_pair_not_in_the_proposed_plan_rejected(worker, task):  # F
    r = reject(worker, task)
    assert r.status_code == 422 and "not assigned" in r.json()["detail"]


@pytest.mark.parametrize("payload", [
    {},
    {"scenario": "baseline"},
    {"scenario": "baseline", "rejected_assignment": {"worker_id": "w_marc"}},
    {"scenario": "baseline", "rejected_assignment": {"task_id": "t_assembly"}},
    {"scenario": "baseline", "rejected_assignment": {"worker_id": 1, "task_id": "t_assembly"}},
    {"scenario": "baseline", "rejected_assignment": "w_marc:t_assembly"},
    {"scenario": "nope", "rejected_assignment": {"worker_id": "w_marc", "task_id": "t_assembly"}},
])
def test_malformed_input_rejected(payload):
    assert client.post(URL, json=payload).status_code == 422


@pytest.mark.parametrize("field, value", [("schedule", []), ("current_plan", []), ("workers", []), ("tasks", []),
                                          ("heat_windows", []), ("constraints", []), ("validation", {"valid": True})])
def test_client_cannot_supply_plan_constraints_or_metadata(field, value):
    r = reject("w_marc", "t_assembly", **{field: value})
    assert r.status_code == 422 and any(e["type"] == "extra_forbidden" for e in r.json()["detail"])
    nested = client.post(URL, json={"scenario": "baseline", "rejected_assignment": {
        "worker_id": "w_marc", "task_id": "t_assembly", "worker_name": "x", "available_to": "18:00"}})
    assert nested.status_code == 422


# ---------------- G: no alternative -> INFEASIBLE, nothing fabricated ----------------


@pytest.mark.parametrize("worker, task", [("w_alex", "t_concrete"), ("w_laura", "t_electrical")])
def test_no_alternative_is_infeasible_without_fabricating_a_plan(worker, task):
    body = reject(worker, task).json()  # Alex is the only CONCRETE worker, Laura the only ELECTRICAL one
    assert body["status"] == "INFEASIBLE" and body["solver"] == "ortools"
    assert body["schedule"] == [] and body["changes"] == [] and body["validated"] is False
    assert body["validation"] is None
    assert body["rejection"]["worker_id"] == worker and body["rejection"]["task_id"] == task
    assert body["current_plan_validation"]["valid"] is False  # the rejected candidate is invalid under H10


# ---------------- solver / independent validator units ----------------


def test_solver_forbids_only_the_pair_not_the_worker():
    windows = build_windows(load_fixture(SITE).hours)
    res = schedule(ScheduleInput(workers=WORKERS, tasks=TASKS, heat_windows=windows,
                                 rejected_assignments=[RejectedAssignment(worker_id="w_marc", task_id="t_assembly")]))
    assert res.status == "FEASIBLE"
    pairs = {(p.worker_id, p.task_id) for p in res.schedule}
    assert ("w_marc", "t_assembly") not in pairs
    assert any(w == "w_marc" for w, _ in pairs)  # Marc is still schedulable for other tasks


def test_validator_detects_a_rejected_pair_independently_and_checks_h10_only_when_supplied(baseline):
    from app.models import ScheduledTask
    ctx = load_baseline_context()
    plan = [ScheduledTask(**p) for p in baseline["schedule"]]  # still contains Marc + assembly
    without = validate_schedule(plan, ctx.workers, ctx.tasks, ctx.risk.windows)
    assert without.valid and "H10" not in without.hard_constraints_checked
    rej = [RejectedAssignment(worker_id="w_marc", task_id="t_assembly")]
    with_h10 = validate_schedule(plan, ctx.workers, ctx.tasks, ctx.risk.windows, rejected_assignments=rej)
    assert not with_h10.valid and "H10" in with_h10.hard_constraints_checked
    assert {(v.constraint, v.task_id) for v in with_h10.violations} == {("H10", "t_assembly")}


# ---------------- H/I: baseline immutable, /optimize unchanged ----------------


def test_baseline_context_stays_immutable_and_optimize_is_unchanged(baseline):
    before = load_baseline_context()
    for worker, task in (("w_marc", "t_assembly"), ("w_alex", "t_concrete"), ("w_joan", "t_docs")):
        reject(worker, task)
    after = load_baseline_context()
    assert [w.model_dump() for w in after.workers] == [w.model_dump() for w in before.workers]  # H
    assert after.rejected_assignments is None and after.wildfire_restrictions is None
    again = client.post("/optimize", json={"scenario": "baseline"}).json()
    assert again == baseline  # I
    assert again["status"] == "FEASIBLE" and again["validated"] is True and len(again["changes"]) == 3
    assert again["validation"]["hard_constraints_checked"] == [f"H{i}" for i in range(1, 9)]  # no H10 on /optimize
    assert "rejection" not in again
