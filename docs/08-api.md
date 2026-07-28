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
| `PUT /config` | meta | single-user runtime settings: LLM provider/model/key + GitHub token. Applies to the live process immediately and persists to `.env` (seeded from `.env.example` if missing). Write-only — responses are masked; omitted field = unchanged, `""` = clear. `403` in multiuser mode (keys live per-user in `/api/v1/me`) |
| `GET /jobs/{id}` | meta | background-job status |
| `POST /analyze` | trigger | Tool 1 (`{"repo", "refresh", "max_commits", "top"}`) |
| `POST /commit-quality` | trigger | Tool 4 |
| `POST /profiles/{user}` | trigger | Tool 2 — requires `GITHUB_TOKEN`; always rebuilds (skips profile cache) |
| `POST /repos/{o}/{r}/pr-reviews/{n}` | trigger | Tool 3 — requires `GITHUB_TOKEN`. Emails the finished report when `PR_REVIEW_EMAIL=true`; the job result reports `emailed` (recipient count) |
| `POST /repos/{key}/insights` | trigger | LLM insight bullets (`core/insights.py`) |
| `GET /repos` | discovery | per-repo summary for the dashboard landing page. Single-user: everything in the store. Multiuser: **only what the requesting user analyzed** (empty for anonymous) |
| `GET /profiles` · `GET /repos/{key}/pr-reviews` | discovery | stored profiles / reviews lists — `/profiles` is scoped per user the same way |
| `GET /repos/{key}/hotspots` | read | Tool 1 report (`?top=` limit) |
| `GET /repos/{key}/commit-quality` | read | Tool 4 report |
| `GET /repos/{key}/pr-reviews/{n}` | read | Tool 3 report |
| `GET /profiles/{username}` | read | Tool 2 profile |
| `GET /repos/{key}/activity` | read | contributors, recent commits, daily heatmap, health score — served from the `activity_base` aggregate cached at history-save time (`core/activity.py`; window step per request, `?recent=` ≤ 50). Pre-aggregate caches self-heal on first read |
| `GET /repos/{key}/meta` | read | GitHub header metadata (stars, forks, languages) — database-first: cached copy served whatever its age; GitHub only on first fetch or `?refresh=true` |
| `GET /repos/{key}/pulls` | read | the repo's last-N GitHub PRs (any state, reviewed or not; `?limit=`, default 5) — store-cached with a short TTL (`PULLS_CACHE_HOURS`, default 1h) since PR lists churn fast; `?refresh=true` forces a refetch. The dashboard joins these against `/pr-reviews` for review chips |
| `GET /repos/{key}/insights` | read | cached LLM insight bullets |
| `POST /webhook/github` | webhook | GitHub PR events → auto Tool 3 |
| `POST /api/v1/auth/signup` · `/signup/verify` · `/login`, `GET /api/v1/auth/github/login` · `/callback`, `POST /api/v1/auth/logout`, `GET /api/v1/me`, `PUT/DELETE /api/v1/me/llm`, `DELETE /api/v1/me/github-token` | auth (v2) | multi-user identity — email+password and GitHub OAuth share the same session plane. Signup is two steps: `/signup` emails a code and creates nothing (`202`, also the resend — 60s cooldown), `/signup/verify` exchanges it for the account + session (`201`). Login answers one generic `401`. `503` while `MULTIUSER=false`; see [12-identity-postgres.md](12-identity-postgres.md) |

Repo keys contain slashes (`owner/repo`), so repo routes use `:path` params —
`GET /repos/pallets/flask/hotspots` works without URL-encoding.

## What changes under `MULTIUSER=true`

The route table above is the single-user contract. With the identity plane on
(see [12-identity-postgres.md](12-identity-postgres.md)):

- **Triggers require a session.** `POST /analyze`, `/commit-quality`,
  `/profiles/{u}`, pr-reviews and insights answer `401` without one, and the
  job records `created_by`.
- **Each trigger records what the user searched** — repo keys into
  `user_repos`, profile usernames into `user_profiles` — which is what makes
  the discovery endpoints per-user.
- **Analyses run on the caller's own credentials.** `core.identity.user_settings`
  overlays that user's decrypted GitHub token and BYO LLM key onto a *copy* of
  the global settings, so one user's key never leaks into another's job;
  anything they haven't configured falls back to the server's value.
- **`PUT /config` is `403`** — keys are per-user via `/api/v1/me`.
- **CORS** pins to `DASHBOARD_ORIGIN` with credentials, and mutating routes
  require the `X-GitPulse-Client: dashboard` CSRF header.

Deep reads (`GET /repos/{key}/...`, `/profiles/{u}`) and the HMAC-verified
webhook are deliberately unchanged in this slice — hard per-repo ACLs are the
next one.

## Background jobs (`api/jobs.py`)

`JobRegistry` is a thread-safe, **bounded (200), in-memory** map of
`job_id → {id, kind, params, status, created_at, finished_at, progress,
result, error}`. Statuses: `pending → running → done | failed`.

`progress` is the job's latest phase report —
`{"phase", "pct", "detail", "updated_at"}` (`null` until the first phase;
`pct` is `null` when the stage has no measurable total). The engine's long
operations accept a `progress` callback (`core/progress.py`) and report
phases worded to answer "*what* is slow": `cloning repository (GitHub)` with
live percent, `reading commit history (git)`, `fetching commits (GitHub)`
(percent = repos completed), `embedding bug-fix diffs (ML)`,
`scoring files (weighted formula | ML second opinion)`, `... (LLM)`,
`saving report (database)`. The CLI prints the same phases via the default
`print_progress` sink; the dashboard renders them as a progress bar.

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

The report is always persisted, and two delivery channels hang off it. Both
are **opt-in and default off**, because both reach outside the machine:

| | |
|---|---|
| `GITPULSE_WEBHOOK_POST` | posts the report back to the PR as a comment |
| `PR_REVIEW_EMAIL` | emails it (`core/notify.py`) to everyone tracking that repo — in single-user mode, to `NOTIFY_EMAIL` |

Recipients are the repo's trackers precisely because that is already the set
allowed to read the report, so notifying cannot reveal a repo someone couldn't
open. A send that fails is logged and skipped: the review has already been
saved by then, and mail trouble must never turn a successful analysis into a
failed job. The job result carries `emailed` — how many messages went out.
