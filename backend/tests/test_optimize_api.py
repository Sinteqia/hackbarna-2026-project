"""T4: trusted POST /optimize flow. The backend owns the context; the client only names a scenario."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.demo_data import CURRENT_PLAN, TASKS, WORKERS
from app.main import app
from app.models import ScheduleResult
from app.services.optimization import run_optimization
from app.services.scenario import load_baseline_context

client = TestClient(app)


@pytest.fixture(scope="module")
def body():
    response = client.post("/optimize", json={"scenario": "baseline"})
    assert response.status_code == 200
    return response.json()


def by_task(plan):
    return {p["task_id"]: p for p in plan}


def test_baseline_is_feasible_and_validated(body):
    assert body["status"] == "FEASIBLE"
    assert body["solver"] == "ortools"
    assert body["validated"] is True
    assert body["validation"]["valid"] is True
    assert body["validation"]["violations"] == []
    assert body["validation"]["hard_constraints_checked"] == [f"H{i}" for i in range(1, 9)]


def test_risk_provenance_is_honest_synthetic_fixture(body):
    assert body["risk"]["source"] == "fixture"
    assert "SYNTHETIC" in body["risk"]["description"]
    assert body["data_label"] == "SYNTHETIC DEMO DATA"
    high = [w for w in body["risk"]["windows"] if w["risk"] == "HIGH"]
    assert [(w["from"], w["to"]) for w in high] == [("12:00", "16:00")]


def test_current_plan_has_exactly_two_h5_conflicts(body):
    assert {c["task_id"] for c in body["current_plan_conflicts"]} == {"t_concrete", "t_assembly"}
    assert len(body["current_plan_conflicts"]) == 2
    val = body["current_plan_validation"]
    assert val["valid"] is False
    h5 = [v for v in val["violations"] if v["constraint"] == "H5"]
    assert {v["task_id"] for v in h5} == {"t_concrete", "t_assembly"} and len(h5) == 2
    assert len(h5) == len(val["violations"])  # nothing else is wrong with the current plan


def test_optimized_plan_changes_only_heat_chain_without_reassignments(body):
    changes = body["changes"]
    assert {c["task_id"] for c in changes} == {"t_unload", "t_concrete", "t_assembly"}
    assert len(changes) == 3
    assert sum(c["worker_changed"] for c in changes) == 0


def test_unaffected_tasks_unchanged(body):
    plan = by_task(body["schedule"])
    assert (plan["t_electrical"]["worker_id"], plan["t_electrical"]["start"], plan["t_electrical"]["end"]) == (
        "w_laura", "12:00", "14:00")
    assert (plan["t_docs"]["worker_id"], plan["t_docs"]["start"], plan["t_docs"]["end"]) == (
        "w_joan", "16:00", "17:00")


def test_no_heat_overlap_after_optimization(body):
    for t in ("t_unload", "t_concrete", "t_assembly"):
        p = by_task(body["schedule"])[t]
        assert p["end"] <= "12:00" or p["start"] >= "16:00"


@pytest.mark.parametrize(
    "field, value",
    [
        ("workers", []),
        ("tasks", []),
        ("current_plan", []),
        ("heat_windows", []),
        ("hard_constraints", []),
        ("status", "FEASIBLE"),
        ("validation", {"valid": True}),
    ],
)
def test_client_cannot_override_trust_sensitive_fields(field, value):
    response = client.post("/optimize", json={"scenario": "baseline", field: value})
    assert response.status_code == 422
    assert any(e["type"] == "extra_forbidden" for e in response.json()["detail"])


def test_client_supplied_safe_window_cannot_weaken_optimization(body):
    # Attempt: declare everything allowed. It is rejected, and the backend result is unchanged.
    allow_all = [{"from": "07:00", "to": "18:00", "risk": "LOW",
                  "constraints": {"outdoor_high_intensity_allowed": True}}]
    response = client.post("/optimize", json={"scenario": "baseline", "heat_windows": allow_all})
    assert response.status_code == 422
    assert client.post("/optimize", json={"scenario": "baseline"}).json() == body


def test_unsupported_or_missing_scenario_fails_cleanly():
    assert client.post("/optimize", json={"scenario": "nope"}).status_code == 422
    assert client.post("/optimize", json={}).status_code == 422


def test_validator_failure_is_never_returned_as_validated_plan():
    # Controlled: a scheduler that "succeeds" with a candidate that violates H5 (the current plan).
    def bad_scheduler(_):
        return ScheduleResult(status="FEASIBLE", solver="ortools", schedule=CURRENT_PLAN,
                              changes=[], violations=[])

    out = run_optimization(load_baseline_context(), scheduler_fn=bad_scheduler)
    assert out.validated is False
    assert out.status == "VALIDATION_FAILED"
    assert out.schedule == [] and out.changes == []
    assert out.validation is not None and out.validation.valid is False
    assert {v.constraint for v in out.validation.violations} == {"H5"}


def test_infeasible_returns_no_schedule_and_no_validation():
    ctx = load_baseline_context()
    tight = [t.model_copy(update={"mandatory_deadline": "09:00"}) if t.id == "t_concrete" else t
             for t in TASKS]
    out = run_optimization(replace(ctx, tasks=tight))
    assert out.status == "INFEASIBLE"
    assert out.schedule == [] and out.validated is False and out.validation is None


def test_low_level_validate_and_forecast_still_work():
    assert client.get("/forecast", params={"demo": "true"}).status_code == 200
    payload = {
        "candidate_schedule": [p.model_dump(mode="json") for p in CURRENT_PLAN],
        "workers": [w.model_dump(mode="json") for w in WORKERS],
        "tasks": [t.model_dump(mode="json") for t in TASKS],
        "heat_windows": load_baseline_context().risk.model_dump(mode="json", by_alias=True)["windows"],
    }
    r = client.post("/validate", json=payload)
    assert r.status_code == 200 and r.json()["valid"] is False
