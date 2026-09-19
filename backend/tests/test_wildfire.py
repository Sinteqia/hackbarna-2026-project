"""Norrsken: Deepfire signal -> Site -> WorkZone/Task -> configured restriction (H9) -> solver -> validator.

No test calls the real Deepfire API or needs credentials: hotspot fetchers are simulated.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.demo_data import CURRENT_PLAN, SITE, TASKS, WORKERS
from app.main import app
from app.models import ScheduledTask, ScheduleInput, WildfireRestriction
from app.services import deepfire, wildfire
from app.services.heat_risk import build_windows
from app.services.scenario import load_baseline_context
from app.services.scheduler import schedule
from app.services.validator import validate_schedule
from app.services.weather import load_fixture

client = TestClient(app)
NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
OUTDOOR_TASKS = {"t_unload", "t_concrete", "t_assembly"}


def hotspot(km_north: float, age_h: float = 5.0, hid: str = "h1") -> deepfire.Hotspot:
    return deepfire.Hotspot(
        id=hid, lat=SITE.latitude + km_north / 111.0, lon=SITE.longitude,
        observed_at=NOW - timedelta(hours=age_h), confidence="MEDIUM", source="VIIRS",
    )


def fetcher(*hotspots, truncated=False):
    return lambda lat, lon, radius: (list(hotspots), truncated)


def unavailable(*_):
    raise deepfire.DeepfireUnavailable("hotspots query failed (HTTP 503)")


ctx = load_baseline_context


# ---------------- signal -> site applicability -> zones/tasks ----------------


def test_fresh_hotspot_within_radius_is_applicable_and_maps_to_outdoor_zones_and_tasks():
    a = wildfire.assess_wildfire(ctx(), fetcher(hotspot(14.4)), now=NOW)
    assert a.status == "APPLICABLE_SIGNAL" and a.site_id == "site_barcelona"
    assert a.nearest_km == pytest.approx(14.4, abs=0.2) and a.hotspots_in_radius == 1
    assert a.affected_zone_ids == ["zone_loading", "zone_structural"]  # OUTDOOR zones only
    assert set(a.affected_task_ids) == OUTDOOR_TASKS  # electrical (PARTIAL) and docs (INDOOR) untouched
    r = a.restriction
    assert (r.from_time, r.to_time, r.outdoor_work_allowed) == ("07:00", "18:00", False)  # no invented end
    assert "CONFIGURED OPERATIONAL RULE" in a.rule_description
    assert "not a confirmed fire" in a.disclaimer and "not a legal prohibition" in a.disclaimer
    assert "CONFIGURED OPERATIONAL RULE" in r.rule  # the H9 restriction itself says it is configured


def test_radius_and_window_are_labelled_as_configured_demo_parameters_not_official_values():
    a = wildfire.assess_wildfire(ctx(), fetcher(hotspot(14.4)), now=NOW)
    assert (a.radius_km, a.fresh_hours) == (25.0, 24)  # unchanged demo configuration
    note = a.parameters_note
    assert note.startswith("CONFIGURED DEMO OPERATIONAL RULE PARAMETERS") and "25 km" in note and "24 h" in note
    for denied in ("Deepfire recommendations", "legal thresholds", "wildfire safety distances",
                   "official exclusion zones"):
        assert denied in note
    # present on every status, so it can never be missing from the API metadata
    for get in (fetcher(), unavailable, fetcher(hotspot(10.0, age_h=48))):
        assert wildfire.assess_wildfire(ctx(), get, now=NOW).parameters_note == note


def test_hotspot_outside_radius_is_not_applicable():
    a = wildfire.assess_wildfire(ctx(), fetcher(hotspot(60.0)), now=NOW)
    assert a.status == "NO_APPLICABLE_SIGNAL" and a.restriction is None and a.hotspots_in_radius == 0


def test_no_hotspots_is_never_reported_as_safe_or_low_risk():
    a = wildfire.assess_wildfire(ctx(), fetcher(), now=NOW)
    assert a.status == "NO_APPLICABLE_SIGNAL" and a.restriction is None
    assert "does not mean the site is safe" in a.disclaimer
    assert not any(w in (a.status + a.disclaimer).upper() for w in ("LOW RISK", "SAFE TO WORK"))


def test_stale_signal_is_not_treated_as_low_risk():
    a = wildfire.assess_wildfire(ctx(), fetcher(hotspot(10.0, age_h=48)), now=NOW)
    assert a.status == "STALE_SIGNAL" and a.restriction is None and a.hotspots_in_radius == 1


def test_unavailable_service_and_truncated_result_are_not_low_risk():
    a = wildfire.assess_wildfire(ctx(), unavailable, now=NOW)
    assert a.status == "UNAVAILABLE" and a.error == "hotspots query failed (HTTP 503)" and a.restriction is None
    t = wildfire.assess_wildfire(ctx(), fetcher(hotspot(60.0), truncated=True), now=NOW)
    assert t.status == "UNAVAILABLE" and "truncated" in t.error


def test_credentials_missing_is_unavailable_and_leaks_nothing(monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPFIRE_CLIENT_ID", raising=False)
    monkeypatch.delenv("DEEPFIRE_CLIENT_SECRET", raising=False)
    monkeypatch.setattr(deepfire, "_ENV_FILE", tmp_path / "missing.env")
    with pytest.raises(deepfire.DeepfireUnavailable) as exc:
        deepfire.fetch_active_hotspots(SITE.latitude, SITE.longitude, 25.0)
    assert str(exc.value) == "credentials not configured"


# ---------------- solver + independent validator under H9 ----------------


def test_applicable_signal_makes_outdoor_work_infeasible_and_never_fabricates_a_plan():
    out = wildfire.run_wildfire_optimization("baseline", fetcher(hotspot(14.4)), now=NOW)
    assert out.status == "INFEASIBLE" and out.solver == "ortools"
    assert out.schedule == [] and out.changes == [] and out.validated is False and out.validation is None
    assert out.wildfire.status == "APPLICABLE_SIGNAL"
    # the plan in force is re-validated independently: real H9 evidence for every OUTDOOR task
    prev = out.current_plan_validation
    assert prev.valid is False and "H9" in prev.hard_constraints_checked
    h9 = [v for v in prev.violations if v.constraint == "H9"]
    assert {v.task_id for v in h9} == OUTDOOR_TASKS
    assert all(v.code == "WILDFIRE_RESTRICTION_OVERLAP" for v in h9)


def test_no_applicable_signal_keeps_the_heat_result_and_checks_h9_vacuously():
    out = wildfire.run_wildfire_optimization("baseline", fetcher(), now=NOW)
    assert out.status == "FEASIBLE" and out.validated is True and len(out.changes) == 3
    assert out.validation.hard_constraints_checked == [f"H{i}" for i in range(1, 10)]
    assert out.validation.violations == []
    assert out.wildfire.status == "NO_APPLICABLE_SIGNAL"  # not a safety statement


@pytest.mark.parametrize("get_hotspots, status", [(unavailable, "SIGNAL_UNAVAILABLE"),
                                                  (fetcher(hotspot(10.0, age_h=48)), "SIGNAL_STALE")])
def test_blocking_signal_states_never_present_a_plan_as_wildfire_cleared(get_hotspots, status):
    out = wildfire.run_wildfire_optimization("baseline", get_hotspots, now=NOW)
    assert out.status == status and out.validated is False
    assert out.schedule == [] and out.changes == [] and out.validation is None
    assert "wildfire-cleared" in out.message


def test_solver_can_still_find_a_plan_when_the_restriction_does_not_bind():
    windows = build_windows(load_fixture(SITE).hours)
    late = WildfireRestriction(**{"from": "16:00", "to": "18:00"})  # after the heat-adjusted outdoor chain
    res = schedule(ScheduleInput(workers=WORKERS, tasks=TASKS, heat_windows=windows,
                                 wildfire_restrictions=[late], current_plan=CURRENT_PLAN))
    assert res.status == "FEASIBLE"
    val = validate_schedule(res.schedule, WORKERS, TASKS, windows, [late])
    assert val.valid and val.hard_constraints_checked[-1] == "H9"


def test_validator_detects_h9_independently_and_h9_is_only_checked_when_supplied():
    windows = build_windows(load_fixture(SITE).hours)
    restriction = WildfireRestriction(**{"from": "07:00", "to": "09:00"})
    plan = [  # unloading (OUTDOOR) inside the restricted window; everything else valid
        ScheduledTask(task_id="t_unload", task_name="Material unloading", worker_id="w_marc", worker_name="Marc",
                      start="07:00", end="08:00"),
        ScheduledTask(task_id="t_concrete", task_name="Concrete pouring", worker_id="w_alex", worker_name="Alex",
                      start="09:00", end="11:00"),
        ScheduledTask(task_id="t_assembly", task_name="Outdoor assembly", worker_id="w_marc", worker_name="Marc",
                      start="11:00", end="12:00"),
        ScheduledTask(task_id="t_electrical", task_name="Electrical installation", worker_id="w_laura",
                      worker_name="Laura", start="12:00", end="14:00"),
        ScheduledTask(task_id="t_docs", task_name="Documentation", worker_id="w_joan", worker_name="Joan",
                      start="16:00", end="17:00"),
    ]
    without = validate_schedule(plan, WORKERS, TASKS, windows)  # no wildfire assessment supplied
    assert "H9" not in without.hard_constraints_checked
    with_h9 = validate_schedule(plan, WORKERS, TASKS, windows, [restriction])
    assert "H9" in with_h9.hard_constraints_checked
    assert {(v.constraint, v.task_id) for v in with_h9.violations if v.constraint == "H9"} == {("H9", "t_unload")}


# ---------------- API + trust boundary + heat regression ----------------


def test_endpoint_uses_backend_queried_signal_and_rejects_client_supplied_signals(monkeypatch):
    monkeypatch.setattr(deepfire, "fetch_active_hotspots", fetcher(hotspot(14.4)))
    body = client.post("/wildfire/optimize", json={"scenario": "baseline"}).json()
    assert body["status"] == "INFEASIBLE" and body["wildfire"]["status"] == "APPLICABLE_SIGNAL"
    assert body["scenario"] == "baseline" and body["wildfire"]["site_id"] == "site_barcelona"
    for extra in ({"hotspots": []}, {"wildfire": {"status": "NO_APPLICABLE_SIGNAL"}}, {"radius_km": 0},
                  {"restriction": None}, {"site_id": "x"}):
        assert client.post("/wildfire/optimize", json={"scenario": "baseline", **extra}).status_code == 422
    assert client.post("/wildfire/optimize", json={"scenario": "nope"}).status_code == 422


def test_heat_flow_is_unchanged_by_the_wildfire_integration(monkeypatch):
    monkeypatch.setattr(deepfire, "fetch_active_hotspots", fetcher(hotspot(14.4)))
    client.post("/wildfire/optimize", json={"scenario": "baseline"})  # must not leak into the baseline
    opt = client.post("/optimize", json={"scenario": "baseline"}).json()
    assert opt["status"] == "FEASIBLE" and opt["validated"] is True and len(opt["changes"]) == 3
    assert opt["validation"]["hard_constraints_checked"] == [f"H{i}" for i in range(1, 9)]  # no H9 on heat flow
    assert "wildfire" not in opt
