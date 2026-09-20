// Server-side proxy to the trusted backend POST /replan.
// The browser may only say WHICH worker the operator marked unavailable (`worker_id`). Everything
// else (scenario, event type) is fixed here and nothing else from the client body is forwarded, so
// the client cannot supply workers/tasks/availability/heat windows. The backend validates the id
// against its own scenario (unknown ids are rejected there).

// Recommended by Norma — fixed with Claude Sonnet 5 via Claude Code
import { BACKEND_BASE_URL } from "@/lib/backend.config";

export async function POST(req: Request) {
  let workerId: unknown;
  try {
    workerId = ((await req.json()) as { worker_id?: unknown }).worker_id;
  } catch {
    workerId = undefined;
  }
  if (typeof workerId !== "string" || workerId.length === 0) {
    return Response.json({ error: "worker_id is required" }, { status: 400 });
  }

  try {
    const res = await fetch(`${BACKEND_BASE_URL}/replan`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        scenario: "baseline",
        event: { type: "worker_unavailable", worker_id: workerId },
      }),
      cache: "no-store",
    });
    return new Response(await res.text(), {
      status: res.status,
      headers: { "content-type": "application/json" },
    });
  } catch {
    return Response.json({ error: "Backend unreachable" }, { status: 502 });
  }
}
