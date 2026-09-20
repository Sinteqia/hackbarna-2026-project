# Operational Adaptation

> A heat alert doesn't protect a worker. Changing the work does.

Environmental alerts don't reorganise the work by themselves. Operational Adaptation doesn't send
generic weather alerts: it works out which site, work zone and scheduled tasks are affected by an
environmental signal, turns that into explicit operational constraints, and replans the operation.
If no schedule can satisfy the hard constraints, it returns `INFEASIBLE` instead of inventing a plan.

**Rules constrain. OR-Tools optimizes. The validator verifies. Humans approve.**

> **Prototype for a hackathon (HackBarna 2026).** All workers, tasks and sites are **synthetic demo
> data**. This is not a safety system: it is not a certified WBGT, not an occupational-risk assessment,
> not medical or legal advice, and it does not tell anyone that work is safe or that a person is fit
> to work. People remain responsible for operational decisions.

## Problem

A forecast or a wildfire signal says *"it is hot"* or *"there is a fire nearby"*. It does not say
which tasks on which site have to move, who can take them, or whether a valid schedule exists at all.
Working that out by hand is slow and error-prone.

## Architecture

```
Next.js UI ──► FastAPI backend ──► Open-Meteo forecast ──► Prototype Heat Risk Engine (rules)
                    │           └► Deepfire hotspots ────► configured wildfire rule (H9)
                    │
                    └► explicit constraints H1–H10 ──► OR-Tools CP-SAT (constraint optimization)
                                                    ──► independent validator (deterministic checks)
                                                    ──► candidate plan: FEASIBLE / INFEASIBLE / …

Worker confirmation (external to this repo):  Vonage WhatsApp Sandbox ⇄ Make ⇄ Supabase
```

| Component | Nature |
|---|---|
| Prototype Heat Risk Engine (`backend/app/services/heat_risk.py`) | deterministic rules |
| OR-Tools CP-SAT (`services/scheduler.py`) | constraint optimization (not described as deterministic) |
| Validator (`services/validator.py`) | deterministic checks, recomputed from the candidate data; does not trust the solver's status |

The backend owns the workers, tasks, plan and risk windows. The client only names a scenario; it
cannot supply or override the signal, the rule or the risk windows. No LLM is used in this
repository: planning, validation and constraint decisions are rules plus the solver.

## Operational model: Company → Site → WorkZone → Task

- **Site**: a location (demo: a construction site in Barcelona).
- **WorkZone**: owns the environment classification (`OUTDOOR`, `PARTIAL`, `INDOOR`).
- **Task**: belongs to one zone and derives its environment from it; has a required skill,
  intensity, duration, dependencies and an optional mandatory deadline.

Because the environment comes from the zone, a signal affects only the zones (and tasks) it applies to.

## Heat workflow

1. `GET /forecast` reads Open-Meteo for the site. On failure it falls back to a fixture and reports
   `source` and `fallback_reason`; `?demo=true` forces the synthetic fixture (reproducible demo).
2. The **Prototype Heat Risk Engine** maps apparent temperature (air temperature if missing) to an
   *operational heat risk* level and to time windows. Thresholds are prototype demo values in
   `heat_risk.py`.
3. Constraint **H5**: `OUTDOOR` + high-intensity tasks may not overlap a window that forbids them.
4. CP-SAT searches for a schedule that satisfies the constraints; the validator re-checks it.

## Constraints H1–H10

| ID | Constraint |
|---|---|
| H1 | Worker availability |
| H2 | Skill match |
| H3 | Required number of workers |
| H4 | Task dependencies |
| H5 | Heat restriction (`OUTDOOR` + high intensity) |
| H6 | Exact duration |
| H7 | Mandatory deadline |
| H8 | No double-booking |
| H9 | Configured wildfire restriction on `OUTDOOR` zones (only when a wildfire assessment takes part) |
| H10 | A rejected worker+task pair is forbidden; rejections accumulate (only when a rejection takes part) |

The validator always recomputes H1–H8, and additionally H9 / H10 when they apply to the request.
Soft goals (plan stability, efficiency) never relax a hard constraint.

## Solver + validator trust boundary

- The solver proposes a candidate; it is not the authority.
- The validator independently recomputes the constraints on that candidate. A candidate that fails
  validation is reported as `VALIDATION_FAILED` and not offered as a plan.
- Result statuses: `FEASIBLE`, `INFEASIBLE`, `UNKNOWN`, `VALIDATION_FAILED`.
- The validator confirms that a plan satisfies the **configured constraints**. It does not prove that
  a plan is safe.
- `INFEASIBLE` means no schedule satisfies the configured hard constraints; the response then has an
  empty `schedule`.

## Norrsken / Deepfire (wildfire, H9)

