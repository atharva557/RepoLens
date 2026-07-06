# 08 — The Web API (FastAPI)

`api/main.py` is a **thin layer over the same engine the CLI uses** — it adds
HTTP framing, background-job bookkeeping, CORS, and the GitHub webhook.
No analysis logic lives in `api/`.

```bash
python -m uvicorn api.main:app --reload    # from test_1/
# Swagger UI: http://127.0.0.1:8000/docs
```

## App construction

`create_app(settings=None, store=None)` is a factory — tests inject a
`FakeStore` and canned settings. Shared state (`settings`, the store, the
`JobRegistry`) is attached to `app.state` in the lifespan handler. CORS is
enabled for `GITPULSE_CORS_ORIGINS` (default `*`) so the Vite dev server can
call the API cross-origin.

Handlers are deliberately plain `def` (not `async`): the engine is
synchronous, and FastAPI runs sync handlers and sync background tasks in its
threadpool.

## The two endpoint kinds

**Reads** return stored documents immediately; a `404` means "not analyzed
yet" and its `detail` string names the POST to run first.

**Triggers** return `202` with `{job_id, status, status_url}` and run the
analysis in a FastAPI `BackgroundTask`. Clients poll `GET /jobs/{id}` until
`status` is `done` or `failed`, then re-fetch the read endpoint. Job results
are small summaries; full reports live in the store.

| Method + path | Kind | What |
|---|---|---|
| `GET /health` | meta | liveness + active store backend |
| `GET /config` | meta | resolved settings, secrets masked |
| `GET /test` | meta | one-call self-test: store round-trip, LLM availability, similarity backend, token/webhook config |
| `GET /jobs/{id}` | meta | background-job status |
| `POST /analyze` | trigger | Tool 1 (`{"repo", "refresh", "max_commits", "top"}`) |
| `POST /commit-quality` | trigger | Tool 4 |
| `POST /profiles/{user}` | trigger | Tool 2 — requires `GITHUB_TOKEN`; always rebuilds (skips profile cache) |
| `POST /repos/{o}/{r}/pr-reviews/{n}` | trigger | Tool 3 — requires `GITHUB_TOKEN` |
| `POST /repos/{key}/insights` | trigger | LLM insight bullets (`core/insights.py`) |
| `GET /repos` | discovery | per-repo summary of everything in the store (dashboard landing page) |
| `GET /profiles` · `GET /repos/{key}/pr-reviews` | discovery | stored profiles / reviews lists |
| `GET /repos/{key}/hotspots` | read | Tool 1 report (`?top=` limit) |
| `GET /repos/{key}/commit-quality` | read | Tool 4 report |
| `GET /repos/{key}/pr-reviews/{n}` | read | Tool 3 report |
| `GET /profiles/{username}` | read | Tool 2 profile |
| `GET /repos/{key}/activity` | read | contributors, recent commits, daily heatmap, health score — aggregated live from cached commits (`core/activity.py`) |
| `GET /repos/{key}/meta` | read | GitHub header metadata (stars, forks, languages) — store-cached with TTL, needs `GITHUB_TOKEN` on first fetch |
| `GET /repos/{key}/insights` | read | cached LLM insight bullets |
| `POST /webhook/github` | webhook | GitHub PR events → auto Tool 3 |
| `GET /api/v1/auth/github/login` · `/callback`, `POST /api/v1/auth/logout`, `GET /api/v1/me`, `PUT/DELETE /api/v1/me/llm`, `DELETE /api/v1/me/github-token` | auth (v2) | multi-user identity — `503` while `MULTIUSER=false`; see [12-identity-postgres.md](12-identity-postgres.md) |

Repo keys contain slashes (`owner/repo`), so repo routes use `:path` params —
`GET /repos/pallets/flask/hotspots` works without URL-encoding.

## Background jobs (`api/jobs.py`)

`JobRegistry` is a thread-safe, **bounded (200), in-memory** map of
`job_id → {id, kind, params, status, created_at, finished_at, result, error}`.
Statuses: `pending → running → done | failed`.

- In-memory on purpose: the stores persist the *results*; the registry only
  tracks transient state, so losing it on restart is fine for the
  single-process uvicorn deployment. (Celery + Redis is the noted upgrade
  path if outgrown.)
- `run()` catches **`SystemExit` as well as `Exception`** — the engine raises
  `SystemExit` for operational errors (e.g. missing token), and a background
  job must never kill the server. Errors are recorded per-job.

## GitHub webhook (`api/webhook.py`)

`POST /webhook/github` auto-runs Tool 3 when a PR opens or updates:

1. **Disabled without a secret** — no `GITHUB_WEBHOOK_SECRET` → `503`.
2. **HMAC verification** — the `X-Hub-Signature-256` header is checked
   against the raw request body (`hmac.compare_digest`, timing-safe).
   Invalid/missing → `401`.
3. **Event filtering** — only `pull_request` events with action in
   `{opened, reopened, synchronize, ready_for_review}` proceed; everything
   else is acknowledged and ignored.
4. **Dispatch** — the review runs as a normal background job
   (`review_pr_from_payload`), so webhook reviews are observable via
   `GET /jobs/{id}` like any other run.

The report is always persisted; **posting it back as a PR comment is opt-in**
via `GITPULSE_WEBHOOK_POST` (default off — it's outward-facing).
