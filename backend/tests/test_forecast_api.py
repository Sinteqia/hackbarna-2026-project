from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_forecast_demo_mode_returns_valid_structure():
    body = client.get("/forecast", params={"demo": "true"}).json()

    assert body["location"] == "Barcelona"
    assert body["source"] == "fixture"
    assert body["fallback_reason"] is None
    assert len(body["hourly"]) == 11

    high = [w for w in body["risk_windows"] if w["risk"] == "HIGH"]
    assert len(high) == 1
    assert (high[0]["from"], high[0]["to"]) == ("12:00", "16:00")
    assert high[0]["constraints"]["outdoor_high_intensity_allowed"] is False
