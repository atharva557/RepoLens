# 03 — Pages

Every page lives in `src/pages/`. Each receives its inputs exclusively from the
URL (path + query string) — there is no shared page-level state outside
`ThemeContext` and `AuthContext`.

---

## `Home` (`/`)

**Purpose:** entry point for new analyses and quick navigation to existing ones.

### Data fetched on mount

```
GET /repos    (30 s TTL)   → repos[], sorted newest-first by generated_at
GET /profiles (30 s TTL)   → profiles[]
GET /health   (30 s TTL)   → { status, store, version }
```

All three are fetched in one `Promise.all`. A `window.focus` / `visibilitychange`
listener re-runs the same load — navigating back from `/loading` or switching
tabs always shows the freshest list without a manual refresh.

### Repo input

The spotlight input accepts:
- Full GitHub HTTPS URLs (`https://github.com/owner/repo`)
- SSH URLs (`git@github.com:owner/repo.git`)
- Bare `owner/repo` shorthands

`looksLikeRepo(text)` validates the input with a regex before submitting.
`looksLikeRemoteUrl(text)` catches non-GitHub remote URLs (GitLab, etc.) and
surfaces a clear error rather than silently failing.

**Auto-analyze on paste:** if `globalSettings.autoAnalyze` is enabled (set in
the Settings drawer), pasting a valid repo URL into the input field triggers
`handleAnalyze` immediately without the user pressing the button.

**Advanced options:** a collapsible panel exposes `max_commits` — saved to
`localStorage` under the repo key via `saveRepoSettings` and sent with the
`POST /analyze` payload.

### Submit flow

```
POST /analyze { repo, refresh: false, max_commits, top }
  → 202 { job_id }
  → navigate /loading?job=<id>&repo=<key>&next=/dashboard
```

### Recent Analysis list

Repos are sorted by `max(hotspots.generated_at, commit_quality.generated_at)`
so the most recently touched repo is always first. Each row shows the repo
key, commit count, which tools have results (hotspots / quality chips), and
inline PR review number chips for quick jump-to. A `SyncBadge` shows data age.

### Profiles rail

A horizontally scrollable row of avatar cards for already-built developer
profiles. Clicking any card navigates to `/profile?user=<username>`.

### Footer status bar

A slim fixed footer reads from the `GET /health` response and shows a live
status dot (`SYSTEM_READY` / `SYSTEM_OFFLINE`), the active store backend, and
the API version.

---

## `Loading` (`/loading`)

**Purpose:** poll a background job and redirect when it finishes.

### URL parameters

| Param | Meaning |
|---|---|
| `job` | Job ID returned by the trigger endpoint |
| `repo` | Repo key (forwarded to the next page) |
| `user` | GitHub username (for profile builds) |
| `next` | Target path after success (default `/dashboard`) |

### Polling loop

```
setInterval(poll, 1500)

poll():
  GET /jobs/{jobId}
    status == "done"    → clearInterval; setTimeout(navigate, 800)
    status == "failed"  → clearInterval; setError(job.error)
    status == 404       → clearInterval; setError("server restarted")
    other error         → clearInterval; setError(e.message)
    pending/running     → update phase display, keep polling
```

The 800 ms delay before redirect lets the user see the progress bar reach 100%
rather than cutting straight to the next page.

`job.progress` drives the display: `phase` is the human-readable step name
(e.g. `cloning repository (GitHub)`), `pct` is 0–100 or `null` when the step
has no measurable total (shown as an indeterminate pulse bar instead).

### Retry

`handleRetry` re-triggers the same analysis type based on `next`:

| `next` value | Re-trigger call |
|---|---|
| `/dashboard` or `/hotspots` | `POST /analyze` |
| `/profile` | `POST /profiles/{user}` |
| `/pr-review` | `POST /repos/{repo}/pr-reviews/{pr}` |
| anything else | `POST /commit-quality` |

---

## `Dashboard` (`/dashboard?repo=<key>`)

**Purpose:** full overview of a repository — the primary post-analysis view.

### Data fetched on mount

