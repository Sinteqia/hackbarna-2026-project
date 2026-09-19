import type { Change, OptimizeResponse } from "./types";

export type Outcome = "validated" | "infeasible" | "validation_failed" | "no_solution";

/**
 * Trusted response rule: a proposal is shown as valid ONLY when the solver said FEASIBLE
 * AND the independent validator accepted it. Anything else is never presented as a plan.
 * Applies to both POST /optimize and POST /replan responses.
 */
export function classify(r: OptimizeResponse): Outcome {
  if (
    r.status === "FEASIBLE" &&
    r.validated === true &&
    r.validation?.valid === true &&
    r.schedule.length > 0
  ) {
    return "validated";
  }
  if (r.status === "INFEASIBLE") return "infeasible";
  if (r.status === "VALIDATION_FAILED" || r.status === "FEASIBLE") return "validation_failed";
  return "no_solution";
}

/** Row tag per changed task: a worker change reads REASSIGNED, a time change reads MOVED. */
export function changeLabels(changes: Change[]): Map<string, string> {
  return new Map(changes.map((c) => [c.task_id, c.worker_changed ? "REASSIGNED" : "MOVED"]));
}
