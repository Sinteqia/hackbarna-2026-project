// Server-side proxy to the trusted backend POST /wildfire/optimize.
// The backend queries Deepfire and holds the credentials; the browser sends no body and never
// sees secrets. The scenario is fixed here, so the client cannot supply signals or rules.

const BACKEND_BASE_URL = process.env.BACKEND_BASE_URL ?? "http://127.0.0.1:8000";

export async function POST() {
  try {
    const res = await fetch(`${BACKEND_BASE_URL}/wildfire/optimize`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ scenario: "baseline" }),
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
