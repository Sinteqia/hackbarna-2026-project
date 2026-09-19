from fastapi import FastAPI

from app.models import ForecastResponse
from app.services.heat_risk import build_windows
from app.services.weather import get_forecast

DISCLAIMER = (
    "Prototype Heat Risk Engine: operational demo thresholds only. "
    "Not a certified WBGT, not an occupational-risk assessment, not medical or legal advice."
)

app = FastAPI()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/forecast", response_model=ForecastResponse)
def forecast(demo: bool = False) -> ForecastResponse:
    """Weather -> operational heat risk windows. `?demo=true` forces the synthetic fixture."""
    weather = get_forecast(demo=demo)
    return ForecastResponse(
        location=weather.location,
        source=weather.source,
        fallback_reason=weather.fallback_reason,
        disclaimer=DISCLAIMER,
        hourly=weather.hours,
        risk_windows=build_windows(weather.hours),
    )
