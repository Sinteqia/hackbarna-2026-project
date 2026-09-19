// Mirrors the backend OptimizeResponse contract (backend/app/models.py). Do not add fields
// the backend does not return.

export type Risk = "LOW" | "MODERATE" | "HIGH" | "VERY_HIGH";

export interface HeatWindow {
  from: string; // "HH:MM"
  to: string; // exclusive
  risk: Risk;
  constraints: { outdoor_high_intensity_allowed: boolean };
}

export interface ScheduledTask {
  task_id: string;
  task_name: string;
  worker_id: string;
  worker_name: string;
  start: string;
  end: string;
}

export interface HeatConflict {
  task_id: string;
  task_name: string;
  start: string;
  end: string;
  window_from: string;
  window_to: string;
  risk: Risk;
}

export interface Change {
  task_id: string;
  task_name: string;
  old_start: string;
  old_end: string;
  new_start: string;
  new_end: string;
  old_worker_id: string;
  new_worker_id: string;
  worker_changed: boolean;
}

export interface ValidationViolation {
  constraint: string; // "H1".."H8" | "STRUCTURE"
  code: string;
  message: string;
  task_id: string | null;
  worker_id: string | null;
}

export interface ValidationResult {
  valid: boolean;
  violations: ValidationViolation[];
  hard_constraints_checked: string[];
}

export interface OptimizeResponse {
  scenario: string;
  data_label: string;
  risk: { source: string; description: string; windows: HeatWindow[] };
  current_plan: ScheduledTask[];
  current_plan_conflicts: HeatConflict[];
  current_plan_validation: ValidationResult;
  status: string; // FEASIBLE | INFEASIBLE | UNKNOWN | VALIDATION_FAILED
  solver: string;
  validated: boolean;
  schedule: ScheduledTask[];
  changes: Change[];
  validation: ValidationResult | null;
  message: string | null;
}
