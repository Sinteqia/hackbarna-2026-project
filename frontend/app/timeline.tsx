import type { HeatWindow, ScheduledTask } from "@/lib/types";

const toMin = (t: string) => {
  const [h, m] = t.split(":").map(Number);
  return h * 60 + m;
};

interface Props {
  plan: ScheduledTask[];
  order: string[]; // task ids, so both timelines keep the same row order
  conflictIds?: Set<string>;
  conflictLabel?: string; // tag for rows in conflictIds (default H5 CONFLICT)
  changeLabels?: Map<string, string>; // task_id -> tag; when provided, other rows read UNCHANGED
  taskZones?: Map<string, { name: string; environment: string }>; // task_id -> WorkZone (backend)
  hotWindows: HeatWindow[];
}

const ENV_STYLE: Record<string, string> = {
  OUTDOOR: "bg-amber-100 text-amber-800",
  PARTIAL: "bg-sky-100 text-sky-800",
  INDOOR: "bg-slate-200 text-slate-700",
};

export default function Timeline({
  plan,
  order,
  conflictIds,
  conflictLabel = "H5 CONFLICT",
  changeLabels,
  taskZones,
  hotWindows,
}: Props) {
  const start = 7 * 60;
  const end = Math.max(17 * 60, Math.ceil(Math.max(...plan.map((p) => toMin(p.end))) / 60) * 60);
  const pct = (m: number) => `${(Math.min(Math.max(m, start), end) - start) / (end - start) * 100}%`;
  const hours = Array.from({ length: (end - start) / 60 + 1 }, (_, i) => start / 60 + i);
  const byId = new Map(plan.map((p) => [p.task_id, p]));
  const rows = order.map((id) => byId.get(id)).filter((p): p is ScheduledTask => !!p);

  const shade = hotWindows.map((w) => (
    <div
      key={`${w.from}-${w.to}`}
      className="absolute inset-y-0 border-x border-red-300 bg-red-500/10"
      style={{ left: pct(toMin(w.from)), width: `calc(${pct(toMin(w.to))} - ${pct(toMin(w.from))})` }}
    />
  ));

  return (
    <div className="text-sm">
      <div className="grid grid-cols-[290px_minmax(0,1fr)]">
        <div />
        <div className="relative h-6">
          {hours.map((h) => (
            <span
              key={h}
              className="absolute -translate-x-1/2 font-mono text-[11px] text-slate-500"
              style={{ left: pct(h * 60) }}
            >
              {String(h).padStart(2, "0")}:00
            </span>
          ))}
        </div>
      </div>
      {rows.map((p) => {
        const conflict = conflictIds?.has(p.task_id);
        const changed = changeLabels?.has(p.task_id);
        const bar = conflict
          ? "bg-red-600 ring-2 ring-red-300"
          : changed
            ? "bg-sky-600"
            : "bg-slate-600";
        return (
          <div key={p.task_id} className="grid grid-cols-[290px_minmax(0,1fr)] border-t border-slate-200">
            <div className="flex items-center justify-between gap-2 py-0.5 pr-3">
              <div className="min-w-0">
                <div className="font-semibold text-slate-900">{p.task_name}</div>
                <div className="flex items-center gap-1 text-[11px] text-slate-500">
                  <span className="truncate">
                    {p.worker_name}
                    {taskZones?.get(p.task_id) ? ` · ${taskZones.get(p.task_id)?.name}` : ""}
                  </span>
                  {taskZones?.get(p.task_id) && (
                    <span
                      className={`shrink-0 rounded px-1 text-[9px] font-bold ${
                        ENV_STYLE[taskZones.get(p.task_id)!.environment] ?? ENV_STYLE.INDOOR
                      }`}
                    >
                      {taskZones.get(p.task_id)!.environment}
                    </span>
                  )}
                </div>
              </div>
              {conflict && (
                <span className="shrink-0 rounded bg-red-100 px-1.5 py-0.5 text-[10px] font-bold text-red-700">
                  {conflictLabel}
                </span>
              )}
              {!conflict && changeLabels && (
                <span
                  className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold ${
                    changed ? "bg-sky-100 text-sky-700" : "bg-slate-100 text-slate-500"
                  }`}
                >
                  {changed ? changeLabels.get(p.task_id) : "UNCHANGED"}
                </span>
              )}
            </div>
            <div className="relative h-9">
              {hours.map((h) => (
                <div key={h} className="absolute inset-y-0 w-px bg-slate-100" style={{ left: pct(h * 60) }} />
              ))}
              {shade}
              <div
                className={`absolute inset-y-1 flex items-center justify-center overflow-hidden rounded px-1 font-mono text-[11px] font-semibold whitespace-nowrap text-white ${bar}`}
                style={{
                  left: pct(toMin(p.start)),
                  width: `calc(${pct(toMin(p.end))} - ${pct(toMin(p.start))})`,
                }}
              >
                {p.start}–{p.end}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
