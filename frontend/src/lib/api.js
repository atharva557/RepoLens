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

// Session-scoped GET cache so page-to-page navigation feels instant instead
// of refetching everything on every mount. Opt-in per call via { ttl } (ms);
// every successful GET reprimes its entry regardless, and any successful
// POST/PUT clears the whole cache (triggers change server state through
// background jobs, so everything read before them is suspect). /jobs polling
// is never cached — job status must always be live.
const _cache = new Map();

export function invalidateCache(prefix = "") {
  if (!prefix) {
    _cache.clear();
    return;
  }
  for (const key of _cache.keys()) {
    if (key.startsWith(prefix)) _cache.delete(key);
  }
}

/**
 * Error carrying the HTTP status alongside the server's `detail` message.
 *
 * The status MUST survive: "not analyzed yet" (404) is normal control flow
 * that pages turn into a POST + job poll, and it is only distinguishable from
 * a real failure by the code. Throwing a bare Error forced callers to sniff
 * the message for "404" — but the message is FastAPI's `detail` string, which
 * never contains the number, so those branches silently never fired.
 * Check `err.status === 404`, never `err.message.includes("404")`.
 */
export class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

/** True when a failure means "this resource hasn't been generated yet". */
export function isNotFound(err) {
  return err instanceof ApiError && err.status === 404;
}

async function _parse(res) {
  const body = await res.json().catch(() => null);
  if (res.ok) return body;
  if (res.status === 502) {
    throw new ApiError(
      "Backend server is currently unavailable (502 Bad Gateway). Please try again later.",
      502, body);
  }
  throw new ApiError((body && body.detail) || `${res.status} ${res.statusText}`,
                     res.status, body);
}

export async function getJSON(path, { ttl } = {}) {
  if (ttl) {
    const hit = _cache.get(path);
    if (hit && Date.now() - hit.at < ttl) return hit.data;
  }
  const res = await fetch(API_BASE + path);
  const body = await _parse(res);
  if (!path.startsWith("/jobs")) _cache.set(path, { data: body, at: Date.now() });
  return body;
}

// custom header = CSRF proof on every mutating call (cross-site forms can't
// set custom headers); the server requires it in multiuser mode
const CSRF_HEADERS = { "X-GitPulse-Client": "dashboard" };

export async function postJSON(path, payload) {
  const res = await fetch(API_BASE + path, {
    method: "POST",
    headers: payload ? { "Content-Type": "application/json", ...CSRF_HEADERS } : CSRF_HEADERS,
    body: payload ? JSON.stringify(payload) : undefined,
  });
  const body = await _parse(res);
  invalidateCache();
  return body;
}

export async function putJSON(path, payload) {
  const res = await fetch(API_BASE + path, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...CSRF_HEADERS },
    body: JSON.stringify(payload || {}),
  });
  const body = await _parse(res);
  invalidateCache();
  return body;
}
