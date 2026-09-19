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

export interface AppliedEvent {
  type: string;
  worker_id: string;
  worker_name: string;
  description: string;
}

export interface WorkerStatus {
  id: string;
  name: string;
  skills: string[];
  available: boolean; // false once the operator marked the worker unavailable
}

export type Environment = "OUTDOOR" | "PARTIAL" | "INDOOR";

export interface ZoneView {
  id: string;
  name: string;
  environment: Environment;
}

// Safe Site/WorkZone metadata owned by the backend (no scheduling constraints).
export interface SiteView {
  company_name: string;
  id: string;
  name: string;
  location_name: string;
  latitude: number;
  longitude: number;
  zones: ZoneView[];
  task_zones: Record<string, string>; // task_id -> work_zone_id
}

export interface OptimizeResponse {
  scenario: string;
  data_label: string;
  risk: { site_id: string; source: string; description: string; windows: HeatWindow[] };
  site: SiteView;
  workers: WorkerStatus[]; // backend-owned roster
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

// POST /replan: same shape, evaluated under the UPDATED context. `current_plan` is the previously
// validated plan and `current_plan_validation` is that plan re-validated under the new context.
export interface ReplanResponse extends OptimizeResponse {
  event: AppliedEvent;
}
