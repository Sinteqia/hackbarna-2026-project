# Project

HackBarna 2026 prototype.

## Architecture

Frontend: Next.js + TypeScript + Tailwind
Backend: FastAPI + Python

## Development

Backend (http://localhost:8000/health):

```
cd backend
python -m venv .venv
.venv\Scripts\activate   # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Forecast (Weather -> Prototype Heat Risk Engine -> operational constraints):

- `GET /forecast` uses Open-Meteo (Barcelona); on failure it falls back to the fixture and reports `source` and `fallback_reason`.
- `GET /forecast?demo=true` forces the SYNTHETIC fixture `backend/fixtures/barcelona_forecast_demo.json` (reproducible demo, not a real forecast).
- Risk uses apparent temperature when available, otherwise air temperature. Thresholds live in `backend/app/services/heat_risk.py`; they are prototype operational thresholds for demo, not a certified WBGT nor medical/legal guidance.
- Tests: `cd backend && .venv\Scripts\python -m pytest`

Frontend (http://localhost:3000):

```
cd frontend
npm install
npm run dev
```
