/**
 * RepoLens API — conventions shared by every page.
 *
 * Base URL: http://127.0.0.1:8000   (uvicorn api.main:app, run from test_1/)
 * CORS is already enabled server-side (GITPULSE_CORS_ORIGINS=*), so the Vite
 * dev server can call it directly. Interactive docs live at /docs.
 *
 * Two kinds of endpoints:
 *
 * 1. READS  — plain GET, return JSON immediately.
 *    404 means "not analyzed yet"; its `detail` string says which POST to run.
 *
 * 2. TRIGGERS — POST, return 202 with { job_id, status, status_url }.
 *    Poll GET /jobs/{job_id} (~every 1-2s) until status is "done" or "failed":
 *      { id, kind, params, status: pending|running|done|failed,
 *        created_at, finished_at, result, error }
 *    then re-fetch the read endpoint. There is no cancel endpoint.
 *
 * Health/diagnostics for a settings/status page:
 *    GET /health  — { status, store, version }
 *    GET /test    — one-call self-test: store round-trip, LLM availability,
 *                   similarity backend, github_token / webhook config
 *    GET /config  — resolved settings (secrets masked)
 *
 * Repo keys in URLs may contain a slash ("owner/repo") — the API routes use
 * path-typed params, so fetch(`/repos/${key}/hotspots`) works without encoding.
 */

// "/api" is proxied to http://127.0.0.1:8000 by vite.config.js
export const API_BASE = "/api";

export async function getJSON(path) {
  const res = await fetch(API_BASE + path);
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 502) {
      throw new Error("Backend server is currently unavailable (502 Bad Gateway). Please try again later.");
    }
    throw new Error((body && body.detail) || `${res.status} ${res.statusText}`);
  }
  return body;
}

export async function postJSON(path, payload) {
  const res = await fetch(API_BASE + path, {
    method: "POST",
    headers: payload ? { "Content-Type": "application/json" } : {},
    body: payload ? JSON.stringify(payload) : undefined,
  });
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 502) {
      throw new Error("Backend server is currently unavailable (502 Bad Gateway). Please try again later.");
    }
    throw new Error((body && body.detail) || `${res.status} ${res.statusText}`);
  }
  return body;
}
