"""T6: dynamic replanning (worker_unavailable). The backend applies the event to its own context."""

import pytest
from fastapi.testclient import TestClient

from app.demo_data import WORKERS
from app.main import app
from app.models import ScheduleResult, WorkerUnavailableEvent
from app.services.optimization import run_optimization
from app.services.replan import run_replan
from app.services.scenario import apply_worker_unavailable, load_baseline_context
from app.services.scheduler import schedule

client = TestClient(app)
EVENT = {"type": "worker_unavailable", "worker_id": "w_marc"}
REQUEST = {"scenario": "baseline", "event": EVENT}


@pytest.fixture(scope="module")
def baseline():
    return client.post("/optimize", json={"scenario": "baseline"}).json()


@pytest.fixture(scope="module")
def body():
    response = client.post("/replan", json=REQUEST)
    assert response.status_code == 200
    return response.json()


WORKER_IDS = ["w_marc", "w_laura", "w_joan", "w_alex"]
# Known demo outcomes. Laura (only ELECTRICAL) and Alex (only CONCRETE) are the sole holders of
# their skill, so INFEASIBLE is the correct, honest answer; constraints are never relaxed.
EXPECTED_STATUS = {"w_marc": "FEASIBLE", "w_joan": "FEASIBLE", "w_laura": "INFEASIBLE", "w_alex": "INFEASIBLE"}


def replan_body(worker_id):
    response = client.post(
        "/replan",
        json={"scenario": "baseline", "event": {"type": "worker_unavailable", "worker_id": worker_id}},
    )
    assert response.status_code == 200
    return response.json()


def test_supported_workers_are_the_backend_roster():
    assert {w.id: w.name for w in WORKERS} == {
        "w_marc": "Marc", "w_laura": "Laura", "w_joan": "Joan", "w_alex": "Alex",
    }


def test_baseline_roster_all_available(baseline):
    assert [(w["id"], w["name"], w["available"]) for w in baseline["workers"]] == [
        ("w_marc", "Marc", True), ("w_laura", "Laura", True),
        ("w_joan", "Joan", True), ("w_alex", "Alex", True),
    ]


SKILLS = {"w_marc": ["GENERAL"], "w_laura": ["ELECTRICAL"], "w_joan": ["GENERAL"], "w_alex": ["CONCRETE"]}
SAFE_KEYS = {"id", "name", "skills", "available"}  # no availability windows / scheduling data


def test_worker_metadata_exposes_skills_but_no_scheduling_constraints(baseline):
    for w in baseline["workers"]:
        assert set(w) == SAFE_KEYS and w["skills"] == SKILLS[w["id"]]
    endpoint = client.get("/scenarios/baseline/workers")
    assert endpoint.status_code == 200
    assert endpoint.json() == baseline["workers"]  # same backend-owned source before/after optimize
    assert client.get("/scenarios/nope/workers").status_code == 404


def test_replan_roster_keeps_skills_and_hides_windows():
    body = replan_body("w_marc")
    assert [set(w) for w in body["workers"]] == [SAFE_KEYS] * 4
    assert {w["id"]: w["skills"] for w in body["workers"]} == SKILLS


@pytest.mark.parametrize("worker_id", WORKER_IDS)
def test_every_worker_event_is_handled_by_the_backend(worker_id, baseline):
    body = replan_body(worker_id)
    assigned = {p["task_id"] for p in baseline["schedule"] if p["worker_id"] == worker_id}

    # previous plan is re-validated independently; H1 evidence only if the worker had assignments
    prev = body["current_plan_validation"]
    assert prev["valid"] == (not assigned)
    assert {v["task_id"] for v in prev["violations"]} == assigned
    assert all(v["constraint"] == "H1" and v["worker_id"] == worker_id for v in prev["violations"])

    # roster: only the selected worker is unavailable
    assert {w["id"] for w in body["workers"] if not w["available"]} == {worker_id}
    assert body["event"]["worker_id"] == worker_id

    assert body["status"] == EXPECTED_STATUS[worker_id]
    if body["status"] == "FEASIBLE":
        assert body["validated"] is True and body["solver"] == "ortools"
        assert body["validation"]["valid"] is True and body["validation"]["violations"] == []
        assert body["validation"]["hard_constraints_checked"] == [f"H{i}" for i in range(1, 9)]
        assert not any(p["worker_id"] == worker_id for p in body["schedule"])  # zero assignments
    else:
        assert body["status"] == "INFEASIBLE"
        assert body["schedule"] == [] and body["validated"] is False and body["validation"] is None


def test_marc_replacement_assignments_are_joan(body):
    reassigned = {c["task_id"]: c["new_worker_id"] for c in body["changes"]}
    assert reassigned == {"t_unload": "w_joan", "t_assembly": "w_joan"}


def test_unknown_worker_rejected_by_runtime_check():
    response = client.post(
        "/replan", json={"scenario": "baseline", "event": {"type": "worker_unavailable", "worker_id": "w_ghost"}}
    )
    assert response.status_code == 422 and "w_ghost" in response.json()["detail"]


def test_baseline_context_unchanged_after_events_for_all_workers(baseline):
    for worker_id in WORKER_IDS:
        replan_body(worker_id)
    assert client.post("/optimize", json={"scenario": "baseline"}).json() == baseline


def test_baseline_optimize_unchanged(baseline, body):  # `body` ran /replan first
    assert baseline["status"] == "FEASIBLE" and baseline["validated"] is True
    assert len(baseline["changes"]) == 3
    assert sum(c["worker_changed"] for c in baseline["changes"]) == 0
    # replan must not leak into the baseline context: Marc still works in the baseline plan
    again = client.post("/optimize", json={"scenario": "baseline"}).json()
    assert again == baseline
    assert any(p["worker_id"] == "w_marc" for p in again["schedule"])


