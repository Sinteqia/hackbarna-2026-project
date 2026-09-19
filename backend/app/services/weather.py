"""Weather adapter: Open-Meteo (live) with an explicit, visible fixture fallback.

Only this module knows the Open-Meteo JSON shape; the rest of the app uses WeatherForecast.
"""

import json
from pathlib import Path

import httpx

from app.models import Site, WeatherForecast, WeatherHour

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_SECONDS = 5.0
FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "barcelona_forecast_demo.json"


def parse_open_meteo(payload: dict) -> list[WeatherHour]:
    """Convert an Open-Meteo `hourly` payload to internal WeatherHour objects."""
    hourly = payload["hourly"]
    times = hourly["time"]
    temps = hourly["temperature_2m"]
    apparent = hourly.get("apparent_temperature") or [None] * len(times)
    humidity = hourly.get("relative_humidity_2m") or [None] * len(times)
    if not (len(times) == len(temps) == len(apparent) == len(humidity)):
        raise ValueError("Open-Meteo hourly arrays have different lengths")

    hours = [
        WeatherHour(
            time=t,
            temperature_c=temp,
            apparent_temperature_c=app,
            relative_humidity_pct=hum,
        )
        for t, temp, app, hum in zip(times, temps, apparent, humidity)
        if temp is not None  # skip hours without a usable reading
    ]
    if not hours:
        raise ValueError("Open-Meteo returned no usable hourly data")
    return hours


def load_fixture(site: Site) -> WeatherForecast:
    """The synthetic demo fixture, labelled with the site it stands in for."""
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return WeatherForecast(
        location=site.location_name, source="fixture", hours=parse_open_meteo(payload)
    )


def fetch_open_meteo(site: Site) -> WeatherForecast:
    response = httpx.get(
        OPEN_METEO_URL,
        params={
            "latitude": site.latitude,
            "longitude": site.longitude,
            "hourly": "temperature_2m,apparent_temperature,relative_humidity_2m",
            "timezone": "Europe/Madrid",
            "forecast_days": 1,
        },
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return WeatherForecast(
        location=site.location_name, source="open_meteo", hours=parse_open_meteo(response.json())
    )


def get_forecast(site: Site, demo: bool = False) -> WeatherForecast:
    """Forecast for a Site's coordinates. `demo=True` forces the fixture; a live failure falls
    back to it (reported in `fallback_reason`)."""
    if demo:
        return load_fixture(site)
    try:
        return fetch_open_meteo(site)
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        forecast = load_fixture(site)
        forecast.fallback_reason = f"open_meteo failed: {type(exc).__name__}: {exc}"
        return forecast
