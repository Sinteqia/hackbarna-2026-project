// SYNTHETIC DEMO DATA: pre-click presentation of the baseline scenario, matching the backend's
// demo current plan. After POST /optimize returns, the UI uses the backend response instead.

import type { HeatWindow, ScheduledTask, WorkerStatus } from "./types";

// Display-only FALLBACK roster, used only if GET /api/workers (backend metadata) is unreachable.
// Controls are disabled until a backend-validated baseline arrives, and the backend roster
// (`response.workers`) always replaces this, so it is never authoritative.
export const BASELINE_WORKERS: WorkerStatus[] = [
  { id: "w_marc", name: "Marc", skills: ["GENERAL"], available: true },
  { id: "w_laura", name: "Laura", skills: ["ELECTRICAL"], available: true },
  { id: "w_joan", name: "Joan", skills: ["GENERAL"], available: true },
  { id: "w_alex", name: "Alex", skills: ["CONCRETE"], available: true },
];

const task = (
  task_id: string,
  task_name: string,
  worker_name: string,
  start: string,
  end: string,
): ScheduledTask => ({
  task_id,
  task_name,
  worker_id: worker_name.toLowerCase(),
  worker_name,
  start,
  end,
});

export const BASELINE_PLAN: ScheduledTask[] = [
  task("t_unload", "Material unloading", "Marc", "08:00", "09:00"),
  task("t_concrete", "Concrete pouring", "Alex", "11:00", "13:00"),
  task("t_electrical", "Electrical installation", "Laura", "12:00", "14:00"),
  task("t_assembly", "Outdoor assembly", "Marc", "14:00", "16:00"),
  task("t_docs", "Documentation", "Joan", "16:00", "17:00"),
];

// Outdoor high-intensity tasks overlapping the HIGH window in the baseline plan.
export const BASELINE_CONFLICT_IDS = ["t_concrete", "t_assembly"];

export const BASELINE_HOT_WINDOWS: HeatWindow[] = [
  { from: "12:00", to: "16:00", risk: "HIGH", constraints: { outdoor_high_intensity_allowed: false } },
];
