"use client";

import { useState } from "react";
import { BASELINE_CONFLICT_IDS, BASELINE_HOT_WINDOWS, BASELINE_PLAN } from "@/lib/baseline";
import { classify } from "@/lib/optimize";
import type { OptimizeResponse } from "@/lib/types";
import Timeline from "./timeline";

type Phase =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "done"; data: OptimizeResponse };

const ALL_CHECKS = ["H1", "H2", "H3", "H4", "H5", "H6", "H7", "H8"];

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
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });

  async function optimize() {
    setPhase({ kind: "loading" });
    try {
      const res = await fetch("/api/optimize", { method: "POST" });
      if (!res.ok) throw new Error(`Backend responded ${res.status}`);
      setPhase({ kind: "done", data: (await res.json()) as OptimizeResponse });
    } catch (e) {
      setPhase({ kind: "error", message: e instanceof Error ? e.message : "Request failed" });
    }
  }

  const data = phase.kind === "done" ? phase.data : null;
  const outcome = data ? classify(data) : null;
  const validated = outcome === "validated" && data !== null;

  const currentPlan = data ? data.current_plan : BASELINE_PLAN;
  const conflictIds = new Set(data ? data.current_plan_conflicts.map((c) => c.task_id) : BASELINE_CONFLICT_IDS);
  const hotWindows = data
    ? data.risk.windows.filter((w) => !w.constraints.outdoor_high_intensity_allowed)
    : BASELINE_HOT_WINDOWS;
  const order = currentPlan.map((p) => p.task_id);
  const changedIds = new Set(validated ? data.changes.map((c) => c.task_id) : []);

  const violations = data?.validation?.violations ?? [];
  const heatAfter = validated ? violations.filter((v) => v.constraint === "H5").length : null;
  const reassigned = validated ? data.changes.filter((c) => c.worker_changed).length : null;
  const veryHigh = hotWindows.some((w) => w.risk === "VERY_HIGH");
  const hotText = hotWindows.length ? hotWindows.map((w) => `${w.from}–${w.to}`).join(" · ") : "none";

  // Only statements supported by the validator result / backend changes.
  const checked = new Set(data?.validation?.hard_constraints_checked ?? []);
  const failed = new Set(violations.map((v) => v.constraint));
  const ok = (h: string) => checked.has(h) && !failed.has(h);
  const explanations = validated
    ? [
        ok("H5") && "High-intensity outdoor work is outside the configured HIGH window",
        ok("H2") && "Required skills preserved",
        ok("H4") && "Task dependencies preserved",
        ok("H7") && "Mandatory deadlines preserved",
        ok("H1") && "Worker availability respected",
        reassigned === 0 && "Worker assignments preserved",
      ].filter((s): s is string => !!s)
    : [];

  return (
    <main className="mx-auto flex w-full max-w-[1440px] flex-col gap-4 p-5">
      <header className="flex items-center justify-between rounded-lg bg-slate-900 px-6 py-3 text-white">
        <div>
          <div className="text-2xl font-extrabold tracking-tight">Operational Adaptation</div>
          <div className="mt-0.5 flex items-center gap-3 text-sm text-slate-300">
            <span>Construction site · Barcelona</span>
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
        <Kpi
          label="Heat conflicts"
          value={validated ? `${conflictIds.size} → ${heatAfter}` : String(conflictIds.size)}
          sub={validated ? "current → optimized" : "current plan"}
          tone={validated && heatAfter === 0 ? "green" : "red"}
        />
        <Kpi label="Tasks rescheduled" value={validated ? String(data.changes.length) : "—"} sub="vs current plan" />
        <Kpi label="Worker reassignments" value={validated ? String(reassigned) : "—"} sub="vs current plan" />
        <Kpi
          label="Independent validation"
          value={validated ? "VALIDATED" : outcome === "validation_failed" ? "FAILED" : "—"}
          sub={validated ? `H1–H8 checked · ${violations.length} violations` : "runs after optimization"}
          tone={validated ? "green" : outcome === "validation_failed" ? "red" : "slate"}
        />
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)_360px] gap-4">
        <div className="flex flex-col gap-4">
          <Card
            title="Current plan"
            badge={<Pill tone="red">{conflictIds.size} conflicts</Pill>}
          >
            <Timeline plan={currentPlan} order={order} conflictIds={conflictIds} hotWindows={hotWindows} />
          </Card>

          <Card
            title="Optimized plan"
            badge={validated ? <Pill tone="green">VALIDATED</Pill> : undefined}
          >
            {validated ? (
              <Timeline plan={data.schedule} order={order} changedIds={changedIds} hotWindows={hotWindows} />
            ) : (
              <div className="flex h-44 items-center justify-center rounded border border-dashed border-slate-300 text-slate-500">
                {phase.kind === "loading"
                  ? "Optimizing under operational constraints…"
                  : outcome === "infeasible" || outcome === "no_solution"
                    ? "No feasible plan found"
                    : outcome === "validation_failed"
                      ? "Candidate rejected by the independent validator — not shown"
                      : "Run OPTIMIZE PLAN to generate a validated alternative"}
              </div>
            )}
          </Card>
        </div>

        <aside className="flex flex-col gap-3">
          <button
            onClick={optimize}
            disabled={phase.kind === "loading"}
            className="rounded-lg bg-red-600 px-6 py-4 text-xl font-extrabold tracking-wide text-white shadow transition hover:bg-red-700 disabled:cursor-wait disabled:bg-slate-400"
          >
            {phase.kind === "loading" ? "Optimizing under operational constraints…" : "OPTIMIZE PLAN"}
          </button>

          {phase.kind === "error" && (
            <div className="rounded-lg border border-red-300 bg-red-50 p-4 text-sm text-red-800">
              <div className="font-bold">Optimization request failed</div>
              <div>{phase.message}. Is the backend running?</div>
            </div>
          )}

          {(outcome === "infeasible" || outcome === "no_solution") && data && (
            <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
              <div className="text-base font-bold">No feasible plan found</div>
              <div>{data.message ?? "No schedule satisfies all hard constraints."}</div>
              <div className="mt-1 text-xs">No alternative has been proposed; hard constraints were not relaxed.</div>
            </div>
          )}

          {outcome === "validation_failed" && data && (
            <div className="rounded-lg border-2 border-red-500 bg-red-50 p-4 text-sm text-red-900">
              <div className="text-base font-bold">Validation failed — plan blocked</div>
              <div>{data.message ?? "The candidate did not pass independent validation."}</div>
              <ul className="mt-2 list-disc pl-5 text-xs">
                {violations.map((v, i) => (
                  <li key={i}>
                    [{v.constraint}] {v.message}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {validated && (
            <>
              <Card title="Independent validation" badge={<Pill tone="green">PASS</Pill>}>
                <div className="flex flex-wrap gap-1.5">
                  {ALL_CHECKS.map((h) => (
                    <span
                      key={h}
                      className={`rounded px-2 py-1 font-mono text-xs font-bold ${
                        ok(h) ? "bg-emerald-100 text-emerald-800" : "bg-slate-100 text-slate-400"
                      }`}
                    >
                      {h}
                    </span>
                  ))}
                </div>
                <div className="mt-2 text-sm text-slate-700">
                  {checked.size} hard constraints checked · {violations.length} violations
                </div>
                <div className="text-xs text-slate-500">Recomputed by a separate validator, not by the solver.</div>
              </Card>

              <Card title="What changed">
                <ul className="flex flex-col gap-1 text-sm">
                  {data.changes.map((c) => (
                    <li key={c.task_id}>
                      <span className="font-semibold">{c.task_name}</span>
                      <div className="font-mono text-xs text-slate-600">
                        {c.old_start}–{c.old_end} → {c.new_start}–{c.new_end}
                        {c.worker_changed ? " · worker changed" : ""}
                      </div>
                    </li>
                  ))}
                </ul>
              </Card>

              <Card title="Why it holds">
                <ul className="flex flex-col text-[13px] leading-5 text-slate-700">
                  {explanations.map((s) => (
                    <li key={s}>✓ {s}</li>
                  ))}
                </ul>
              </Card>
            </>
          )}

          {!data && phase.kind !== "error" && (
            <Card title="How it works">
              <ol className="list-decimal pl-5 text-sm text-slate-700">
                <li>Backend loads the scenario and heat windows</li>
                <li>OR-Tools proposes an alternative plan</li>
                <li>An independent validator re-checks H1–H8</li>
              </ol>
            </Card>
          )}

          <div className="text-xs text-slate-500">
            {data ? data.data_label : "SYNTHETIC DEMO DATA"}
            {data && ` · risk source: ${data.risk.source}`} · Prototype heat risk engine (demo thresholds),
            not a certified WBGT.
          </div>
        </aside>
      </div>
    </main>
  );
}
