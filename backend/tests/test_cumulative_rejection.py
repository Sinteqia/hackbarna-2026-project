"""Cumulative assignment rejections (ordered rejection_history), replayed server-side. Synthetic data."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import RejectedAssignment, ScheduledTask
from app.services.scenario import load_baseline_context
from app.services.validator import validate_schedule

client = TestClient(app)
URL = "/replan/assignment-rejection"
MARC_ASSEMBLY = {"worker_id": "w_marc", "task_id": "t_assembly"}
JOAN_ASSEMBLY = {"worker_id": "w_joan", "task_id": "t_assembly"}


def history(*pairs):
    return client.post(URL, json={"scenario": "baseline", "rejection_history": list(pairs)})


def single(pair):
    return client.post(URL, json={"scenario": "baseline", "rejected_assignment": pair})


def pair(worker, task):
    return {"worker_id": worker, "task_id": task}


def by_task(plan):
    return {p["task_id"]: p for p in plan}


def assert_valid_and_pairs_absent(body, pairs):
    assert body["status"] == "FEASIBLE" and body["validated"] is True and body["solver"] == "ortools"
    assert body["validation"]["valid"] is True and body["validation"]["violations"] == []
    assert body["validation"]["hard_constraints_checked"] == [f"H{i}" for i in range(1, 9)] + ["H10"]
    held = {(p["worker_id"], p["task_id"]) for p in body["schedule"]}
    for p in pairs:
        assert (p["worker_id"], p["task_id"]) not in held  # every accumulated pair is absent
    # independent re-validation (H1-H8 + every accumulated H10 pair) of the returned schedule
    ctx = load_baseline_context()
    plan = [ScheduledTask(**p) for p in body["schedule"]]
    again = validate_schedule(plan, ctx.workers, ctx.tasks, ctx.risk.windows,
                              rejected_assignments=[RejectedAssignment(**p) for p in pairs])
    assert again.valid, again.violations


# ---------------- 1. compatibility ----------------


def test_single_form_is_unchanged_and_equals_a_history_of_one():
    a, b = single(MARC_ASSEMBLY), history(MARC_ASSEMBLY)
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json()  # identical response for both request forms
    body = a.json()
    assert body["rejection"] == body["rejection_history"][0] and len(body["rejection_history"]) == 1
    assert by_task(body["schedule"])["t_assembly"]["worker_id"] == "w_joan"  # original T7 behavior


# ---------------- 2. round 1 ----------------


def test_round_one_gives_assembly_to_joan_and_marc_keeps_other_work():
    body = history(MARC_ASSEMBLY).json()
    assert_valid_and_pairs_absent(body, [MARC_ASSEMBLY])
    plan = by_task(body["schedule"])
    assert plan["t_assembly"]["worker_id"] == "w_joan"
    assert plan["t_unload"]["worker_id"] == "w_marc"  # NOT != unavailable
    assert {w["id"]: w["available"] for w in body["workers"]}["w_marc"] is True


# ---------------- 3. round 2: Joan declines what she just inherited ----------------


def test_second_round_joan_declines_assembly_is_infeasible_without_fabricating_a_plan():
    body = history(MARC_ASSEMBLY, JOAN_ASSEMBLY).json()  # was 422 before this extension
    assert body["status"] == "INFEASIBLE" and body["solver"] == "ortools"  # no other GENERAL worker exists
    assert body["schedule"] == [] and body["changes"] == [] and body["validated"] is False
    assert body["validation"] is None
    assert [(r["worker_id"], r["task_id"]) for r in body["rejection_history"]] == [
        ("w_marc", "t_assembly"), ("w_joan", "t_assembly")]
    assert body["rejection"] == body["rejection_history"][-1]
    # the rejected candidate is the plan produced by round 1 (Joan on assembly), violating only the new pair
    assert by_task(body["current_plan"])["t_assembly"]["worker_id"] == "w_joan"
    assert [(v["constraint"], v["task_id"], v["worker_id"]) for v in body["current_plan_validation"]["violations"]] == [
        ("H10", "t_assembly", "w_joan")]


# ---------------- 4/8. a later pair must exist in THAT round's candidate; feasible chains ----------------


@pytest.mark.parametrize("second, holder_after", [
    (pair("w_marc", "t_unload"), {"t_unload": "w_joan", "t_assembly": "w_joan"}),   # Marc still held unloading
    (pair("w_joan", "t_docs"), {"t_docs": "w_marc", "t_assembly": "w_joan"}),        # Joan still held documentation
])
def test_second_pair_accepted_only_because_it_exists_after_round_one(second, holder_after):
    body = history(MARC_ASSEMBLY, second).json()
    assert_valid_and_pairs_absent(body, [MARC_ASSEMBLY, second])
    plan = by_task(body["schedule"])
    for task, worker in holder_after.items():
        assert plan[task]["worker_id"] == worker
    assert [c["task_id"] for c in body["changes"]] == [second["task_id"]]  # only round 2 changed vs candidate 1


def test_three_round_chain_replays_in_order():
    chain = [MARC_ASSEMBLY, pair("w_marc", "t_unload"), pair("w_joan", "t_docs")]
    body = history(*chain).json()
    assert body["status"] in ("FEASIBLE", "INFEASIBLE") and len(body["rejection_history"]) == 3
    if body["status"] == "FEASIBLE":
        assert_valid_and_pairs_absent(body, chain)
    else:
        assert body["schedule"] == [] and body["validated"] is False


# ---------------- 5. invalid / stale pairs ----------------


@pytest.mark.parametrize("pairs", [
    [MARC_ASSEMBLY, pair("w_laura", "t_assembly")],   # both exist, pair not in candidate 1
    [MARC_ASSEMBLY, pair("w_alex", "t_docs")],
    [MARC_ASSEMBLY, pair("w_marc", "t_docs")],
    [JOAN_ASSEMBLY, MARC_ASSEMBLY],                   # wrong order: Joan does not hold assembly in the baseline
])
def test_stale_or_out_of_order_pair_is_rejected(pairs):
    r = history(*pairs)
    assert r.status_code == 422 and "not assigned" in r.json()["detail"]


def test_error_message_names_the_round():
    detail = history(MARC_ASSEMBLY, pair("w_laura", "t_assembly")).json()["detail"]
    assert "previous rejection" in detail


def test_later_pair_after_an_infeasible_round_has_no_candidate():
    r = history(pair("w_alex", "t_concrete"), pair("w_marc", "t_unload"))  # Alex is the only CONCRETE worker
    assert r.status_code == 422 and "no validated plan" in r.json()["detail"]


# ---------------- 6/7. duplicates and unknown ids ----------------


def test_duplicate_rejection_is_rejected():
    r = history(MARC_ASSEMBLY, MARC_ASSEMBLY)
    assert r.status_code == 422 and "more than once" in r.json()["detail"]
    r2 = history(MARC_ASSEMBLY, pair("w_marc", "t_unload"), MARC_ASSEMBLY)
    assert r2.status_code == 422 and "more than once" in r2.json()["detail"]


@pytest.mark.parametrize("pairs, needle", [
    ([pair("w_ghost", "t_assembly")], "w_ghost"),
    ([pair("w_marc", "t_ghost")], "t_ghost"),
    ([MARC_ASSEMBLY, pair("w_ghost", "t_docs")], "w_ghost"),
    ([MARC_ASSEMBLY, pair("w_joan", "t_ghost")], "t_ghost"),
])
def test_unknown_worker_or_task_rejected_in_any_position(pairs, needle):
    r = history(*pairs)
    assert r.status_code == 422 and needle in r.json()["detail"]


# ---------------- request shape ----------------


@pytest.mark.parametrize("payload", [
    {"scenario": "baseline"},                                                          # neither form
    {"scenario": "baseline", "rejection_history": []},                                 # empty history
    {"scenario": "baseline", "rejected_assignment": MARC_ASSEMBLY, "rejection_history": [MARC_ASSEMBLY]},  # both forms
    {"scenario": "baseline", "rejection_history": [pair("w_marc", "t_unload")] * 11},   # over the cap
    {"scenario": "baseline", "rejection_history": [{"worker_id": "w_marc"}]},           # malformed pair
    {"scenario": "baseline", "rejection_history": [{**MARC_ASSEMBLY, "reason": "x"}]},  # extra field in pair
    {"scenario": "baseline", "rejection_history": [MARC_ASSEMBLY], "schedule": []},     # client schedule refused
    {"scenario": "nope", "rejection_history": [MARC_ASSEMBLY]},
])
def test_invalid_request_shapes_rejected(payload):
    assert client.post(URL, json=payload).status_code == 422


# ---------------- 9/10. infeasible never fabricates; baseline immutable ----------------


@pytest.mark.parametrize("pairs", [[pair("w_alex", "t_concrete")], [MARC_ASSEMBLY, JOAN_ASSEMBLY],
                                   [pair("w_laura", "t_electrical")]])
def test_infeasible_returns_no_schedule(pairs):
    body = history(*pairs).json()
    assert body["status"] == "INFEASIBLE" and body["schedule"] == [] and body["changes"] == []
    assert body["validated"] is False and body["validation"] is None


def test_baseline_unchanged_after_cumulative_calls():
    before = client.post("/optimize", json={"scenario": "baseline"}).json()
    ctx_before = [w.model_dump() for w in load_baseline_context().workers]
    for pairs in ([MARC_ASSEMBLY], [MARC_ASSEMBLY, JOAN_ASSEMBLY], [MARC_ASSEMBLY, pair("w_marc", "t_unload")]):
        history(*pairs)
    ctx = load_baseline_context()
    assert [w.model_dump() for w in ctx.workers] == ctx_before
    assert ctx.rejected_assignments is None and ctx.wildfire_restrictions is None
    after = client.post("/optimize", json={"scenario": "baseline"}).json()
    assert after == before and after["validation"]["hard_constraints_checked"] == [f"H{i}" for i in range(1, 9)]
    assert "rejection_history" not in after