Six requests are fired in one `Promise.all` (all soft-fail via a `soft()`
helper that returns `{ unavailable: true }` on error rather than rejecting):

```
GET /repos/{key}/activity?days=<timeRange>&recent=15
GET /repos/{key}/meta
GET /repos/{key}/commit-quality
GET /repos/{key}/insights
GET /repos/{key}/pr-reviews
GET /repos/{key}/pulls
```

`timeRange` comes from `globalSettings.timeRange` (default 365 days, set in
the Settings drawer).

### 404 auto-trigger logic

| Endpoint | 404 means | Auto-action |
|---|---|---|
| `/activity` | Repo not analyzed yet | `POST /analyze` → navigate to `/loading` |
| `/insights` | No LLM run yet | `POST /repos/{key}/insights` → background poll |
| `/commit-quality` | Never scored | `POST /commit-quality` → background poll |

Insights and commit-quality run as **background polls** — the page stays
visible and updates in place when the job finishes, without navigating to
`/loading`. `pollBackgroundInsights` and `pollBackgroundQuality` are
`useCallback`-memoized and share the same pattern:

```
setTimeout(tick, 2000)
tick():
  GET /jobs/{id}
    done    → GET the result endpoint → setData(prev => { ...prev, field: res })
    failed  → setData(prev => { ...prev, field: { unavailable: true } })
    running → schedule next tick
```

Timers are stored in refs (`insightsTimerRef`, `qualityTimerRef`) and cleared
in the effect cleanup so they do not fire after unmount.

### Sections rendered

**Header:** repo name (`meta.full_name` or bare key), `SyncBadge`,
primary-language chip, stars / forks from `meta`, action buttons (CONFIG,
RE-ANALYZE, BUG HOTSPOTS, GITHUB).

**Stats row:** four `Card`s — Contributors, Total Commits, Open Issues, Health
Score. The Health Score card has a hover tooltip showing the formula breakdown
(`activity.health.formula`, `stability`, `commit_quality`).

**Annual heatmap:** a GitHub-style contribution grid. Cells are 13×13 px
squares colored by `getHeatmapColorStyle(count, accentColor, theme)`. The
year selector is derived entirely from the dates present in `activity.heatmap`
— no hardcoded year. Month labels are computed by scanning column positions,
suppressing labels that are too close together (< 2 columns apart).

**Top contributors:** scrollable list of `activity.contributors`, each with a
share bar.

**Recent commits:** the last 15 commits from `activity.recent_commits`. Bug-fix
commits get a red `BUGFIX` chip (from `is_bugfix`).

**AI Insights card:** bullet list from `insights.bullets`. If generating, shows
a pulsing "calculating" indicator. Has a Rebuild button that re-posts
`/repos/{key}/insights`.

**Commit Quality card:** summary metrics grid (avg score, weak commits, imperative
%, references %). A `LineChart` shows the monthly score trend. "View Full
Quality Report" opens the `CommitQualityModal` (see below). A Re-run button
re-triggers `POST /commit-quality` and navigates to `/loading`.

**Language Inventory:** top-4 languages from `meta.languages` with progress
bars.

**Pull Requests card:** shows `pulls.pulls` (live GitHub PRs) joined with
`prReviews` (reviewed PRs) to annotate each PR with its Tool 3 risk level
(HIGH / MEDIUM / LOW chip). Falls back to the reviewed-only list when no
GitHub token is configured. A sync button refreshes the pull list via
`GET /repos/{key}/pulls?refresh=true`.

### `CommitQualityModal`

A full-screen modal with three tabs:

| Tab | Content |
|---|---|
| Overview | Conic-dial showing avg score + RadarChart (score, imperative%, referenced%, clean%) |
| Contributors | Grid of contributor avatar cards from `activity.contributors` |
| Worst Commits | Searchable/filterable list of `quality.worst` commits with per-commit issue breakdown |

Closes on ESC or backdrop click.

### `SettingsModal` (analysis config)

Edits `max_commits` and `top` for the repo (saved via `saveRepoSettings`).
"Save & Analyze" persists the settings and immediately calls `handleReAnalyze`.

