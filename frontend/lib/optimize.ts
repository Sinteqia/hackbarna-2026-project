import type { OptimizeResponse } from "./types";

export type Outcome = "validated" | "infeasible" | "validation_failed" | "no_solution";

/**
 * Trusted response rule: a proposal is shown as valid ONLY when the solver said FEASIBLE
 * AND the independent validator accepted it. Anything else is never presented as a plan.
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
