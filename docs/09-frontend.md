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
| `/profile` | `DeveloperProfile` | `GET /profiles/{username}` — type distribution, languages, commit health, heatmap, AI summary |
| `/pr-review` | `PRReview` | `GET/POST /repos/{o}/{r}/pr-reviews/{n}` + `GET /repos/{key}/pr-reviews` — accepts `owner/repo#N` or a PR URL, triggers a review, shows the risk report; lists the repo's reviewed PRs |
| `/status` | `Status` | `GET /test`, `GET /config` — live self-test (store, LLM, similarity backend, token/webhook) and the resolved, secret-masked config |

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

- `getJSON(path)` / `postJSON(path, payload)` — thin `fetch` wrappers that
  throw the API's `detail` string on non-2xx responses.
- **Reads** return data immediately; a `404` means "not analyzed yet", and
  its message tells the user which analysis to trigger.
- **Triggers** return `202 {job_id, status_url}`; the UI polls
  `GET /jobs/{job_id}` every 1–2 s until `done`/`failed`, then re-fetches the
  read endpoint. There is no cancel endpoint.
- Repo keys with slashes (`owner/repo`) are used raw in URLs — the API's
  path-typed params accept them without encoding.
