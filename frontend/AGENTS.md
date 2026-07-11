# RepoLens Frontend — Agent Instructions

You (the agent, and every subagent you spawn) are building the **React
dashboard** for RepoLens, a GitHub analytics platform. The backend is
**finished and frozen** — your job is purely frontend: turn the HTML
prototypes the developer gives you into React pages wired to the local
FastAPI backend described below.

Read this whole file before writing code. Everything an agent needs — stack,
rules, the exact API contract with response shapes, and per-page specs — is
here. Deeper background lives in `../docs/` (architecture, tools, API), but
this file is self-sufficient for UI work.

---

## 1. Hard rules (apply to every subagent)

1. **Never modify anything outside `frontend/`.** `api/`, `core/`, `tools/`,
   `pipeline/`, `config/`, `tests/` are the finished backend. If the UI seems
   to need a backend change, STOP and report it to the developer instead.
2. **Do not invent API endpoints or response fields.** The contract in §4 is
   the truth, taken from the backend source. If in doubt, check the live
   Swagger UI at `http://127.0.0.1:8000/docs` — never guess.
3. **The provided HTML prototypes are the visual source of truth.** Match
   their layout, spacing, colors and typography. The API shapes in §4 are the
   data source of truth. Where a prototype shows data the API doesn't
   provide, omit it or derive it client-side — do not fabricate values.
4. **Fixed stack — do not add to it:** Vite, React 19 (plain JavaScript/JSX —
   **no TypeScript**), Tailwind CSS v4 (via `@tailwindcss/vite`; design
   tokens go in `src/index.css` under `@theme`), `react-router-dom` v7,
   Recharts for charts. No Redux/Zustand/react-query, no axios, no component
   libraries (MUI/shadcn/etc.), no CSS-in-JS. Plain `useState`/`useEffect`
   and the helpers in `src/lib/api.js` are enough for this app.
5. **All API access goes through `src/lib/api.js`** (`getJSON`/`postJSON`
   against `API_BASE = "/api"`). Never hardcode `http://127.0.0.1:8000` in a
   component — the Vite dev proxy maps `/api` to it.
6. **Git:** commit messages are clean and imperative ("Add hotspot table
   sorting"), with **no AI/tool attribution of any kind** (no
   "Co-Authored-By", no "Generated with…") — this is a repo-wide convention.
   Never commit `node_modules/`, `dist/`, or any `.env`.
7. **Definition of done** for any page task: `npm run lint` clean,
   `npm run build` succeeds, the page renders real data from the live
   backend without console errors, and loading/error/empty states all work
   (see §6). Verify in the browser — screenshot against the prototype if you
   have browser tooling.

---

## 2. Running the app

Two processes, both from this repo:

```bash
# 1. backend — run from the repo root (one level up from frontend/)
python -m uvicorn api.main:app          # → http://127.0.0.1:8000, Swagger at /docs

# 2. frontend — run from frontend/
npm install
npm run dev                             # Vite dev server, /api proxied to :8000
```

To get real data to develop against, trigger one analysis first (curl or the
Swagger UI): `POST /analyze` with body `{"repo": "https://github.com/pallets/flask"}`,
then wait for the job (§4.2). The store may already contain analyzed repos —
check `GET /repos`.

Some features depend on server-side config you cannot control from the UI:
Tool 2 profiles and PR reviews need `GITHUB_TOKEN` on the server (a `POST`
without it returns `400`), and AI insights need an LLM provider (the job
fails with a clear error). The UI must handle these gracefully, not assume
they work.

---

## 3. Current state of `frontend/`

- `src/lib/api.js` — API helpers and conventions. **Keep it as the single
  API access point**; extend it rather than fetching ad hoc.
- `src/App.jsx` — router with routes `/`, `/loading`, `/dashboard`,
  `/hotspots`, `/profile`.
- `src/pages/*.jsx` — a working minimal implementation of each page. Treat
  these as the starting point to extend and restyle toward the prototypes —
  preserve their data-fetching logic and conventions unless it's wrong.
- `src/index.css` — Tailwind v4 entry with the `@theme` design tokens.

The developer will supply the prototype HTML files (from the project's
`ui_protoype/` folder): `github_url.html` (landing), `loading.html`,
`Dashboard(1).html`, `Bughotspot.html`, `Developer_profile.html`. If a
prototype you need isn't in the workspace yet, ask for it — don't improvise
a design.

---

## 4. The API contract

### 4.1 Conventions

- **Database-first, always.** Every read serves what is stored in the
  database, however old — the server never silently calls GitHub on a `GET`.
  Fresh data is fetched from GitHub only via the explicit refresh actions
  below (§5a). Show `generated_at` next to data so users can tell how old it
  is, and pair it with the sync button.
- **Reads** are `GET` and return JSON immediately. A `404` means "not
  analyzed yet"; its `{"detail": "..."}` string names the `POST` that fixes
  it — surface that message to the user.
