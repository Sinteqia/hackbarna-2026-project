"use client";

import { useEffect, useState } from "react";
import { BASELINE_CONFLICT_IDS, BASELINE_HOT_WINDOWS, BASELINE_PLAN, BASELINE_WORKERS } from "@/lib/baseline";
import { changeLabels, classify } from "@/lib/optimize";
import type { OptimizeResponse, ReplanResponse, SiteView, WorkerStatus } from "@/lib/types";
import Timeline from "./timeline";
import WildfireCard from "./wildfire-card";
import WorkersTable from "./workers-table";

type Phase<T> =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "done"; data: T };

const ALL_CHECKS = ["H1", "H2", "H3", "H4", "H5", "H6", "H7", "H8"];

async function post<T>(url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method: "POST",
    ...(body === undefined ? {} : { headers: { "content-type": "application/json" }, body: JSON.stringify(body) }),
  });
  if (!res.ok) throw new Error(`Backend responded ${res.status}`);
  return (await res.json()) as T;
}

function Card({ title, badge, children }: { title: string; badge?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-xs font-bold tracking-widest text-slate-500 uppercase">{title}</h2>
        {badge}
      </div>
      {children}
    </section>
  );
}

function Pill({ tone, children }: { tone: "red" | "green" | "blue" | "slate"; children: React.ReactNode }) {
  const tones = {
    red: "bg-red-100 text-red-700",
    green: "bg-emerald-100 text-emerald-800",
    blue: "bg-sky-100 text-sky-700",
    slate: "bg-slate-100 text-slate-600",
  };
  return <span className={`rounded px-2 py-0.5 text-xs font-bold ${tones[tone]}`}>{children}</span>;
}

function Kpi({ label, value, sub, tone = "slate" }: { label: string; value: string; sub?: string; tone?: "red" | "green" | "slate" }) {
  const color = { red: "text-red-600", green: "text-emerald-700", slate: "text-slate-900" }[tone];
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm">
      <div className="text-xs font-bold tracking-widest text-slate-500 uppercase">{label}</div>
      <div className={`text-3xl leading-tight font-extrabold ${color}`}>{value}</div>
      <div className="h-4 text-xs text-slate-500">{sub}</div>
    </div>
  );
}

