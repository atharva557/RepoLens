# 09 — Frontend (React dashboard)

`frontend/` is a Vite + React 19 single-page app styled with Tailwind CSS 4,
charting with Recharts, routed with react-router 7. It is a pure client of the
FastAPI backend — no server-side logic of its own.

```bash
cd frontend
npm install
npm run dev        # Vite dev server (default http://localhost:5173)
```

The API must be running (`python -m uvicorn api.main:app` from `test_1/`).
All requests go to `/api/...`, which `vite.config.js` proxies to
`http://127.0.0.1:8000` — so there are no hardcoded backend URLs in
components, and CORS is a non-issue in dev (the server also enables CORS via
`GITPULSE_CORS_ORIGINS` for non-proxied setups).

## Pages (`src/pages/`)

| Route | Page | Backed by |
|---|---|---|
| `/` | `Home` | `GET /repos`, `GET /profiles` — what's already analyzed, most-recent first; entry point for new analyses |
| `/loading` | `Loading` | `GET /jobs/{id}` polling while a triggered analysis runs; renders the job's `progress` phases |
| `/dashboard` | `Dashboard` | `GET /repos/{key}/activity`, `/meta`, `/insights`, `/commit-quality`, `/pr-reviews` — repo overview: contributors, heatmap, health score, AI insights, language inventory, reviewed-PR card |
| `/hotspots` | `BugHotspots` | `GET /repos/{key}/hotspots` — ranked hotspot table with reasons |
| `/profile` | `DeveloperProfile` | `GET /profiles/{username}` — type distribution, languages, commit health, heatmap, AI summary. Without `?user=` it renders a username search (accepting `octocat`, `@octocat`, a profile URL or `owner/repo`) plus chips for already-built profiles from `GET /profiles` |
| `/pr-review` | `PRReview` | `GET/POST /repos/{o}/{r}/pr-reviews/{n}` + `GET /repos/{key}/pr-reviews` — accepts `owner/repo#N` or a PR URL, triggers a review, shows the risk report; lists the repo's reviewed PRs |
| `/status` | `Status` | `GET /test`, `GET /config` — live self-test (store, LLM, similarity backend, token/webhook) and the resolved, secret-masked config |

`Login` has no route of its own: in multiuser mode `App.jsx` renders it
*instead of* the router for an anonymous visitor, on every URL, so the
originally requested URL still resolves once they sign in.

## Components (`src/components/`)

- **`Navbar`** — fixed top bar; context-aware links that carry the current
  `repo`/`user` as query string, and the button that opens the settings drawer.
- **`SettingsDrawer`** — right-hand drawer (from the design prototype) that
  slides in over an overlay, applies theme/accent changes live, and persists
  through `ThemeContext`. Rendered through a `createPortal` because the navbar's
  `backdrop-blur` would otherwise clip a fixed child. Replaced the older
  `GlobalSettingsModal`.
- **`Card`** — the shared surface primitive (rounded container, hover border,
  card glow) every page composes.
- **`SyncBadge`** — "Synced Nh ago" freshness pill with a stale state and a
  refresh affordance, driven by the `age_hours`/`stale` fields that
  database-first reads return.

## Client library (`src/lib/`)

- **`api.js`** — the one HTTP module (see conventions below). `API_BASE` is
  `/api`, proxied to the backend by Vite.
- **`auth.jsx`** — `AuthProvider` probes `GET /api/v1/me` once on load and
  resolves one of three modes: **503 → single-user** (no wall, exactly the old
  app), **401 → anonymous** (Login wall), **200 → signed in** (navbar account
  chip + sign-out).
- **`settings.js`** — two localStorage-backed stores: per-repo *analysis*
  settings (`max_commits`, `top`) and global *UI* settings (theme, accent).
  Also exports the `ACCENTS` palette list and color helpers.
- **`theme.js`** — the `ThemeContext` (kept out of `App.jsx` to avoid a
  circular import and keep fast-refresh working) plus `accentThemeCss` /
  `mixHex`, which synthesize a per-theme palette for a chosen accent.

`App.jsx` owns theme state: `theme` resolves `dark | light | system` (the
`system` option tracks the OS preference live), and the chosen accent is
injected as an `#accent-theme` `<style>` tag that recolors the whole app —
primary, borders, muted text, and glows.

## API conventions (`src/lib/api.js`)

One tiny client module encodes the contract every page follows:

- `getJSON(path, {ttl})` / `postJSON(path, payload)` / `putJSON(path, payload)`
  — thin `fetch` wrappers that throw an **`ApiError`** carrying `status`,
  `message` (the API's `detail` string) and `body` on non-2xx responses.
- **Branch on the status code, never the message.** `404` means "not analyzed
  yet" and is normal control flow — pages turn it into a POST + job poll —
  so use the exported `isNotFound(err)` (or `err.status === 404`). Sniffing
  `err.message` for `"404"` silently never matched: the message is FastAPI's
  `detail` string, which never contains the number.
- **Triggers** return `202 {job_id, status_url}`; the UI polls
  `GET /jobs/{job_id}` every 1–2 s until `done`/`failed`, then re-fetches the
  read endpoint. There is no cancel endpoint.
- **A session-scoped GET cache** makes page-to-page navigation instant:
  opt in per call with `{ ttl }` (ms), every successful GET reprimes its
  entry, `/jobs` polling is never cached, and any successful POST/PUT clears
  the whole cache (a trigger changes server state, so earlier reads are
  suspect). `invalidateCache(prefix)` clears it manually.
- `postJSON`/`putJSON` always send the `X-GitPulse-Client: dashboard` CSRF
  header — harmless in single-user mode, required in multiuser.
- Repo keys with slashes (`owner/repo`) are used raw in URLs — the API's
  path-typed params accept them without encoding.