- **Triggers** are `POST` and return `202` with
  `{"job_id", "status": "pending", "status_url": "/jobs/{id}"}`. The
  analysis runs server-side in the background.
- **Repo keys contain a slash** (`pallets/flask`). Use them raw in URL
  paths — the API routes are path-typed, `fetch("/api/repos/pallets/flask/hotspots")`
  works. Local-path repos have bare keys (`myproject`).
- All timestamps are ISO-8601 UTC strings. Format them client-side.

### 4.2 Job polling (the one dynamic pattern in the app)

After any trigger, poll `GET /jobs/{job_id}` every 1–2 s:

```json
{
  "id": "a1b2c3d4e5f6", "kind": "analyze", "params": {"repo": "..."},
  "status": "pending | running | done | failed",
  "created_at": "...", "finished_at": "... | null",
  "progress": {"phase": "cloning repository (GitHub)", "pct": 40,
                "detail": "pallets/flask", "updated_at": "..."},   // null until first phase
  "result": { "...small summary, full report is in the store..." },
  "error": "ExcType: message | null"
}
```

**Progress bar (required UI):** render `progress.phase` as the status line —
it tells the user *what* is slow (GitHub, git, ML, LLM) — with `detail` as
secondary text. Show a determinate bar when `pct` is a number, an
indeterminate/animated bar when it is `null`. Phases you will see include
`cloning repository (GitHub)` (with live pct), `reading commit history (git)`,
`fetching commits (GitHub)` (pct = repos done), `embedding bug-fix diffs (ML)`,
`scoring files (weighted formula / ML second opinion)`, `summarizing the diff
(LLM)`, `saving report (database)`. Display the strings as-is — never
hardcode the list.

Stop polling on `done` (then fetch the read endpoint) or `failed` (show
`error`, offer retry). There is no cancel endpoint. A `404` on `/jobs/{id}`
means the server restarted and forgot the job — treat as failed.

### 4.3 Triggers

| Endpoint | Body / notes |
|---|---|
| `POST /analyze` | `{"repo": "<url or local path>", "refresh"?: bool, "max_commits"?: int, "top"?: int}` — runs Tool 1, also populates the commit cache used by activity |
| `POST /commit-quality` | `{"repo": "...", "max_commits"?: int, "top"?: int}` |
| `POST /profiles/{username}` | no body; `400` if server lacks `GITHUB_TOKEN`; always rebuilds |
| `POST /repos/{owner}/{repo}/pr-reviews/{n}` | no body; `400` without token |
| `POST /repos/{key}/insights` | no body; job fails if server has no LLM |

### 4.4 Discovery & health

`GET /repos` — the landing page's data:

```json
{"repos": [{
  "repo": "pallets/flask",
  "commits": 238,
  "hotspots": {"generated_at": "...", "files": 137} ,        // or null
  "commit_quality": {"generated_at": "..."},                  // or null
  "pr_reviews": [3, 42]                                        // PR numbers, may be []
}]}
```

`GET /profiles` → `{"profiles": [{"username", "generated_at", "primary_type"}]}`
`GET /health` → `{"status": "ok", "store": "mongo|json", "version"}`
`GET /test` → per-subsystem self-test (store round-trip, LLM availability,
similarity backend, token/webhook config) — ideal for a settings/status view.
`GET /config` → resolved server settings, secrets masked.

### 4.5 Reads and their exact shapes

**`GET /repos/{key}/hotspots?top=50`**

```json
{"repo": "pallets/flask", "generated_at": "...", "rows": [{
  "path": "src/flask/app.py",
  "score": 0.586,                                   // 0..1, RELATIVE ranking within this repo
  "components": {"bug": 1.0, "churn": 0.33, "authors": 0.5, "complexity": 0.9},
  "raw": {"commits": 40, "churn_window": 2, "churn_lines": 812, "authors": 14,
           "bugfix_count": 4, "bug_score": 1.62, "last_change_days": 12.5,
           "last_was_bugfix": true, "loc": 2210, "cyclomatic": 167},
  "reasons": ["4 bug-fix commit(s) (recency-weighted 1.6)", "..."],   // ≤3 strings
  "ml_prob": 0.81                                   // null unless the optional ML model is trained
}]}
```

**`GET /repos/{key}/commit-quality`**

```json
{"key": "...", "generated_at": "...", "repo": "...",
 "commits": 238, "avg_score": 7.17, "good": 180, "weak": 9,
 "avg_subject_len": 41.2, "pct_imperative": 78, "pct_referenced": 3,
 "contributors": [{"author", "commits", "avg_score"}],       // sorted worst-first
 "trend": [{"month": "2026-01", "commits", "avg_score"}],
 "common_issues": [["no issue/ticket reference", 232], ...],  // [label, count] pairs, ≤6
 "worst": [{"sha", "author", "month", "subject", "score", "issues": ["..."]}],
 "scored": [ ...same shape as worst, every commit... ]}
```

