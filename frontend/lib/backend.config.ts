// Backend proxy target for the server-side /api routes.
// Set BACKEND_BASE_URL to override; the fallback is the local development backend.
export const BACKEND_BASE_URL = process.env.BACKEND_BASE_URL ?? "http://127.0.0.1:8000";