---

## `BugHotspots` (`/hotspots?repo=<key>`)

**Purpose:** ranked table of files by bug-hotspot score with a sticky detail panel.

### Data fetched

```
GET /repos/{key}/hotspots?top=50   (60 s TTL)
GET /repos/{key}/activity?recent=10 (60 s TTL, soft-fail)
```

A `404` on hotspots is an **actionable not-found state** (`notFound = true`),
not an error — the page shows a "Run Initial Hotspot Analysis" button instead
of an error card. This distinction is tracked from `isNotFound(e)` (checking
`err.status === 404`), never from the error message string.

### Risk categories

| Score threshold | Label | Color |
|---|---|---|
| ≥ 0.70 | Critical | `text-error` (red) |
| ≥ 0.40 | High | `text-tertiary` (orange) |
| < 0.40 | Medium | `text-primary` (accent) |

### Table features

- **Search:** filters `row.path` (case-insensitive substring).
- **Risk filter:** ALL / CRITICAL / HIGH / MEDIUM dropdown.
- **Pagination:** 10 rows per page (`PAGE_SIZE = 10`). Page changes are
  animated with a 120 ms opacity transition. Global rank (position in the
  full unfiltered list) is preserved across pages.
- **Component weight bars:** each row shows four 4×1 px mini-bars for
  `components.bug`, `components.churn`, `components.authors`,
  `components.complexity` — a quick visual breakdown of what drove the score.
- **ML probability column:** shown only when any row has `ml_prob` set.
  A `warning` icon appears when `|score - ml_prob| > 0.4` (heuristic and ML
  disagree significantly).

### Side panel

Clicking a row opens a sticky side panel (`lg:sticky lg:top-24`) showing:

- File path (selectable for copy)
- Cyclomatic complexity or LOC
- Commit count and total lines churned
- Diagnostic factors (`row.reasons` — plain-English explanations from the
  backend explainer)
- 3 most recent commits in the repo (from `activity.recent_commits`) with
  bug-fix flags

On mobile the panel scrolls into view automatically via `asideRef.scrollIntoView`.
The selected row is kept even when paginating — deselection only happens via
the `×` button.

---

## `DeveloperProfile` (`/profile?user=<username>`)

**Purpose:** display a built developer profile, or build one on first visit.

### Without `?user=`

Renders a search screen with a URL input (`https://github.com/username`
format only — validated by `parseGitHubProfileUrl`) and chips for
already-built profiles from `GET /profiles`.

A compact inline search form also appears in the profile header once a profile
is loaded, so switching between developers does not require navigating back.

### With `?user=`

```
GET /profiles/{username}
  200 → render profile
  404 → auto-trigger POST /profiles/{username} → navigate /loading?user=...
  400 → tokenError = true (GITHUB_TOKEN not configured)
  other → setError
```

The 404 → auto-trigger pattern means the very first visit to
`/profile?user=torvalds` kicks off the build immediately. The user sees the
`Loading` page with progress phases rather than a "not found" dead-end.

### Profile sections

**Header card:** avatar (or initials fallback), `@username`, `primary_type`
badge, followers/following/repos stats, `SyncBadge` with `age_hours` / `stale`
from the API response, inline search form, bio/label.

**Quick stat cards:** Analyzed Commits, PRs Merged (out of authored PRs), Issues
Resolved, Years Active.

**Annual contribution heatmap:** identical mechanics to the Dashboard heatmap,
using `data.heatmap`. Year selector derived from actual data; falls back to a
"no contribution data" empty state if no commits exist for the selected year.

**Top Languages:** GitHub-style segmented bar + legend. Uses a fixed 6-color
categorical palette (`CATEGORICAL`) rather than the accent color, so
multiple languages are always visually distinct.

**Contribution Mix:** `data.activity_split` entries sorted by value — bar chart
showing what fraction of activity is each type (feature, bugfix, docs, etc.).
The top type uses `--color-primary`; others use the categorical palette.

