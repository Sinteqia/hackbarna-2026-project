"use client";

import { useState } from "react";
import type { WildfireResponse } from "@/lib/types";

type Phase =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "done"; data: WildfireResponse };

// Backend status codes -> plain wording. None of them means "low risk" or "safe".
const SIGNAL_LABEL: Record<string, string> = {
  APPLICABLE_SIGNAL: "Relevant signal detected",
  NO_APPLICABLE_SIGNAL: "No applicable signal (not a safety statement)",
  STALE_SIGNAL: "Signal too old to assess",
  UNAVAILABLE: "Signal unavailable",
};

const utc = (iso: string) => `${iso.slice(0, 16).replace("T", " ")} UTC`;

function Pill({ tone, children }: { tone: "red" | "green" | "amber" | "slate"; children: React.ReactNode }) {
  const tones = {
    red: "bg-red-100 text-red-700",
    green: "bg-emerald-100 text-emerald-800",
    amber: "bg-amber-100 text-amber-800",
    slate: "bg-slate-100 text-slate-600",
  };
  return <span className={`rounded px-2 py-0.5 text-xs font-bold ${tones[tone]}`}>{children}</span>;
}

// Result of the wildfire optimization, exactly as the backend reports it. A plan is never shown:
// only FEASIBLE + validated is called feasible, and INFEASIBLE is a legitimate operational outcome.
function outcome(d: WildfireResponse): { pill: React.ReactNode; text: string } {
  if (d.status === "INFEASIBLE") {
    return {
      pill: <Pill tone="amber">INFEASIBLE</Pill>,
      text: "No feasible schedule satisfies the configured wildfire restriction.",
    };
  }
  if (d.status === "FEASIBLE" && d.validated && d.validation?.valid === true) {
    return {
      pill: <Pill tone="green">FEASIBLE</Pill>,
      text: "A plan was found and independently validated (no wildfire restriction applied).",
    };
  }
  if (d.status === "SIGNAL_STALE" || d.status === "SIGNAL_UNAVAILABLE") {
    return {
      pill: <Pill tone="slate">{d.status === "SIGNAL_STALE" ? "SIGNAL STALE" : "SIGNAL UNAVAILABLE"}</Pill>,
      text: `${d.message ?? "Wildfire signal could not be assessed."} Not treated as low risk.`,
    };
  }
  return {
    pill: <Pill tone="red">BLOCKED</Pill>,
    text: d.message ?? "The result did not pass independent validation and is not shown.",
  };
}

export default function WildfireCard() {
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });

  async function check() {
    setPhase({ kind: "loading" });
    try {
      const res = await fetch("/api/wildfire", { method: "POST" });
      if (!res.ok) throw new Error(`Backend responded ${res.status}`);
      setPhase({ kind: "done", data: (await res.json()) as WildfireResponse });
    } catch (e) {
      setPhase({ kind: "error", message: e instanceof Error ? e.message : "Request failed" });
    }
  }

  const d = phase.kind === "done" ? phase.data : null;
  const w = d?.wildfire;
  const zoneNames = d && w ? d.site.zones.filter((z) => w.affected_zone_ids.includes(z.id)).map((z) => z.name) : [];
  const taskNames = d && w ? d.current_plan.filter((p) => w.affected_task_ids.includes(p.task_id)).map((p) => p.task_name) : [];
  const h9Violations = d ? d.current_plan_validation.violations.filter((v) => v.constraint === "H9").length : 0;
  const result = d ? outcome(d) : null;

  return (
    <section className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-baseline gap-2">
          <h2 className="text-xs font-bold tracking-widest text-slate-500 uppercase">Wildfire operational risk</h2>
          <span className="text-[11px] text-slate-500">Deepfire satellite hotspots · configured operational rule</span>
        </div>
        <div className="flex items-center gap-2">
          {w && <Pill tone={w.status === "APPLICABLE_SIGNAL" ? "red" : "slate"}>{w.status.replaceAll("_", " ")}</Pill>}
          {result?.pill}
          <button
            onClick={check}
            disabled={phase.kind === "loading"}
            className="rounded border border-red-500 bg-white px-3 py-0.5 text-[11px] font-bold tracking-wide text-red-700 transition hover:bg-red-50 disabled:cursor-wait disabled:border-slate-300 disabled:text-slate-400"
          >
            {phase.kind === "loading" ? "CHECKING DEEPFIRE…" : d ? "RE-CHECK WILDFIRE SIGNAL" : "CHECK WILDFIRE SIGNAL"}
          </button>
        </div>
      </div>

      {phase.kind === "error" && (
        <div className="mt-1 text-xs text-red-800">
          Wildfire request failed: {phase.message}. Not treated as low risk.
        </div>
      )}

      {d && w && result && (
        <>
          <div className="mt-1 text-xs leading-[18px] text-slate-700">
            <div>
              <span className="font-semibold">Signal:</span> {SIGNAL_LABEL[w.status] ?? w.status}
              {w.nearest_km !== null && <> · nearest hotspot <b>{w.nearest_km} km</b></>}
              {" "}· {w.hotspots_in_radius} active within {w.radius_km} km
              {w.latest_observed_at && <> · last observed {utc(w.latest_observed_at)}</>} (window {w.fresh_hours} h)
              {w.error && <> · detail: {w.error}</>}
            </div>
            {(zoneNames.length > 0 || taskNames.length > 0) && (
              <div>
                <span className="font-semibold">Affected:</span> {zoneNames.join(", ")} — {taskNames.join(", ")}
              </div>
            )}
            {w.restriction && (
              <div>
                <span className="font-semibold">H9 (configured operational rule):</span> OUTDOOR work restricted{" "}
                {w.restriction.from}–{w.restriction.to} · current plan: {h9Violations} H9 violations
              </div>
            )}
            <div className="font-semibold text-slate-900">Result: {result.text}</div>
          </div>
          <div className="mt-1 text-[10.5px] leading-[14px] text-slate-500">
            Deepfire provides the spatial signal; Operational Adaptation applies a configured operational rule.{" "}
            {w.parameters_note}
          </div>
        </>
      )}
    </section>
  );
}