**`GET /repos/{key}/activity?days=365&recent=15`** (404 until `POST /analyze` has cached commits)

```json
{"repo": "...", "total_commits": 238, "window_days": 365,
 "window_commits": 154, "window_bugfix_ratio": 0.22,
 "contributors_total": 31,
 "contributors": [{"author", "commits", "share"}],            // top 10
 "recent_commits": [{"sha": "abc1234", "subject", "author", "date", "is_bugfix"}],
 "heatmap": [{"date": "2026-07-01", "count": 3}, ...],        // daily buckets, sorted
 "health": {"score": 7.8, "commit_quality": 7.17, "stability": 8.9,
             "formula": "0.6 * commit_quality + 0.4 * (1 - recent_bugfix_ratio) * 10"}}
```

`health.commit_quality` is `null` (and the formula string says so) until a
commit-quality report exists. Show the formula in a tooltip — transparency is
a product principle here.

**`GET /repos/{key}/meta?refresh=false`** (GitHub header data; only
`owner/repo` keys have it, needs server token on first fetch; `404`/`502` possible)

```json
{"key": "...", "generated_at": "...", "full_name": "pallets/flask",
 "description": "...", "language": "Python",
 "languages": [{"name": "Python", "pct": 98.2}, ...],
 "stars": 68000, "forks": 16000, "open_issues": 5,
 "visibility": "public", "default_branch": "main", "url": "https://github.com/..."}
```

**`GET /repos/{key}/insights`** (404 until its POST has run)

```json
{"key": "...", "generated_at": "...", "repo": "...",
 "bullets": ["...", "...", "..."],                            // ≤4 one-sentence insights
 "provider": "claude (model=...)",
 "based_on": {"commits": 238, "has_commit_quality": true, "has_hotspots": true}}
```

**`GET /profiles/{username}`**

```json
{"key": "...", "generated_at": "...", "username": "octocat",
 "primary_type": "Feature Builder", "label": "...",
 "activity_split": {"Bug Fixer": 18.0, "Feature Builder": 42.0, "Refactorer": 10.0,
                     "Reviewer": 8.0, "Documentation Writer": 12.0, "Architect": 10.0},
 "commits_analyzed": 640, "repos_analyzed": 15,
 "top_languages": ["Python", "JavaScript"],
 "languages": [{"name", "pct"}],
 "commit_message_quality": 6.8,                                // 0..10
 "authored_prs": 120, "prs_merged": 98, "issues_resolved": 41,
 "reviews": 87,
 "review_ratio": 0.42,                     // numeric — safe for UI math
 "review_participation": "Active (87 PRs reviewed)",  // display label, NOT a number
 "user": {"name", "avatar_url", "bio", "followers", "following",
           "public_repos", "created_at", "years_active", "url"},   // may be {}
 "heatmap": [{"date", "count"}],
 "llm_summary": "... or a clear placeholder when no LLM is configured"}
```

**`GET /repos/{key}/pr-reviews`** → `{"repo", "pr_reviews": [{"number", "level", "generated_at"}]}`

**`GET /repos/{key}/pr-reviews/{n}`**

```json
{"key": "owner/repo#42", "generated_at": "...",
 "level": "HIGH | MEDIUM | LOW",
 "risk_score": 0.55,                                           // 0..1 weighted signal sum
 "breakdown": [{"signal": "file_risk", "weight": 0.30}, ...],  // which checks fired
 "markdown": "## 🤖 RepoLens Pre-Review Report\n...",         // render this
 "warnings": ["..."], "notes": ["..."], "oks": ["..."],
 "similarity": 0.43, "files_changed": 7, "lines_added": 214, "has_summary": true}
```

---

## 5a. The "Sync from GitHub" button (required feature)

Because reads are database-first (§4.1), every repo view and profile view
needs an explicit **"Sync from GitHub"** button — the only way users get
fresh data:

- **Repo sync** (Dashboard header, also usable on repo cards): 
  1. `POST /analyze` with `{"repo": "<key>", "refresh": true}` — this pulls
     new commits from GitHub into the cached clone and re-runs the analysis;
     poll the job as usual.
  2. When the job is `done`, call `GET /repos/{key}/meta?refresh=true` once
     (refreshes stars/description/languages), then re-fetch the page's reads.
- **Profile sync** (Developer Profile page): `POST /profiles/{username}`
  (a rebuild always re-hits GitHub) → poll → re-fetch `GET /profiles/{u}`.
- While syncing, disable the button and show progress; on job failure show
  the job's `error` verbatim. Display `generated_at` ("synced 3 days ago")
  beside the button so the staleness is visible.

## 5. Pages — what each one does

