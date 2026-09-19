from datetime import datetime, timedelta

from app.demo_data import SITE
from app.models import Risk, WeatherHour
from app.services.heat_risk import build_windows, classify
from app.services.weather import load_fixture

BASE = datetime(2026, 7, 15, 0, 0)


def hour(h: int, temp: float, apparent: float | None = None) -> WeatherHour:
    return WeatherHour(
        time=BASE + timedelta(hours=h), temperature_c=temp, apparent_temperature_c=apparent
    )


def test_low_input_is_low():
    assert classify(hour(9, 22.0, 23.0)) == Risk.LOW


def test_high_input_is_high_and_blocks_outdoor_high_intensity():
    (window,) = build_windows([hour(13, 34.0, 35.0)])
    assert window.risk == Risk.HIGH
    assert window.constraints.outdoor_high_intensity_allowed is False


def test_very_high_input_is_very_high():
    assert classify(hour(14, 39.0, 40.0)) == Risk.VERY_HIGH


def test_consecutive_high_hours_form_one_window():
    hours = [hour(11, 30.0, 30.0)] + [hour(h, 34.0, 35.0) for h in (12, 13, 14, 15)]
    windows = build_windows(hours)
    high = [w for w in windows if w.risk == Risk.HIGH]
    assert len(high) == 1
    assert (high[0].from_time, high[0].to_time) == ("12:00", "16:00")


def test_missing_apparent_temperature_falls_back_to_temperature():
    assert classify(hour(13, 34.0, None)) == Risk.HIGH  # 34 -> HIGH via temperature_c
    assert classify(hour(13, 20.0, None)) == Risk.LOW


def test_fixture_loads():
    forecast = load_fixture(SITE)
    assert forecast.source == "fixture"
    assert len(forecast.hours) == 11
    assert all(h.apparent_temperature_c is not None for h in forecast.hours)
