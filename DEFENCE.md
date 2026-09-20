# Norma / Quality Clouds Defence

Project: Operational Adaptation (`Sinteqia/hackbarna-2026-project`, branch `main`).

Entries marked `PENDING` are filled in from the second Norma scan and are not guessed here.

## Scan before
- commit: PENDING (confirm the scanned hash in Norma: `1af9af4` or `a507f70`; the code is identical, they differ only in `README.md`)
- date: 20/09/2026 09:20 (as shown by Norma)
- score: 79/100
- issue count: 52 (plus 1 AI finding, which Norma does not count in the score)

## Finding selected
- severity: High
- rule: Empty Catch Block Swallows Errors (rule id: PENDING, copy it from the Norma Issues view)
- file/line: `frontend/app/dashboard.tsx`, lines 74 and 84
- reason selected: single file, no change of behaviour or API contract, outside the solver, validator and H1–H10 logic.

## Fixed
Fixed: Empty Catch Block Swallows Errors (rule id PENDING) in `frontend/app/dashboard.tsx`
Why: the two fallback `catch` blocks now log a `console.warn` with the error instead of swallowing it silently.

- exact change: both `catch {}` blocks became `catch (error) { console.warn(..., error); }`. The display-only fallback roster and site name are unchanged.
- commit: `929ef1a` ("fix: handle dashboard fallback errors")
- validation: `eslint` exit 0, `tsc --noEmit` exit 0, `git diff --check` clean.

## Scan after
- commit: PENDING
- score: PENDING
- issue count: PENDING

## Left intentionally
Findings known from the first scan. Each one is to be confirmed against the second scan, and any finding the rescan no longer reports is removed from this list.

Left: Hardcoded Loopback API URL (`js-mng-loopback-url-1.0`) in `frontend/app/api/optimize/route.ts:5` and `frontend/app/api/wildfire/route.ts:5`
Why: the address is only a local-development default that `BACKEND_BASE_URL` overrides, and removing it would break the documented local run.

Left: Synchronous setState Inside useEffect (`rct-prf-setstate-in-useeffect-1.0`) in `frontend/app/dashboard.tsx:78` and `:88`
Why: the state is set after an awaited fetch inside an async function, so fixing it means restructuring the component, which was riskier than the benefit.

Left: Async Operation Without Error Handling (`js-no-error-handling-async-1.0`) in `frontend/app/dashboard.tsx:20` and `:25`
Why: `post()` is only called from `optimize()` and `markUnavailable()`, which already wrap it in `try/catch` and show the error.

Left: `assert` for runtime validation (rule id PENDING) in `backend/app/services/rejection.py:106`
Why: it sits in the H10 replanning logic, which was frozen, and the request model already guarantees the history is never empty.

Left: List endpoint without pagination (rule id PENDING) in `backend/app/main.py:85`
Why: adding pagination would change the public contract of an endpoint that returns a fixed roster of four synthetic workers.

Left: Sensitive data leaves the system through a response or a log (`sensitive-data-exposure-1.0`, AI finding, confidence 93%) in `backend/app/main.py:0`
Why: reviewed manually: the backend has no logging, Deepfire errors expose only an HTTP status or exception type and never credentials, and the worker data returned is synthetic (name, skills, availability flag) with no contact details.

Left: remaining findings of the first scan (issues 11–52): PENDING, to be listed from the second scan.

## Engineering rationale
A verifiable, low-risk change was prioritised over modifying functionality solely to chase a score. No functional changes were made for that purpose, and the solver, validator and H1–H10 constraints were left untouched.
