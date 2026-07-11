# RepoLens Frontend v2 — Work Order

Copy everything below this line into the agent.

---

You are working on **RepoLens** (repo: `atharva557/RepoLens`), a GitHub
analytics platform: a finished Python/FastAPI backend and a React dashboard
in `frontend/`. Your job is **frontend only**: fix four small
frontend↔backend mismatches, then build the missing features listed below.
The backend is complete and frozen — every endpoint and response shape you
need is documented in this prompt. **Never modify anything outside
`frontend/`.** If something seems to need a backend change, stop and report
it instead.

## Ground rules

1. **Stack is locked:** Vite + React 19 (plain JS/JSX — no TypeScript),
   Tailwind CSS v4 (theme tokens live in `src/index.css` under `@theme`),
   `react-router-dom` v7, Recharts. No new dependencies of any kind — no
   axios, no state libraries, no UI kits, no markdown libraries.
2. **All API access goes through `src/lib/api.js`** (`getJSON`/`postJSON`
   against `API_BASE = "/api"`; the Vite dev server proxies `/api` →
   `http://127.0.0.1:8000`). Never hardcode a backend URL in a component.
3. **Match the existing visual language.** The app has an established dark
   "terminal" aesthetic (look at `src/pages/Dashboard.jsx` and
   `BugHotspots.jsx`): `font-code` labels in uppercase, Material Symbols
   icons, `bg-surface`/`border-outline-variant` cards, amber `#D4855A`
   primary. New pages must look like they were always there. Do not invent a
   new style.