export default function Dashboard() {
  const [opt, setOpt] = useState<Phase<OptimizeResponse>>({ kind: "idle" });
  const [rep, setRep] = useState<Phase<ReplanResponse>>({ kind: "idle" });
  // Worker the operator just marked unavailable, shown as UNAVAILABLE while the replan runs.
  const [pendingWorker, setPendingWorker] = useState<string | null>(null);
  const [baseRoster, setBaseRoster] = useState<WorkerStatus[]>(BASELINE_WORKERS);
  const [baseSite, setBaseSite] = useState<SiteView | null>(null);

  // Safe backend metadata (workers, site/zones) so the screen is backend-sourced before any
  // optimization. Falls back to display-only defaults if the backend is unreachable.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/workers");
        if (!res.ok) return;
        const workers = (await res.json()) as WorkerStatus[];
        if (!cancelled && Array.isArray(workers) && workers.length > 0) setBaseRoster(workers);
      } catch (error) {
        // Recommended by Norma — fixed with Claude Sonnet 5 via Claude Code
        // keep the display-only fallback roster, but leave a trace of why
        console.warn("Could not load the worker roster from the backend; using the display-only fallback.", error);
      }
    })();
    (async () => {
      try {
        const res = await fetch("/api/site");
        if (!res.ok) return;
        const site = (await res.json()) as SiteView;
        if (!cancelled && site && Array.isArray(site.zones)) setBaseSite(site);
      } catch (error) {
        // Recommended by Norma — fixed with Claude Sonnet 5 via Claude Code
        // the header keeps its display-only fallback name, but leave a trace of why
        console.warn("Could not load the site metadata from the backend; using the display-only fallback.", error);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function optimize() {
    setRep({ kind: "idle" });
    setPendingWorker(null);
    setOpt({ kind: "loading" });
    try {
      setOpt({ kind: "done", data: await post<OptimizeResponse>("/api/optimize") });
    } catch (e) {
      setOpt({ kind: "error", message: e instanceof Error ? e.message : "Request failed" });
    }
  }

  // The operator marks a worker UNAVAILABLE: that human action is the operational event.
  async function markUnavailable(workerId: string) {
    setPendingWorker(workerId);
    setRep({ kind: "loading" });
    try {
      setRep({ kind: "done", data: await post<ReplanResponse>("/api/replan", { worker_id: workerId }) });
    } catch (e) {
      setPendingWorker(null);
      setRep({ kind: "error", message: e instanceof Error ? e.message : "Request failed" });
    }
  }

  // Baseline optimization (POST /optimize) and, once available, the replan (POST /replan).
  const data = opt.kind === "done" ? opt.data : null;
  const outcome = data ? classify(data) : null;
  const validated = outcome === "validated" && data !== null; // baseline proposal is trusted

  const rd = rep.kind === "done" ? rep.data : null;
  const replanLoading = rep.kind === "loading";
  const replanMode = rd !== null || replanLoading;

  // `active` drives the validation/changes panels: the replan when present, else the baseline.
  const active = rd ?? data;
  const activeOutcome = rd ? classify(rd) : outcome;
  const activeValidated = activeOutcome === "validated" && active !== null;

  const violations = active?.validation?.violations ?? [];
  const prevViolations = rd?.current_plan_validation.violations ?? [];
  const violatedIds = new Set(prevViolations.map((v) => v.task_id).filter((x): x is string => !!x));
  const violatedLabel = `${[...new Set(prevViolations.map((v) => v.constraint))].join("/")} VIOLATION`;

  const hotWindows = active
    ? active.risk.windows.filter((w) => !w.constraints.outdoor_high_intensity_allowed)
    : BASELINE_HOT_WINDOWS;
  const conflictIds = new Set(data ? data.current_plan_conflicts.map((c) => c.task_id) : BASELINE_CONFLICT_IDS);

  const topPlan = rd ? rd.current_plan : replanLoading && data ? data.schedule : data ? data.current_plan : BASELINE_PLAN;
  const order = topPlan.map((p) => p.task_id);

  const changes = activeValidated ? active.changes : [];
  const reassigned = activeValidated ? changes.filter((c) => c.worker_changed).length : null;
  const heatAfter = validated ? (data.validation?.violations ?? []).filter((v) => v.constraint === "H5").length : null;
  const veryHigh = hotWindows.some((w) => w.risk === "VERY_HIGH");
  const hotText = hotWindows.length ? hotWindows.map((w) => `${w.from}–${w.to}`).join(" · ") : "none";
  const workerName = new Map(
    [...(active?.current_plan ?? []), ...(active?.schedule ?? [])].map((p) => [p.worker_id, p.worker_name]),
  );

  // Only statements supported by the validator result / backend changes.
  const checked = new Set(active?.validation?.hard_constraints_checked ?? []);
  const failed = new Set(violations.map((v) => v.constraint));
  const ok = (h: string) => checked.has(h) && !failed.has(h);
  const explanations =
    validated && rep.kind === "idle"
      ? [
          ok("H5") && "High-intensity outdoor work is outside the configured HIGH window",
          ok("H2") && "Required skills preserved",
          ok("H4") && "Task dependencies preserved",
          ok("H7") && "Mandatory deadlines preserved",
          ok("H1") && "Worker availability respected",
          reassigned === 0 && "Worker assignments preserved",
        ].filter((s): s is string => !!s)
      : [];

  // ONE availability state per worker, always backend-owned: the response roster once a plan
  // exists, otherwise the backend metadata fetched on load (static fallback only if unreachable).
  // UNAVAILABLE is shown ONLY once the backend has processed the event; while the request runs
  // the worker reads UPDATING…, and on a technical failure it stays AVAILABLE.
  const roster = active ? active.workers : baseRoster;

  // Site / WorkZone metadata: the response's (authoritative) once a plan exists, else the fetched one.
  const site = active ? active.site : baseSite;
  const taskZones = site
    ? new Map(
        Object.entries(site.task_zones).flatMap(([taskId, zoneId]) => {
          const zone = site.zones.find((z) => z.id === zoneId);
          return zone ? [[taskId, { name: zone.name, environment: zone.environment }] as const] : [];
        }),
      )
    : undefined;
  const coord = (v: number, pos: string, neg: string) => `${Math.abs(v).toFixed(2)}°${v >= 0 ? pos : neg}`;
  // Interactive only after a validated baseline, and only until one event has been applied
  // (accumulating several unavailable workers is out of scope). Re-running OPTIMIZE PLAN or
  // reloading starts a fresh run from the synthetic baseline.
  const canMark = validated && (rep.kind === "idle" || rep.kind === "error");
  const prevValid = rd?.current_plan_validation.valid === true;

  const bottomPlaceholder = replanLoading
    ? "Replanning under the updated operational context…"
    : opt.kind === "loading"
      ? "Optimizing under operational constraints…"
      : activeOutcome === "infeasible" || activeOutcome === "no_solution"
        ? "No feasible plan found"
        : activeOutcome === "validation_failed"
          ? "Candidate rejected by the independent validator — not shown"
          : "Run OPTIMIZE PLAN to generate a validated alternative";

  return (
    <main className="mx-auto flex w-full max-w-[1440px] flex-col gap-4 px-5 pt-5 pb-3">
      <header className="flex items-center justify-between rounded-lg bg-slate-900 px-6 py-3 text-white">
        <div>
          <div className="text-2xl font-extrabold tracking-tight">Operational Adaptation</div>
          <div className="mt-0.5 flex items-center gap-3 text-sm text-slate-300">
            <span>{site ? site.name : "Construction Site — Barcelona"}</span>
            {site && (
              <span className="font-mono text-xs text-slate-400">
                {coord(site.latitude, "N", "S")} {coord(site.longitude, "E", "W")}
              </span>
            )}
            <span className="rounded border border-amber-400/60 px-2 py-0.5 text-xs font-semibold text-amber-300">
              Synthetic operational scenario
            </span>
          </div>
        </div>
        <div className="text-right">
          <div className="text-xs tracking-widest text-slate-400 uppercase">Prototype heat risk indicator</div>
          <div className="text-3xl font-extrabold text-red-400">
            {veryHigh ? "VERY HIGH HEAT" : "HIGH HEAT"} <span className="font-mono">{hotText}</span>
          </div>
          <div className="text-xs text-slate-400">
            Operational demo threshold — outdoor high-intensity work not allowed in this window
          </div>
        </div>
      </header>

      <div className="grid grid-cols-4 gap-4">
        {rd ? (
          <Kpi
            label="Constraint violations"
            value={activeValidated ? `${prevViolations.length} → ${violations.length}` : String(prevViolations.length)}
            sub="previous plan → replan"
            tone={activeValidated && violations.length === 0 ? "green" : "red"}
          />
        ) : (
          <Kpi
            label="Heat conflicts"
            value={validated ? `${conflictIds.size} → ${heatAfter}` : String(conflictIds.size)}
            sub={validated ? "current → optimized" : "current plan"}
            tone={validated && heatAfter === 0 ? "green" : "red"}
          />
        )}
        <Kpi label="Tasks rescheduled" value={activeValidated ? String(changes.length) : "—"} sub="vs plan in force" />
        <Kpi label="Worker reassignments" value={activeValidated ? String(reassigned) : "—"} sub="vs plan in force" />
        <Kpi
          label="Independent validation"
          value={activeValidated ? "VALIDATED" : activeOutcome === "validation_failed" ? "FAILED" : "—"}
          sub={activeValidated ? `H1–H8 checked · ${violations.length} violations` : "runs after optimization"}
          tone={activeValidated ? "green" : activeOutcome === "validation_failed" ? "red" : "slate"}
        />
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)_400px] gap-4">
        <div className="flex flex-col gap-2">
          <Card
            title={replanMode ? "Previous validated plan" : "Current plan"}
            badge={
              rd ? (
                prevValid ? (
                  <Pill tone="green">STILL VALID under updated context</Pill>
                ) : (
                  <Pill tone="red">INVALID · {prevViolations.length} violations under updated context</Pill>
                )
              ) : replanLoading ? (
                <Pill tone="slate">re-checking under updated context…</Pill>
              ) : (
                <Pill tone="red">{conflictIds.size} conflicts</Pill>
              )
            }
          >
            <Timeline
              plan={topPlan}
              order={order}
              conflictIds={rd ? violatedIds : replanLoading ? new Set() : conflictIds}
              conflictLabel={rd ? violatedLabel : undefined}
              taskZones={taskZones}
              hotWindows={hotWindows}
            />
          </Card>

          <Card
            title={replanMode ? "Replanned plan" : "Optimized plan"}
            badge={activeValidated && !replanLoading ? <Pill tone="green">VALIDATED</Pill> : undefined}
          >
            {activeValidated && !replanLoading ? (
              <Timeline
                plan={active.schedule}
                order={order}
                changeLabels={changeLabels(active.changes)}
                taskZones={taskZones}
                hotWindows={hotWindows}
              />
            ) : (
              <div className="flex h-28 items-center justify-center rounded border border-dashed border-slate-300 text-slate-500">
                {bottomPlaceholder}
              </div>
            )}
          </Card>

          <WildfireCard />

          <div className="text-xs text-slate-500">
            {active ? active.data_label : "SYNTHETIC DEMO DATA"}
            {active && ` · risk source: ${active.risk.source}`} · Prototype heat risk engine (demo thresholds),
            not a certified WBGT.
          </div>
        </div>

        <aside className="flex flex-col gap-2">
          <button
            onClick={optimize}
            disabled={opt.kind === "loading" || replanLoading}
            className="rounded-lg bg-red-600 px-6 py-3 text-xl font-extrabold tracking-wide text-white shadow transition hover:bg-red-700 disabled:cursor-wait disabled:bg-slate-400"
          >
            {opt.kind === "loading" ? "Optimizing under operational constraints…" : "OPTIMIZE PLAN"}
          </button>

          <WorkersTable
            roster={roster}
            updatingId={replanLoading ? pendingWorker : null}
            canMark={canMark}
            hint={canMark ? "Operator action → replans" : validated ? "One event per run" : "Optimize first"}
            onSetUnavailable={markUnavailable}
          />

          {(opt.kind === "error" || rep.kind === "error") && (
            <div className="rounded-lg border border-red-300 bg-red-50 p-4 text-sm text-red-800">
              <div className="font-bold">
                {opt.kind === "error" ? "Optimization request failed" : "Replanning request failed"}
              </div>
              <div>{opt.kind === "error" ? opt.message : rep.kind === "error" ? rep.message : ""}. Is the backend running?</div>
              {rep.kind === "error" && (
                <div className="mt-1 text-xs">
                  The event was not applied: the worker stays available and the baseline plan is unchanged.
                </div>
              )}
            </div>
          )}

          {rd && (
            <Card title="Operational event" badge={<Pill tone="slate">SYNTHETIC</Pill>}>
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                <span>{rd.event.worker_name}</span>
                <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-bold text-emerald-800">
                  AVAILABLE
                </span>
                <span aria-hidden>→</span>
                <span className="rounded bg-red-600 px-1.5 py-0.5 text-[10px] font-bold text-white">
                  UNAVAILABLE
                </span>
                <span className="text-xs font-normal text-slate-500">set by operator</span>
              </div>
              {prevValid ? (
                <div className="mt-1 rounded bg-emerald-50 p-1.5 text-xs text-emerald-900">
                  <div className="font-bold">Previous validated plan remains valid under the updated context</div>
                  <div>{rd.event.worker_name} had no assignments in it.</div>
                </div>
              ) : (
                <div className="mt-1 rounded bg-red-50 p-1.5 text-xs text-red-900">
                  <div className="font-bold">
                    Previous validated plan is no longer valid under the updated operational context
                  </div>
                  <ul className="mt-0.5 list-disc pl-4">
                    {prevViolations.map((v, i) => (
                      <li key={i}>
                        [{v.constraint}] {v.message}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </Card>
          )}

          {(activeOutcome === "infeasible" || activeOutcome === "no_solution") && active && (
            <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
              <div className="text-base font-bold">No feasible plan found</div>
              <div>{active.message ?? "No schedule satisfies all hard constraints."}</div>
              <div className="mt-1 text-xs">No alternative has been proposed; hard constraints were not relaxed.</div>
            </div>
          )}

          {activeOutcome === "validation_failed" && active && (
            <div className="rounded-lg border-2 border-red-500 bg-red-50 p-4 text-sm text-red-900">
              <div className="text-base font-bold">Validation failed — plan blocked</div>
              <div>{active.message ?? "The candidate did not pass independent validation."}</div>
              <ul className="mt-2 list-disc pl-5 text-xs">
                {violations.map((v, i) => (
                  <li key={i}>
                    [{v.constraint}] {v.message}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {activeValidated && !replanLoading && (
            <>
              <Card title="Independent validation" badge={<Pill tone="green">PASS</Pill>}>
                <div className="flex flex-wrap gap-1.5">
                  {ALL_CHECKS.map((h) => (
                    <span
                      key={h}
                      className={`rounded px-2 py-0.5 font-mono text-xs font-bold ${
                        ok(h) ? "bg-emerald-100 text-emerald-800" : "bg-slate-100 text-slate-400"
                      }`}
                    >
                      {h}
                    </span>
                  ))}
                </div>
                <div className="mt-1.5 text-xs text-slate-600">
                  {checked.size} checked · {violations.length} violations · separate validator, not the solver
                </div>
              </Card>

              <Card title="What changed">
                <ul className="flex flex-col gap-1 text-xs">
                  {changes.map((c) => (
                    <li key={c.task_id} className="flex items-baseline justify-between gap-2">
                      <span className="font-semibold text-slate-900">{c.task_name}</span>
                      <span className="text-right font-mono text-[11px] text-slate-600">
                        {c.worker_changed
                          ? `${workerName.get(c.old_worker_id) ?? c.old_worker_id} → ${workerName.get(c.new_worker_id) ?? c.new_worker_id} · `
                          : ""}
                        {c.new_start}–{c.new_end}
                        {c.old_start !== c.new_start || c.old_end !== c.new_end
                          ? ` (was ${c.old_start}–${c.old_end})`
                          : ""}
                      </span>
                    </li>
                  ))}
                </ul>
              </Card>

              {explanations.length > 0 && (
                <Card title="Why it holds">
                  <ul className="grid grid-cols-2 gap-x-3 text-xs leading-5 text-slate-700">
                    {explanations.map((s) => (
                      <li key={s}>✓ {s}</li>
                    ))}
                  </ul>
                </Card>
              )}
            </>
          )}

          {!active && opt.kind !== "error" && (
            <Card title="How it works">
              <ol className="list-decimal pl-5 text-sm text-slate-700">
                <li>Backend loads the scenario and heat windows</li>
                <li>OR-Tools proposes an alternative plan</li>
                <li>An independent validator re-checks H1–H8</li>
              </ol>
            </Card>
          )}

        </aside>
      </div>
    </main>
  );
}
