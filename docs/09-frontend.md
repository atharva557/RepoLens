# 09 — Frontend (React dashboard)

`frontend/` is a Vite + React 19 single-page app styled with Tailwind CSS 4,
charting with Recharts, routed with react-router. It is a pure client of the
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
| `/` | `Home` | `GET /repos`, `GET /profiles` — what's already analyzed; entry point for new analyses |
| `/loading` | `Loading` | `GET /jobs/{id}` polling while a triggered analysis runs |
| `/dashboard` | `Dashboard` | `GET /repos/{key}/activity`, `/meta`, `/insights`, `/commit-quality` — repo overview: contributors, heatmap, health score, AI insights |
| `/hotspots` | `BugHotspots` | `GET /repos/{key}/hotspots` — ranked hotspot table with reasons |
| `/profile` | `DeveloperProfile` | `GET /profiles/{username}` — type distribution, languages, quality |

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
