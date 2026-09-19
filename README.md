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

Frontend (http://localhost:3000):

```
cd frontend
npm install
npm run dev
```
