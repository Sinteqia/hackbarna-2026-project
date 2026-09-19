import type { WorkerStatus } from "@/lib/types";

interface Props {
  roster: WorkerStatus[];
  updatingId: string | null; // worker whose event is being processed by the backend
  canMark: boolean; // a validated baseline exists and no event has been applied yet
  hint: string;
  onSetUnavailable: (workerId: string) => void;
}

// Operational view of the workers available to the planning engine (NOT an HR/CRUD table).
// Status reads UNAVAILABLE only when the backend roster says so; while a request runs the worker
// reads UPDATING…. The action is an operator decision that triggers the real replan.
export default function WorkersTable({ roster, updatingId, canMark, hint, onSetUnavailable }: Props) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white px-3 py-2 shadow-sm">
      <div className="mb-0.5 flex items-center justify-between">
        <h2 className="text-xs font-bold tracking-widest text-slate-500 uppercase">Worker availability</h2>
        <span className={`text-[11px] font-semibold ${canMark ? "text-red-700" : "text-slate-500"}`}>{hint}</span>
      </div>
      <table className="w-full text-left">
        <thead>
          <tr className="text-[10px] font-bold tracking-widest text-slate-400 uppercase">
            <th className="py-0.5 font-bold">Worker</th>
            <th className="py-0.5 font-bold">Skill</th>
            <th className="py-0.5 font-bold">Status</th>
            <th className="py-0.5 text-right font-bold">Action</th>
          </tr>
        </thead>
        <tbody>
          {roster.map((w) => {
            const off = !w.available;
            const updating = updatingId === w.id;
            const enabled = canMark && !off && updatingId === null;
            return (
              <tr key={w.id} className="border-t border-slate-100">
                <td className="py-0.5 pr-2 text-sm font-semibold text-slate-900">{w.name}</td>
                <td className="py-0.5 pr-2 font-mono text-[11px] text-slate-600">{w.skills.join(", ")}</td>
                <td className="py-0.5 pr-2">
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] font-bold tracking-wide ${
                      off
                        ? "bg-red-600 text-white"
                        : updating
                          ? "bg-amber-500 text-white"
                          : "bg-emerald-100 text-emerald-800"
                    }`}
                  >
                    {off ? "UNAVAILABLE" : updating ? "UPDATING…" : "AVAILABLE"}
                  </span>
                </td>
                <td className="py-0.5 text-right">
                  {off ? (
                    <span className="text-[10px] font-semibold text-slate-400">SET BY OPERATOR</span>
                  ) : (
                    <button
                      onClick={() => onSetUnavailable(w.id)}
                      disabled={!enabled}
                      aria-label={`Set ${w.name} unavailable`}
                      title={
                        enabled
                          ? `Mark ${w.name} unavailable (operator action, triggers replanning)`
                          : updating
                            ? "Applying event…"
                            : canMark
                              ? "Wait for the current request to finish"
                              : hint
                      }
                      className={`rounded border px-2 py-0.5 text-[10px] font-bold tracking-wide transition ${
                        enabled
                          ? "border-red-500 bg-white text-red-700 hover:bg-red-50"
                          : "cursor-not-allowed border-slate-200 bg-slate-100 text-slate-400"
                      }`}
                    >
                      SET UNAVAILABLE
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
