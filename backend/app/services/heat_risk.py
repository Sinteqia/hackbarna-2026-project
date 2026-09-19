"""Prototype Heat Risk Engine.

Deterministic, rule-based mapping: weather -> operational risk -> operational constraint.

PROTOTYPE OPERATIONAL THRESHOLDS FOR DEMO. They are NOT derived from any legal or
medical standard, are NOT a certified WBGT, and are not medical or legal advice.

Input choice: apparent temperature is the primary input when available; if it is
missing, we fall back to air temperature (temperature_c).
"""

from datetime import timedelta

from app.models import Constraints, HeatRiskWindow, Risk, WeatherHour

# Lower bound (inclusive, degC) of each level. Below MODERATE_FROM is LOW.
# Single place to tune the prototype rules.
MODERATE_FROM = 27.0
HIGH_FROM = 32.0
VERY_HIGH_FROM = 38.0

# Risk -> operational constraint. Single place to tune the mapping.
OUTDOOR_HIGH_INTENSITY_ALLOWED = {
    Risk.LOW: True,
    Risk.MODERATE: True,
    Risk.HIGH: False,
    Risk.VERY_HIGH: False,
}


def effective_temperature_c(hour: WeatherHour) -> float:
    if hour.apparent_temperature_c is not None:
        return hour.apparent_temperature_c
    return hour.temperature_c


def classify(hour: WeatherHour) -> Risk:
    t = effective_temperature_c(hour)
    if t >= VERY_HIGH_FROM:
        return Risk.VERY_HIGH
    if t >= HIGH_FROM:
        return Risk.HIGH
    if t >= MODERATE_FROM:
        return Risk.MODERATE
    return Risk.LOW


def constraints_for(risk: Risk) -> Constraints:
    return Constraints(outdoor_high_intensity_allowed=OUTDOOR_HIGH_INTENSITY_ALLOWED[risk])


def build_windows(hours: list[WeatherHour]) -> list[HeatRiskWindow]:
    """Group consecutive hours with the same risk into windows (`to` is exclusive)."""
    windows: list[HeatRiskWindow] = []
    ordered = sorted(hours, key=lambda h: h.time)
    start = end = None
    current: Risk | None = None

    def close() -> None:
        if start is None or end is None or current is None:
            return
        to_time = "24:00" if end.date() > start.date() else end.strftime("%H:%M")
        windows.append(
            HeatRiskWindow(
                from_time=start.strftime("%H:%M"),
                to_time=to_time,
                risk=current,
                constraints=constraints_for(current),
            )
        )

    for h in ordered:
        risk = classify(h)
        contiguous = end is not None and h.time == end
        if risk == current and contiguous:
            end = h.time + timedelta(hours=1)
            continue
        close()
        start, end, current = h.time, h.time + timedelta(hours=1), risk
    close()
    return windows