4. **Every data block has three states:** loading (skeleton/spinner), error
   (show the API's `detail` string verbatim — it tells the user what to do),
   and empty/not-analyzed (a call-to-action that triggers the right POST).
5. **Pages are shareable:** state that identifies content goes in query
   params (`/dashboard?repo=pallets/flask`, `/profile?user=octocat`), never
   only in router state.
6. **API conventions:** reads are GET and return immediately — a `404` means
   "not analyzed yet". Triggers are POST and return
   `202 {job_id, status, status_url}`; poll `GET /jobs/{job_id}` every 1–2 s
   until `status` is `done` (then re-fetch the read endpoint) or `failed`
   (show `error`, offer retry). Always clear poll timers on unmount. Repo
   keys contain a slash (`owner/repo`) and are used raw in URL paths — do
   not URL-encode them.
7. **Git:** small commits, imperative messages ("Add PR review page"),
   **no AI/tool attribution of any kind** (no Co-Authored-By, no "Generated
   with"). Never commit `node_modules/`, `dist/`, or `.env`.
8. **Definition of done, per task:** `npm run lint` clean, `npm run build`
   succeeds, and the feature verified in the browser against the live
   backend with real data — not just "it compiles".

## One-time setup

```bash
# backend (repo root; use a Python that has the project deps — run.bat
# checks this; a bare `python` may resolve to a venv without GitPython)
py -3 -m pip install -r requirements.txt
py -3 -m uvicorn api.main:app --reload        # http://127.0.0.1:8000, Swagger at /docs

# frontend
cd frontend && npm install && npm run dev      # http://localhost:5173

# seed data to develop against
curl -X POST http://127.0.0.1:8000/analyze -H "Content-Type: application/json" \
     -d '{"repo":"https://github.com/pallets/flask"}'
# check GET /repos — repos may already be analyzed
```

`GITHUB_TOKEN` in the repo-root `.env` is needed for profile builds and PR
reviews (a POST without it returns `400` — the UI must handle that case).

---

## TASK 0 — Fix four mismatches (do these first; ~1 hour total)

**0a. Complexity tile reads a field that doesn't exist.**
`src/pages/BugHotspots.jsx` line ~525 reads `selectedRow.raw.complexity` —
the backend has no such field, so the tile shows "N/A" for every non-Python
file. The row's `raw` object actually contains:
`{commits, churn_window, churn_lines, authors, bugfix_count, bug_score,
last_change_days, last_was_bugfix, loc, cyclomatic}` where `cyclomatic` is
null for non-Python files and `loc` is the size proxy the score actually
uses. Fix: show `raw.cyclomatic` when present (label "CYCLOMATIC"),
otherwise `raw.loc` (label "LINES OF CODE"), and only "N/A" when both are
missing.

**0b. Requesting 100 hotspot rows that can never exist.**
BugHotspots fetches `/repos/${repo}/hotspots?top=100`, but the backend
persists at most 50 rows per analysis. Change the request to `top=50` and
make any "showing N of M" copy honest.

**0c. Analysis settings are silently dropped on re-analysis.**
Dashboard's CONFIG modal collects `max_commits`/`top` and sends them with
its own `POST /analyze` — but BugHotspots' RE-ANALYZE button
(`BugHotspots.jsx` ~line 82) and Loading's retry (`Loading.jsx`
`handleRetry`) POST bare `{repo, refresh: true}`, so the user's settings are
ignored and the re-run can produce a different report. Fix: persist the
settings per repo in `localStorage` (suggested key
`repolens.settings.<repoKey>`, shape `{max_commits, top}`) via a small
helper in `src/lib/` (e.g. `settings.js` with `loadRepoSettings(repo)` /
`saveRepoSettings(repo, s)`), and include them in **every** `/analyze` and
`/commit-quality` POST from every page.

**0d. Home can't cap huge repos.**
Home's first-analysis POST sends no `max_commits`, so pasting a large repo
analyzes its full history. Add a small optional "max commits" field next to
the input (collapsed behind a gear/advanced toggle is fine, default empty =
full history) and thread it through the same settings helper from 0c.

---

## TASK 1 — PR Review page (the flagship; a whole backend tool has no UI)

New route `/pr-review` (+ Navbar item "PR Review"). Reads
`?repo=owner/repo&pr=42` from query params.

**Endpoints:**

- `POST /repos/{owner}/{repo}/pr-reviews/{n}` — trigger. No body. `202` job
  envelope; `400` if the server lacks `GITHUB_TOKEN` (show a clear
  "server needs GITHUB_TOKEN" state).
- `GET /repos/{key}/pr-reviews` →
  `{"repo": "...", "pr_reviews": [{"number": 42, "level": "HIGH|MEDIUM|LOW", "generated_at": "..."}]}`
- `GET /repos/{key}/pr-reviews/{n}` → the report:

```json
{
  "key": "owner/repo#42", "generated_at": "...",
  "level": "HIGH | MEDIUM | LOW",
  "risk_score": 0.5,
  "breakdown": [{"signal": "file_risk", "weight": 0.30},
                 {"signal": "missing_tests", "weight": 0.20}],
  "markdown": "## 🤖 RepoLens Pre-Review Report\n...",
  "warnings": ["..."], "notes": ["..."], "oks": ["..."],
  "similarity": 0.43, "files_changed": 7, "lines_added": 214,
  "has_summary": true
}
```

**Page behavior:**

- Input accepting `owner/repo#42` **or** a full GitHub PR URL
  (`https://github.com/owner/repo/pull/42`) — parse both client-side.
- Submit → POST → poll the job → render the stored report. Reuse the
  polling pattern from `DeveloperProfile.jsx` (or navigate through
  `/loading` with a `next=/pr-review` target — pick whichever is cleaner,
  but the Loading page must then support that target).
- **The centerpiece is the score breakdown**, not the markdown: render
  `risk_score` with its `breakdown` as a horizontal stacked bar where each
  segment is a signal with its weight, captioned with the literal arithmetic
  ("0.30 file_risk + 0.20 missing_tests = 0.50 → HIGH"). Explainability is
  the project's thesis — put the math on screen.
- Below: warnings (amber), notes (neutral), oks (green) as lists, plus the
  stat row (`files_changed`, `lines_added`, `similarity`).
- Render `markdown` in a collapsible "full report" section. **No markdown
  library** — a ~30-line renderer handling `##`/`###` headings, `- ` lists,
  `**bold**` and blank lines is plenty for this known, backend-generated
  format.
- Risk level must never be conveyed by color alone — always show the
  HIGH/MEDIUM/LOW text.
- Sidebar or footer: previously reviewed PRs for this repo (from the list
  endpoint), each linking to its report.
- Home repo cards: `GET /repos` already returns `"pr_reviews": [3, 42]` per
  repo — render small chips linking into this page.

## TASK 2 — Honest loading screen (real progress instead of theater)

`GET /jobs/{id}` returns real progress the backend records while working:

```json
"progress": {"phase": "cloning repository (GitHub)", "pct": 60,
              "detail": "receiving objects", "updated_at": "..."}
```

`src/pages/Loading.jsx` currently ignores this and animates a fake
random-increment bar capped at 92% with fictional log lines. Replace it:

- Headline = `progress.phase`, sub-line = `progress.detail`.
- Bar = `progress.pct` when it's a number; an indeterminate/pulse bar when
  `pct` is null; keep 100% + brief pause on `done`.
- Delete the fake `LOG_LINES` rotation and the random increment logic; the
  step-checklist visual can stay if it's driven by the real phase text.
- Keep everything already correct: 1.5 s polling, treating a `404` job as
  "server restarted", timer cleanup on unmount, retry (with 0c's settings).

## TASK 3 — Freshness everywhere (stop showing stale data silently)

One small reusable chip component (e.g. `src/components/SyncBadge.jsx`):
"Synced 2h ago ↻" — relative time, amber styling when stale, clicking it
triggers the refresh action passed as a prop.

- **Profile page:** `GET /profiles/{u}` now returns `"age_hours": 49.3` and
  `"stale": true|false`. Show the badge in the profile header; clicking →
  `POST /profiles/{u}` → `/loading?job=...&user=...&next=/profile`.
  **Important bug to fix here:** the existing rebuild button
  (`handleBuildProfile`) is only rendered inside the token-error branch — a
  successfully loaded profile currently has **no refresh control at all**.
- **Dashboard header:** badge from `meta.generated_at`; clicking runs the
  existing RE-ANALYZE flow (which also refreshes metadata server-side).
- **Home repo cards:** show relative "analyzed X ago" from
  `hotspots.generated_at` (already in the `GET /repos` payload).

## TASK 4 — Home as a launchpad

- **Profiles rail:** `GET /profiles` →
  `{"profiles": [{"username", "generated_at", "primary_type"}]}`. Render a
  horizontal rail of profile cards (username + `primary_type` badge) linking
  to `/profile?user=...`. Empty state: "No profiles built yet — analyze a
  developer above."
- **PR chips on repo cards** (from Task 1's list data in `GET /repos`).

## TASK 5 — Commit-quality depth (data already in the payload, never shown)

`GET /repos/{key}/commit-quality` already contains, unrendered:

- `contributors`: `[{"author", "commits", "avg_score"}]` — pre-sorted
  worst-first
- `worst`: `[{"sha", "author", "month", "subject", "score", "issues": ["…"]}]`
- `good` (count), `avg_subject_len`

Turn the Dashboard quality card into three tabs: **Overview** (what exists
today + `good` count), **Contributors** (table: author, commits, avg score
with a 0–10 bar), **Worst commits** (subject in `font-code`, score badge,
the `issues` list as small tags — this is the most demo-able content in the
app). Keep it inside the existing card footprint; no new page.

## TASK 6 — Status page (`/status`, Navbar item "System")

- `GET /test` → per-subsystem live check:
  `{"store": {"backend": "mongo|json", "ok": true}, "llm": {"provider": "...", "available": true}, "similarity": "chroma (deps installed) | lite (fallback — ...)", "github_token": true, "webhook": {"enabled": false, "auto_post": false}, "multiuser": {"enabled": false, "identity": null}, "ok": true}`
- `GET /config` → resolved settings, secrets already masked server-side.

Render a tile per subsystem: green when healthy, amber for fallbacks (JSON
store instead of Mongo, lite similarity instead of chroma, LLM unavailable)
— with one plain-English line each ("Using JSON file cache — MongoDB not
reachable"). Below, a collapsible read-only config table. A refresh button
re-runs `GET /test`. This page makes the project's graceful-degradation
design visible; treat fallbacks as informative, not as errors.

## TASK 7 — Profile headline (classification is computed but never shown)

The profile payload includes `primary_type` (e.g. `"Feature Builder"`),
`label` (a one-line description), `top_languages`, and `reviews` (count) —
none currently rendered. Make `primary_type` + `label` the page headline
("FEATURE BUILDER — ships new code across many repos"), with the existing
split chart as supporting evidence. Add `reviews` next to
`review_participation`.

## TASK 8 — Consistency & polish pass (last)

- Every 404/empty state uses a consistent CTA verb: "Analyze now" / "Build
  profile" / "Generate insights" / "Review PR".
- `prefers-reduced-motion`: disable the spin/pulse animations.
- `/` keyboard shortcut focuses the repo input on Home.
- Tables/wide content scroll inside their container — no page-level
  horizontal scroll on mobile widths.
- Icons-only buttons get `aria-label`s; avatar `img`s get `alt`.

---

## Suggested execution order

Task 0 first (unblocks correctness), then 1 → 2 → 3 as independent chunks
(parallelizable across subagents after 0), then 4–8. When a task is done,
report: what was built, which endpoints it consumes, and the result of the
lint/build/live-verification checklist — not just "done".