**Commit Health:** conic ring gauge animated on mount (`gaugeAnimated` state
delays the CSS transition by 100 ms so the ring sweeps in). Sub-stats show
`commit_message_quality` (as a percentage) and review participation ratio.

**AI Developer Summary:** always visible. If `data.llm_summary` is null (built
while no LLM was reachable), a Re-sync button is shown instead of hiding the
card silently.

### Staleness

`data.age_hours` and `data.stale` are returned by the API and forwarded to
`SyncBadge`. A stale profile shows the badge in orange. Re-sync triggers
`POST /profiles/{username}` which always rebuilds (bypasses the profile cache).

---

## `PRReview` (`/pr-review?repo=<key>&pr=<n>`)

**Purpose:** display a Tool 3 PR risk report, or trigger one on first visit.

### Without `?repo` / `?pr`

Renders an input screen accepting:
- `owner/repo#42` shorthand
- Full GitHub PR URLs (`https://github.com/owner/repo/pull/42`)

`parsePrInput` handles both forms and navigates to the correct URL. If `?repo`
is present but `?pr` is missing, the input screen shows the repo's reviewed
PR history (from `GET /repos/{key}/pr-reviews`) as quick-access chips.

### With `?repo` and `?pr`

```
GET /repos/{repo}/pr-reviews/{pr}
  200 → render report
  404 → triggerAnalysis → POST /repos/{repo}/pr-reviews/{pr}
             → pollingJobId set → pollJob loop
  400 → tokenError (GITHUB_TOKEN missing)
  other → setError
```

### Live analysis banner

While `pollingJobId` is set, a banner at the top of the report page shows the
current job phase. The **deterministic risk checks finish before the LLM phase**
— the backend saves a partial report with `summary: null` early. `pollJob`
attempts `GET .../pr-reviews/{pr}` on every tick and renders it as soon as it
appears, while the spinner continues for the LLM summary. This way the user
sees the risk level and file stats immediately instead of waiting for the full
LLM generation.

### Report sections

**Header:** `repo#pr`, risk-level badge (RED / ORANGE / GREEN — fixed semantic
colors, deliberately independent of the accent), generated-at timestamp, Email
button, Re-Analyze button.

**Risk Score Computation:** stacked horizontal bar showing each `breakdown`
segment proportionally, plus the formula text
(`0.35 hotspot_overlap + 0.25 size + ... = 0.61 → HIGH`).

**AI Change Summary:** the LLM-generated summary, or a "generating…" indicator
if still in-flight, or a "re-analyze to retry" message if never generated.

**Quick Stats:** Files Changed, Lines Added (red if ≥ 400), Similarity % vs
past bug-fix diffs.

**Signals:** three collapsible sections — Warnings (orange), Notes (neutral),
Oks (green).

**Full Markdown Report:** collapsible toggle revealing the `report.markdown`
field rendered by `SimpleMarkdown` (a minimal inline renderer: `##`, `###`,
`- `, `**bold**`, blank lines).

**Previously Reviewed PRs sidebar:** links to the other reviewed PRs for the
same repo; the current PR is highlighted.

### Email

The **Email** button calls `POST /repos/{repo}/pr-reviews/{pr}/email`
synchronously. The button shows "SENDING…" while in flight, "SENT" on success,
or an error message. `emailState` tracks the three states `{sending}`,
`{ok, count}`, `{error}`.

The `autoEmailReview` global setting (Settings drawer toggle) attaches
`?email=true` to the trigger POST, so the server mails the report as soon as
the analysis finishes — without the user pressing Email separately.

---

## `Status` (`/status`)

**Purpose:** internal diagnostics view.

Fetches `GET /test` and `GET /config` in parallel and renders them as
pretty-printed JSON blocks. No actions — read-only. Used to verify the active
store, LLM availability, GitHub token presence, and resolved configuration
values (secrets are masked by the API).

---

## `Login`

No route — rendered by `Gate` as the full-page wall for anonymous visitors in
multiuser mode. See [07-auth-and-multiuser.md](07-auth-and-multiuser.md) for
the full flow.
