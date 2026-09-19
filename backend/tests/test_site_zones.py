"""T6.5: Company -> Site -> WorkZone -> Task foundation (one demo site, scenario stays "baseline")."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.demo_data import COMPANY, SITE, TASKS, ZONES
from app.main import app
from app.models import Environment, Intensity
from app.services import weather
from app.services.scenario import load_baseline_context

client = TestClient(app)


def test_single_demo_site_with_coordinates():
    assert (SITE.id, SITE.name, SITE.location_name) == ("site_barcelona", "Construction Site — Barcelona", "Barcelona")
    assert -90 <= SITE.latitude <= 90 and -180 <= SITE.longitude <= 180


def test_four_zones_belong_to_the_site_and_own_the_environment():
    assert {z.name: z.environment for z in ZONES} == {
        "Loading": Environment.OUTDOOR,
        "Structural": Environment.OUTDOOR,
        "Covered Installation": Environment.PARTIAL,
        "Site Office": Environment.INDOOR,
    }
    assert {z.site_id for z in ZONES} == {SITE.id}


def test_every_task_references_a_zone_and_derives_its_environment_from_it():
    zones = {z.id: z for z in ZONES}
    for t in TASKS:
        assert t.work_zone_id in zones
        assert t.environment == zones[t.work_zone_id].environment  # single source: the WorkZone


def test_h5_inputs_preserved_outdoor_high_tasks_unchanged():
    outdoor_high = {t.id for t in TASKS if t.environment == Environment.OUTDOOR and t.intensity == Intensity.HIGH}
    assert outdoor_high == {"t_unload", "t_concrete", "t_assembly"}  # same set as before T6.5


def test_open_meteo_uses_backend_owned_site_coordinates(monkeypatch):
    seen = {}

    def fake_get(url, params, timeout):
        seen.update(params)
        raise httpx.ConnectError("no network in tests")

    monkeypatch.setattr(weather.httpx, "get", fake_get)
    forecast = weather.get_forecast(SITE)  # live path fails -> visible fixture fallback
    assert (seen["latitude"], seen["longitude"]) == (SITE.latitude, SITE.longitude)
    assert forecast.source == "fixture" and forecast.fallback_reason
    assert forecast.location == SITE.location_name


def test_weather_module_no_longer_owns_coordinates():
    assert not any(hasattr(weather, name) for name in ("LATITUDE", "LONGITUDE", "LOCATION_NAME"))


def test_risk_context_is_explicitly_bound_to_the_site():
    ctx = load_baseline_context()
    assert ctx.scenario == "baseline"  # scenario is NOT the site identity
    assert ctx.site.id == "site_barcelona" and ctx.risk.site_id == ctx.site.id
    assert SITE.name in ctx.risk.description and "SYNTHETIC" in ctx.risk.description


def test_optimize_and_replan_expose_safe_site_metadata_and_keep_behavior():
    opt = client.post("/optimize", json={"scenario": "baseline"}).json()
    assert opt["scenario"] == "baseline" and opt["status"] == "FEASIBLE" and opt["validated"] is True
    assert opt["risk"]["site_id"] == "site_barcelona"
    site = opt["site"]
    assert set(site) == {"company_name", "id", "name", "location_name", "latitude", "longitude", "zones", "task_zones"}
    assert set(site["zones"][0]) == {"id", "name", "environment"}  # no scheduling data
    assert site["task_zones"]["t_concrete"] == "zone_structural"
    assert len(opt["changes"]) == 3

    rep = client.post("/replan", json={"scenario": "baseline",
                                       "event": {"type": "worker_unavailable", "worker_id": "w_marc"}}).json()
    assert rep["site"] == site and rep["status"] == "FEASIBLE" and rep["validated"] is True
    assert client.post("/optimize", json={"scenario": "baseline"}).json() == opt  # baseline immutable


def test_site_metadata_endpoint():
    body = client.get("/scenarios/baseline/site").json()
    assert body["company_name"] == COMPANY.name and body["name"] == SITE.name
    assert [z["name"] for z in body["zones"]] == ["Loading", "Structural", "Covered Installation", "Site Office"]
    assert client.get("/scenarios/nope/site").status_code == 404


@pytest.mark.parametrize("field", ["site_id", "zones", "latitude", "work_zone_id"])
def test_client_cannot_inject_site_data_into_optimize_or_replan(field):
    assert client.post("/optimize", json={"scenario": "baseline", field: "x"}).status_code == 422
    body = {"scenario": "baseline", "event": {"type": "worker_unavailable", "worker_id": "w_marc"}, field: "x"}
    assert client.post("/replan", json=body).status_code == 422