Keep the existing routes. Pass context between pages via query params
(`/dashboard?repo=pallets/flask`, `/profile?user=octocat`) so every page is
refreshable and shareable — never rely only on router state.

### `/` — Home (prototype: `github_url.html`)
- Hero input: GitHub URL (or local path) → `POST /analyze` → navigate to
  `/loading?job=<id>&repo=<key>`. Derive the repo key client-side from the
  URL (`github.com/owner/repo` → `owner/repo`) for the redirect target.
- Below: "already analyzed" section from `GET /repos` — card per repo
  (commit count, which reports exist, when generated) linking to
  `/dashboard?repo=...`; and profiles from `GET /profiles` linking to
  `/profile?user=...`.

### `/loading` — Job progress (prototype: `loading.html`)
- Reads `job` (+ `repo`/`user` and a `next` target) from query params; polls
  `GET /jobs/{id}` per §4.2. Render the job's `progress` field per §4.1:
  phase text + determinate bar when `pct` is set, indeterminate otherwise.
- `done` → navigate to the target page. `failed` → show `error` verbatim
  with a retry (re-`POST`) and a back-home link. Clear the interval on
  unmount.

### `/dashboard` — Repo overview (prototype: `Dashboard(1).html`)
Data: `meta`, `activity`, `commit-quality`, `insights` for `?repo=`.
- Header: name, description, stars/forks/open-issues, language split
  (`meta` — render the page fine without it if 404/502, it's optional).
- Health score card with formula tooltip; contributors leaderboard; commit
  heatmap (Recharts or CSS grid); recent commits list with bug-fix badges
  (all from `activity`).
- Commit-quality card: `avg_score`, good/weak, `pct_imperative`,
  `pct_referenced`, trend chart, common issues. If 404 → button that runs
  `POST /commit-quality` → `/loading`.
- AI Insights card: `bullets` from `insights`; if 404 → "Generate insights"
  button (`POST` → poll → refetch). If the job fails (no LLM on the server),
  show the error text and leave the button available.
- Prominent link to `/hotspots?repo=...`.

### `/hotspots` — Bug hotspot table (prototype: `Bughotspot.html`)
- `GET /repos/{key}/hotspots` for `?repo=`. Ranked table: rank, file path,
  score (bar or badge scaled 0–1), the ≤3 `reasons`, and the component
  breakdown (`components`) as stacked/mini bars.
- If any row has non-null `ml_prob`, add an "ML" column and visually flag
  disagreements (high `score` + low `ml_prob` or vice versa) — this mirrors
  the CLI behavior.
- 404 → "not analyzed yet" empty state with an analyze button (`POST /analyze`).

### `/profile` — Developer profile (prototype: `Developer_profile.html`)
- Username input (or `?user=`) → `GET /profiles/{u}`. On 404 → offer
  "Build profile" → `POST /profiles/{u}` → `/loading`. On `400` from the
  POST → explain the server is missing `GITHUB_TOKEN`.
- Render: `user` header (avatar, bio, followers — may be empty `{}`),
  `activity_split` as a donut/radar (it's percentages over six fixed types),
  `languages` bars, `commit_message_quality` (0–10), PR/review stats,
  `heatmap`, and `llm_summary` (may be a placeholder string — show as-is).

---

## 6. UX rules (every page, every subagent)

- **Three states minimum** per data block: loading (skeleton or the
  prototype's loader), error (show the API `detail` string — it tells the
  user exactly what to run), and empty/not-analyzed (call-to-action that
  triggers the right POST).
- Numbers have fixed meanings — label them: hotspot `score` is a 0–1
  **relative** rank within the repo (not a probability); `health.score` and
  `commit_message_quality` are 0–10; `activity_split` and language `pct`
  are percentages.
- Don't spam the API: fetch on mount and on explicit user action; no
  polling except `/jobs/{id}`.
- Keep components small and colocated: one file per page in `src/pages/`,
  shared pieces in `src/components/` (create it when a piece is used by two
  pages — not before).
- Accessibility basics: real `<button>`/`<a>`, alt text on avatars, don't
  convey risk level by color alone (HIGH/MEDIUM/LOW also as text).

## 7. Suggested task split for subagents

Work is naturally parallel by page after a shared first step:

1. **First (blocking):** verify/extend `src/lib/api.js` (job-polling helper,
   endpoint wrappers) and the Tailwind `@theme` tokens extracted from the
   prototypes' palette. Everything else depends on this.
2. Then one task per page (§5), each owning its route end-to-end.
3. **Last (blocking):** integration pass — navigation between pages, shared
   empty states, `npm run lint` + `npm run build`, and a live walkthrough
   against the running backend (analyze `pallets/flask`, click through every
   page).

When a subagent finishes, it must report: what it built, which endpoints it
consumed, and the result of the §1.7 checklist — not just "done".