def test_supported_event_accepted(body):
    assert body["event"]["type"] == "worker_unavailable"
    assert body["event"]["worker_id"] == "w_marc" and body["event"]["worker_name"] == "Marc"
    assert "reason" not in body["event"]["description"].lower()


@pytest.mark.parametrize(
    "event",
    [
        {"type": "worker_delayed", "worker_id": "w_marc"},  # unsupported event type
        {"type": "worker_unavailable", "worker_id": "w_ghost"},  # unknown worker (runtime check)
        {"type": "worker_unavailable", "worker_id": ""},  # empty id
        {"type": "worker_unavailable", "worker_id": "W_MARC"},  # ids are exact
        {"type": "worker_unavailable", "worker_id": 123},  # wrong type
        {"type": "worker_unavailable"},  # missing worker
        {"type": "worker_unavailable", "worker_id": "w_marc", "available_from": "07:00"},  # extra
        {"type": "worker_unavailable", "worker_id": "w_marc", "skills": ["ALL"]},  # extra
    ],
)
def test_unsupported_events_rejected(event):
    assert client.post("/replan", json={"scenario": "baseline", "event": event}).status_code == 422


@pytest.mark.parametrize(
    "field, value",
    [
        ("workers", []),
        ("tasks", []),
        ("current_plan", []),
        ("heat_windows", []),
        ("hard_constraints", []),
        ("validation", {"valid": True}),
        ("status", "FEASIBLE"),
    ],
)
def test_client_cannot_override_trust_sensitive_fields(field, value):
    response = client.post("/replan", json={**REQUEST, field: value})
    assert response.status_code == 422
    assert any(e["type"] == "extra_forbidden" for e in response.json()["detail"])


def test_unsupported_scenario_or_missing_event_rejected():
    assert client.post("/replan", json={"scenario": "nope", "event": EVENT}).status_code == 422
    assert client.post("/replan", json={"scenario": "baseline"}).status_code == 422


def test_previous_plan_invalid_under_updated_context_with_real_h1_evidence(baseline, body):
    val = body["current_plan_validation"]
    assert val["valid"] is False
    marc_tasks = {p["task_id"] for p in baseline["schedule"] if p["worker_id"] == "w_marc"}
    assert marc_tasks  # the previously validated plan did use Marc
    assert {v["constraint"] for v in val["violations"]} == {"H1"}
    assert {v["task_id"] for v in val["violations"]} == marc_tasks
    assert {v["worker_id"] for v in val["violations"]} == {"w_marc"}
    # the previous plan is exactly the validated baseline schedule
    assert body["current_plan"] == baseline["schedule"]


def test_replan_is_feasible_ortools_and_independently_validated(body):
    assert body["status"] == "FEASIBLE" and body["solver"] == "ortools"
    assert body["validated"] is True
    assert body["validation"]["valid"] is True
    assert body["validation"]["violations"] == []
    assert body["validation"]["hard_constraints_checked"] == [f"H{i}" for i in range(1, 9)]


def test_marc_has_no_assignment_after_replan(body):
    assert body["schedule"] and not any(p["worker_id"] == "w_marc" for p in body["schedule"])
    assert {p["task_id"] for p in body["schedule"]} == {p["task_id"] for p in body["current_plan"]}


def test_replan_changes_only_reassign_marc_tasks(body):
    changed = {c["task_id"] for c in body["changes"]}
    assert changed == {v["task_id"] for v in body["current_plan_validation"]["violations"]}
    assert all(c["worker_changed"] and c["old_worker_id"] == "w_marc" for c in body["changes"])
    assert body["current_plan_conflicts"] == []  # heat restriction still respected by the old plan


def test_replan_still_respects_heat_window(body):
    for p in body["schedule"]:
        if p["task_id"] in ("t_unload", "t_concrete", "t_assembly"):
            assert p["end"] <= "12:00" or p["start"] >= "16:00"


def test_solver_receives_updated_context_and_original_is_not_mutated():
    seen = []

    def spy(schedule_input):
        seen.append(schedule_input)
        return schedule(schedule_input)

    out = run_replan("baseline", WorkerUnavailableEvent(**EVENT), scheduler_fn=spy)
    assert out.status == "FEASIBLE" and len(seen) == 1
    marc = next(w for w in seen[0].workers if w.id == "w_marc")
    assert marc.available_from == marc.available_to  # empty availability handed to OR-Tools
    assert next(w for w in load_baseline_context().workers if w.id == "w_marc").available_to == "16:00"


def test_replan_validator_rejection_is_never_exposed_as_validated():
    def bad_scheduler(schedule_input):  # "solves" by keeping the old plan that uses Marc
        return ScheduleResult(status="FEASIBLE", solver="ortools",
                              schedule=schedule_input.current_plan, changes=[], violations=[])

    out = run_replan("baseline", WorkerUnavailableEvent(**EVENT), scheduler_fn=bad_scheduler)
    assert out.status == "VALIDATION_FAILED" and out.validated is False
    assert out.schedule == [] and out.validation is not None and out.validation.valid is False


def test_infeasible_when_no_general_worker_remains():
    ctx = load_baseline_context()
    baseline_plan = run_optimization(ctx).schedule
    no_marc = apply_worker_unavailable(ctx, "w_marc", baseline_plan)
    no_general = apply_worker_unavailable(no_marc, "w_joan", baseline_plan)  # domain-level only
    out = run_optimization(no_general)
    assert out.status == "INFEASIBLE" and out.schedule == [] and out.validated is False
