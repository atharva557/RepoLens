# 05 — Client library (`src/lib/api.js`)

All HTTP communication with the FastAPI backend goes through this single
module. No page or component calls `fetch` directly.

---

## Base URL

```js
export const API_BASE = "/api";
```

`/api` is proxied to `http://127.0.0.1:8000` by `vite.config.js` in
development. In a production deployment the same path must be reverse-proxied
to the backend. No page ever constructs an absolute URL to the backend.

---

## `ApiError`

```js
export class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.name = "ApiError";
    this.status = status;   // HTTP status code (number)
    this.body = body;       // parsed JSON body or null
  }
}
```

Every non-2xx response throws an `ApiError`. The critical design decision is
that **the HTTP status code is preserved on the error object**. This matters
because:

- `404` means "not analyzed yet" and is **normal control flow** — pages handle
  it by triggering a POST + poll, not by showing an error screen.
- The `message` on an `ApiError` is the FastAPI `detail` string, which is a
  human-readable sentence. It never contains the numeric status code.
- Before this class existed, code sniffed `err.message.includes("404")` to
  detect not-found — this silently never matched, causing pages to show
  error screens on valid first visits.

The correct pattern everywhere:

```js
// correct
catch (e) {
  if (isNotFound(e)) { /* trigger analysis */ }
  else { setError(e.message); }
}

// wrong — the message is FastAPI's detail string, never "404"
catch (e) {
  if (e.message.includes("404")) { ... }
}
```

### `isNotFound(err)`

```js
export function isNotFound(err) {
  return err instanceof ApiError && err.status === 404;
}
```

A convenience predicate used in every page that handles the "not yet analyzed"
state (`BugHotspots`, `DeveloperProfile`, `PRReview`, `Dashboard`).

### 502 handling

```js
if (res.status === 502) {
  throw new ApiError(
    "Backend server is currently unavailable (502 Bad Gateway). Please try again later.",
    502, body);
}
```

A 502 from a reverse proxy (backend down) gets a user-friendly message rather
than a raw `502 Bad Gateway` error string.

---

## GET cache

```js
const _cache = new Map();  // path → { data, at }
```

A session-scoped in-memory cache that makes page-to-page navigation feel
instant. It is **opt-in per call** via a `ttl` option:

```js
getJSON("/repos", { ttl: 30000 })   // cache for 30 seconds
getJSON("/repos")                   // bypass cache, always fresh
```

Rules:
- Every successful GET **reprimes** its cache entry regardless of whether it
  was a cache hit — the TTL clock resets on any live response.
- `/jobs/...` polling calls are **never cached** — job status must always be
  live.
- Any successful `postJSON` or `putJSON` call clears the **entire cache**
  (`invalidateCache()`). A trigger POST changes server state through a
  background job, so any read cached before it is now stale.
- `invalidateCache(prefix)` clears only entries whose key starts with `prefix`
  for surgical invalidation (not currently used by pages but exported for
  future use).

```js
export function invalidateCache(prefix = "") {
  if (!prefix) { _cache.clear(); return; }
  for (const key of _cache.keys()) {
    if (key.startsWith(prefix)) _cache.delete(key);
  }
}
```

---

## `getJSON(path, { ttl } = {})`

```js
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
```

Steps:
1. Check the cache if `ttl` is given — return immediately on a hit.
2. `fetch(API_BASE + path)` — no headers needed for GETs.
3. `_parse(res)` — parses the JSON body and throws `ApiError` on non-2xx.
4. Cache the result (unless it's a `/jobs/` path).
5. Return the parsed body.

---

## `postJSON(path, payload)`

```js
export async function postJSON(path, payload) {
  const res = await fetch(API_BASE + path, {
    method: "POST",
    headers: payload
      ? { "Content-Type": "application/json", ...CSRF_HEADERS }
      : CSRF_HEADERS,
    body: payload ? JSON.stringify(payload) : undefined,
  });
  const body = await _parse(res);
  invalidateCache();
  return body;
}
```

- If `payload` is `undefined` or `null`, no `Content-Type` header is sent and
  no body is attached — for trigger endpoints that take no request body
  (e.g. `POST /repos/{key}/insights`).
- On success, the **entire GET cache is cleared** so stale reads are not served
  after a state-changing call.

---

## `putJSON(path, payload)`

```js
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
```

Currently used only by `SettingsDrawer` for `PUT /config`. Same cache-clear
behavior as `postJSON`.

---

## CSRF header

```js
const CSRF_HEADERS = { "X-GitPulse-Client": "dashboard" };
```

This custom header is added to every `postJSON` and `putJSON` call. Cross-site
form submissions cannot set custom headers, so its presence proves the request
originated from JavaScript running in the dashboard — not a forged form on
another site. The FastAPI backend **requires** this header on all mutating
routes in multiuser mode and ignores it harmlessly in single-user mode.

---

## `_parse(res)` — internal response parser

```js
async function _parse(res) {
  const body = await res.json().catch(() => null);
  if (res.ok) return body;
  if (res.status === 502) {
    throw new ApiError("Backend server is currently unavailable...", 502, body);
  }
  throw new ApiError(
    (body && body.detail) || `${res.status} ${res.statusText}`,
    res.status,
    body
  );
}
```

- JSON parsing failures (non-JSON body) produce `null` rather than crashing —
  the `ApiError` message then falls back to `"<status> <statusText>"`.
- The `detail` field of FastAPI error responses is used as the human-readable
  message when available.

---

## Summary of the full contract every page follows

| Scenario | HTTP status | What pages do |
|---|---|---|
| Successful read | 2xx | Render the data |
| Not analyzed yet | 404 | `isNotFound(e)` → trigger POST + poll (or show a CTA) |
| Backend down | 502 | Surface the user-friendly message |
| Auth required (multiuser) | 401 | Surface error (the Gate should have caught this) |
| Forbidden | 403 | Surface error (e.g. `PUT /config` in multiuser) |
| Any other error | 4xx/5xx | `setError(e.message)` → error card with Retry |
| Trigger accepted | 202 | `{ job_id, status_url }` → poll `GET /jobs/{id}` |
| Trigger done | job.status == "done" | Re-fetch the read endpoint |
| Trigger failed | job.status == "failed" | `setError(job.error)` |