Deepfire provides a real spatial signal (satellite hotspots). Operational Adaptation translates that
signal through a **configured operational rule** into affected site zones and tasks. If no schedule
can satisfy the resulting hard constraint, it returns `INFEASIBLE` rather than inventing a plan.

- `POST /wildfire/optimize`: the backend queries Deepfire for the site location, applies the rule and
  optimizes and validates under it.
- Rule (demo): while at least one active hotspot observed in the last **24 h** lies within **25 km**
  of the site, `OUTDOOR` work is restricted for the whole planning day.
- **The 25 km / 24 h values are configured demo parameters.** They are not Deepfire recommendations,
  legal thresholds, wildfire safety distances or exclusion zones.
- A hotspot is a candidate-fire signal, not a confirmed fire. No hotspot, stale data or an
  unavailable service is never treated as "low risk" or "safe" (the assessment reports `UNAVAILABLE`).

## Assignment rejection and replanning (H10)

`POST /replan/assignment-rejection` handles a worker declining a proposed assignment. It accepts one
`rejected_assignment` or an ordered `rejection_history` (at most 10). The server replays the rounds
from the baseline, forbids only the rejected worker+task pairs, replans with OR-Tools and validates.
Unknown workers/tasks, duplicates and pairs not present in that round's candidate are rejected (422).

Demo behaviour (covered by backend tests): if Marc rejects *Outdoor assembly*, the plan is `FEASIBLE`
with the task reassigned to Joan (10:00–12:00); if Joan also rejects it, the result is `INFEASIBLE`
with an empty schedule. `POST /replan` applies a synthetic `worker_unavailable` event the same way.

## Worker confirmation, Make, Supabase, Vonage

These pieces live outside this repository (configured in each platform). Intended flow: the affected
worker receives a proposal by WhatsApp and answers `OK` / `NOT`; Make routes the reply, calls the
backend when a replan is needed, and Supabase records the state.

Status at the time of writing:

- **Demonstrated:** basic inbound/outbound WhatsApp through the **Vonage WhatsApp Sandbox**; a
  rejection (`NOT`) sent to the backend → H10 → OR-Tools → validator; the Make → Supabase
  `process_worker_response` call returning HTTP 200.
- **Not claimed as complete:** the fully dynamic WhatsApp loop (Marc `NOT` → Make → replan →
  Joan proposal → Joan `OK` → confirmed) and the Supabase `apply_replan_response` step. This section
  will be updated only if evidence confirms them.

Vonage is used in **sandbox** mode (recipients must opt in); this is not a production WhatsApp
Business deployment.

## Partners

- **Make**: orchestration of the worker-response flow.
- **Norrsken / Deepfire**: the real spatial wildfire signal (see above).
- **Quality Clouds / Norma**: code-quality scan → fix → rescan (see below).
- **Vonage** (additional integration): WhatsApp Sandbox messaging.
- Also used: Open-Meteo (forecast), Supabase (state), OR-Tools (solver).

## Quality Clouds / Norma

Scan → fix → rescan on the GitHub project. Details in [`DEFENCE.md`](DEFENCE.md).

- Scan before the fix: _to be completed after the scan_
- Finding fixed: _to be completed_
- Scan after the fix: _to be completed_

## Privacy, safety and limitations

- Synthetic demo data only; no real workers, projects or personal data in this repository.
- In a real deployment, worker phone numbers and replies would be personal data processed by Make,
  Supabase and Vonage/WhatsApp, and would need a proper data-protection review.
- Heat thresholds and the wildfire rule are prototype operational rules, not standards.
- Forecast and hotspot inputs are third-party data with their own limits and delays.
- The system supports planning; it makes no safety, medical-fitness or compliance guarantee, and it
  has not been assessed under the EU AI Act. A workplace-scheduling context should be treated as
  potentially high-risk until it is.

## Running locally

Backend (http://localhost:8000/health):

```
cd backend
python -m venv .venv
.venv\Scripts\activate   # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Backend tests: `cd backend && .venv\Scripts\python -m pytest`

Frontend (http://localhost:3000):

```
cd frontend
npm install
npm run dev
```

Also available: `npm run lint`, `npm run build`.

Environment (see `.env.example`; never commit real values):

- `DEEPFIRE_CLIENT_ID`, `DEEPFIRE_CLIENT_SECRET`: backend only, needed for `/wildfire/optimize`
  (read from the environment or a git-ignored repo-root `.env`). Without them the wildfire
  assessment reports `UNAVAILABLE`.
- `BACKEND_BASE_URL`: optional, frontend proxy target (default `http://127.0.0.1:8000`).

Backend endpoints: `GET /health`, `GET /forecast`, `GET /demo/optimize`, `POST /optimize`,
`POST /replan`, `POST /replan/assignment-rejection`, `POST /wildfire/optimize`,
`GET /scenarios/{scenario}/site`, `GET /scenarios/{scenario}/workers`, and `POST /validate`
(low-level tooling endpoint, not a trust boundary).
