// Server-side proxy to the backend's SAFE Site/WorkZone metadata for the baseline scenario.
// Read-only; the scenario is fixed here.

const BACKEND_BASE_URL = process.env.BACKEND_BASE_URL ?? "http://127.0.0.1:8000";

export async function GET() {
  try {
    const res = await fetch(`${BACKEND_BASE_URL}/scenarios/baseline/site`, { cache: "no-store" });
    return new Response(await res.text(), {
      status: res.status,
      headers: { "content-type": "application/json" },
    });
  } catch {
    return Response.json({ error: "Backend unreachable" }, { status: 502 });
  }
}
