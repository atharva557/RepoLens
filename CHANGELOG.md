# Changelog

All notable changes to RepoLens (formerly GitPulse) are documented here.
This project follows the milestone roadmap in `../GitPulse_Revised_Sections.md`.

---

## [Unreleased]

- **Multi-user identity plane (Postgres) — first v2 slice** (`MULTIUSER=true`,
  default off = exactly the single-user app): the spec §6.4 schema (`users`,
  `sessions`, `user_repos`, `llm_configs`, `audit_log`) bootstrapped
  idempotently in PostgreSQL (`core/identity.py`, psycopg lazy import);
  "Sign in with GitHub" OAuth (`api/auth.py`: login redirect with state nonce,
  code exchange, user upsert, session cookie httpOnly/SameSite=Lax with only
  its SHA-256 hash stored, sliding 30-day expiry); GitHub tokens and BYO LLM
  keys **Fernet-encrypted** at rest with `FERNET_KEY` (spec §2.5: hash what
  you check, encrypt what you use); CSRF via required `X-GitPulse-Client`
  header; account routes `/api/v1/me` (+ llm / github-token management,
  write-only secrets); every audit-worthy action logged. In multiuser mode,
  analysis triggers require a session and jobs record `created_by`; CORS pins
  to `DASHBOARD_ORIGIN` with credentials. Auth routes answer 503 while off
  (webhook precedent). New deps (optional): `psycopg[binary]`, `cryptography`.
  New 9th suite `tests/test_identity.py` (8 tests, DB- and network-free via a
  `MemoryIdentity` twin + stubbed OAuth exchange). Deferred to the next slice:
  per-repo access rules (§7.12), quotas, per-request LLM resolution (§8.3),
  scope escalation.
- **LM Studio model autoload** (`LOCAL_LLM_AUTOLOAD=true`, default off): when
  the local provider finds the server running but no model loaded, it resolves
  a model (`LLM_MODEL` if downloaded, else an already-loaded one, else the
  first downloaded chat model — via the new `pick_local_model()`), triggers
  LM Studio's just-in-time load with a 1-token request, and falls back to the
  `lms load` CLI if JIT loading is disabled. Announced with `[llm] autoload:`
  lines; `test-llm` shows the toggle; off = exactly the previous behavior.
  Two new tests in `tests/test_llm.py` (7 total in the suite).
- **ChromaDB similarity backend is now live**: `chromadb` + `sentence-transformers`
  installed and verified end-to-end; Tool 3 diff-similarity now uses real semantic
  embeddings (persistent index at `data/chroma`) instead of the TF-IDF fallback.
- **Backends are always announced**: every CLI action prints a `[backend]` line
  stating whether the primary or an alternative was used (store: mongodb vs json
  fallback; similarity: chroma vs lite fallback) — previously only fallbacks warned.
- **Developer profiles are cached**: a profile younger than `PROFILE_CACHE_HOURS`
  (default 24, new `.env` knob) is served from the store instead of re-hitting the
  GitHub API; the CLI asks before re-fetching, and `POST /profiles/{user}` still
  always rebuilds. Cache hits/saves are announced with `[cache]` lines.
- **API: CORS enabled** (`GITPULSE_CORS_ORIGINS`, default `*`) so the React
  dashboard dev server can call the API cross-origin.
- **API: discovery layer** for the dashboard landing pages — `GET /repos`
  (per-repo summary: commit count, hotspot/commit-quality report presence,
  PR-review numbers), `GET /profiles`, and `GET /repos/{key}/pr-reviews`.
  Backed by a new `list_reports()` on both stores (Mongo aggregation /
  JSON-dir scan).
- **API: `GET /test` self-test endpoint** — one call checks every subsystem:
  store save/load round-trip, LLM provider availability, which similarity
  backend would be selected, GitHub-token & webhook configuration.
- `tests/test_api.py` grew to ten tests (discovery, CORS simple + preflight,
  self-test). All eight suites pass.
- **Dashboard read layer** (driven by the `ui_protoype/` screens):
  - `GET /repos/{key}/activity` — contributor leaderboard, recent commits,
    daily heatmap buckets and a transparent health score
    (`0.6·commit_quality + 0.4·(1−recent_bugfix_ratio)·10`), all aggregated
    from the cached commit history (`core/activity.py`).
  - `GET /repos/{key}/meta` — GitHub header metadata (description, stars,
    forks, open issues, language percentages), store-cached with the
    `PROFILE_CACHE_HOURS` TTL (`GitHubAPI.repo_meta` + `get_repo_meta`).
    Fixed: some PyGithub versions leak a `url` string into `get_languages()`.
  - `POST` + `GET /repos/{key}/insights` — LLM-generated insight bullets from
    a digest of stored reports (`core/insights.py`), cached as `repo_insights`.
    Reasoning models get a ≥1536-token budget (512 truncated gemma to empty).
  - Commit-quality reports now carry `avg_subject_len`, `pct_imperative`,
    `pct_referenced` for the dashboard's quality card.
  - `tests/test_api.py`: 13 tests. Shared `report_age_hours()` moved to
    `core/db.py` (profiler + repo-meta reuse it).
- **Developer profile grew the dashboard fields** (Developer_profile.html):
  `user` social header (avatar, bio, followers/following, public repos,
  years active — `GitHubAPI.user_meta`), `languages` with percentages,
  `prs_merged` + `issues_resolved` (GitHub search counts; "resolved" =
  closed issues the user was assigned), and a per-day `heatmap` of the last
  365 days. CLI profile card prints them; old cached profiles still render
  (fields are optional). Rebuild profiles (re-fetch) to populate.
- **Renamed GitPulse → RepoLens** (user-facing strings only): CLI banner,
  API title/root, PR-report header, doc titles. Internals unchanged on
  purpose — `GITPULSE_*` env vars, the `gitpulse` Mongo database, and module
  paths keep working.
- **React scaffold** in `frontend/` (Vite + React, Tailwind v4 via
  `@tailwindcss/vite`, Recharts, react-router-dom). No UI implemented yet —
  `src/pages/*.jsx` are comment-only specs mapping each prototype screen to
  its API endpoints (Home, Loading, Dashboard, BugHotspots, DeveloperProfile;
  conventions in `src/lib/api.js`). The prototype color/font theme is wired
  into `src/index.css` `@theme`; `npm run dev` proxies `/api/*` to
  `127.0.0.1:8000`. Build verified.

---

## [v0.4] — API Layer — 2026-07-02

Adds the **FastAPI backend**: a thin web layer over the existing engine, plus the
**PR-review webhook** deferred from v0.3. The React dashboard is the remaining
v0.4 item. Also fixes several bugs found in an audit of v0.1–v0.3.

### FastAPI backend (`api/`)

| File | Purpose |
|------|---------|
| `api/main.py` | App factory + routes. Reads come from the store; analyses run via `BackgroundTasks` (`202` + job id). Sync handlers on purpose — the engine is synchronous and runs in FastAPI's threadpool. |
| `api/webhook.py` | `POST /webhook/github` — HMAC-verified (`GITHUB_WEBHOOK_SECRET`); auto-runs Tool 3 on PR `opened/reopened/synchronize/ready_for_review`. Posting the report as a PR comment is opt-in (`GITPULSE_WEBHOOK_POST`). |
| `api/jobs.py` | Bounded in-memory job registry (pending/running/done/failed); catches `SystemExit` so engine errors can't kill the server. |

Read endpoints: `/repos/{key}/hotspots`, `/repos/{key}/commit-quality`,
`/repos/{key}/pr-reviews/{n}`, `/profiles/{user}` (the `{key}` param accepts
both `owner/repo` and bare local-clone names). Triggers: `POST /analyze`,
`POST /commit-quality`, `POST /profiles/{user}`, `POST /repos/{o}/{r}/pr-reviews/{n}`.
Meta: `/health`, `/config` (secrets masked), `/jobs/{id}`, `/docs`.

Run: `python -m uvicorn api.main:app --reload` (or `python api/main.py`).

### Bug fixes

- **Tool 4 LLM rewrites crashed** (`TypeError: 'bool' object is not callable`):
  the `suggest` bool parameter in `run_commit_quality_report` shadowed the
  imported `suggest()` function. Import aliased; rewrite path verified end-to-end.
- **MongoDB-backed analysis crashed on date math**: pymongo returns *naive*
  datetimes by default, so cached commit dates couldn't be subtracted from
  tz-aware "now" in the feature extractor. `MongoClient` now uses `tz_aware=True`.
- **Settings crashed on blank numeric `.env` values** (`int("")`): numeric
  settings now fall back to their defaults with a warning instead.
- CLI menu prompt said "1-5" for a 10-option menu; README pointed `test-llm` at
  menu option 6 (it is 7).

### Config & tests

- New `.env`: `GITPULSE_WEBHOOK_POST` (default false). `GITHUB_WEBHOOK_SECRET`
  is now actually consumed (by the webhook).
- New test suite: `tests/test_api.py` — FakeStore + stubbed engine entry points,
  network-free; covers the read layer, job lifecycle, token gates, and webhook
  security (secret gate, HMAC, ignore rules, dispatch). Skips cleanly when
  fastapi isn't installed. All **eight** suites pass.
- New deps (API only): `fastapi`, `uvicorn` (+ `httpx` for the test client).

### Next up (v0.4 completion / v0.5)

- React dashboard (Tailwind + shadcn/ui + Recharts) on top of this API.
- v0.5 evaluation pass (temporal hold-out for Tool 1, human-rated LLM sample).

---

## [v0.3] — PR Review — 2026-07-01

Adds **Tool 3 — PR Review Assistant**: an automated pre-review report for a pull
request, combining v0.1 hotspot risk and the v0.2 LLM, plus a new diff-similarity
engine. Delivered as an on-demand CLI action (webhook deferred to v0.4).

### Roadmap items completed (v0.3)

- [x] Similarity / embedding pipeline (past bug-fix diffs)
- [x] PR Review Assistant (Tool 3)
- [x] On-demand analysis + optional GitHub PR-comment posting *(no GitHub Action)*
- [x] *Folded in:* Tool 1 classifier cleanup (docs/config false positives)

### Diff-similarity engine (pluggable, graceful)

`core/embeddings.py` — a `SimilarityIndex` with two backends, auto-selected:

| Backend | How | Deps |
|---------|-----|------|
| `ChromaIndex` | sentence-transformers (`all-MiniLM-L6-v2`) + ChromaDB (cosine) | heavy, optional |
| `LiteIndex` | stdlib TF-IDF cosine | none |

`open_similarity_index()` prefers Chroma and falls back to Lite with a warning, so
v0.3 runs everywhere and upgrades when the heavy deps are installed. The corpus is
the repo's own past **bug-fix** diffs (`pipeline/build_bug_index.py`).

### Tool 3 — PR Review Assistant

| File | Purpose |
|------|---------|
| `tools/pr_reviewer/risk_scorer.py` | File risk (hotspot membership), missing tests, unfocused/large change — pure stdlib |
| `tools/pr_reviewer/similarity.py` | Embed the PR diff, query the bug corpus, flag high similarity |
| `tools/pr_reviewer/llm_summarizer.py` | LLM plain-English summary of the diff (optional) |
| `tools/pr_reviewer/report_builder.py` | Markdown report (Risk level / ⚠️ Warnings / 📋 Summary / ✅ OK) |
| `tools/pr_reviewer/github_commenter.py` | Post the report as a PR comment (opt-in) |
| `tools/pr_reviewer/runner.py` | Orchestration + `owner/repo#N` / URL parsing |

`GitHubAPI` gained `get_pull()` and `post_pr_comment()`. CLI **`review-pr`** prints
the report and asks before posting. Needs `GITHUB_TOKEN`.

### Tool 1 classifier cleanup

New `core/paths.py` (shared file classification). `extract_features.py` now credits
**bug history only to source files** — a "fix ..." commit that also touches a
`README.md` / `.toml` no longer marks those as hotspots. Churn/authors unchanged.
Regression test added.

### Config & tests

- New `.env`: `SIMILARITY_BACKEND`, `EMBEDDING_MODEL`, `PR_SIMILARITY_TOP_K`,
  `PR_SIMILARITY_WARN`, `HOTSPOT_TOP_N`.
- New tests: `test_embeddings.py`, `test_pr_reviewer.py`, + a Tool-1 regression test.
  All **seven** suites pass (network-free via LiteIndex + FakeProvider + synthetic data).

### Optional dependencies

- `sentence-transformers`, `chromadb` (upgrade the similarity engine). Not required —
  `LiteIndex` is the default fallback.

### Next up (v0.4 — API + Dashboard)

- FastAPI backend (+ the deferred PR webhook), React dashboard.

---

## [v0.2] — Intelligence Layer — 2026-06-30

Adds the LLM and two more tools. Two design decisions shaped it: the LLM backend
is **pluggable** (local LM Studio *or* bring-your-own Claude/OpenAI/Gemini key),
and the Developer Skill Profiler works **per-GitHub-user across repos**.

### Roadmap items completed (v0.2)

- [x] LLM integration — pluggable multi-provider layer (LM Studio default)
- [x] Commit Message Quality Analyzer (Tool 4)
- [x] Developer Skill Profiler — basic classification (Tool 2)

### Pluggable LLM provider layer

`core/llm.py` — choose a backend with `LLM_PROVIDER`:

| Provider | Backend | SDK |
|----------|---------|-----|
| `local` (default) | LM Studio / any OpenAI-compatible server | `openai` |
| `openai` | OpenAI API | `openai` |
| `gemini` | Google Gemini (OpenAI-compatible endpoint) | `openai` |
| `claude` | Anthropic API (default model `claude-opus-4-8`) | `anthropic` |

The LLM is always optional and degrades gracefully (`available()` / `LLMUnavailable`).
SDKs are lazy-imported. CLI **`test-llm`** pings the configured provider.

### Tool 4 — Commit Message Quality Analyzer

| File | Purpose |
|------|---------|
| `tools/commit_quality/scorer.py` | Rule-based 0-10 score (length, vagueness, verb, context, reference) — pure stdlib |
| `tools/commit_quality/suggester.py` | LLM rewrite from message + diff |
| `tools/commit_quality/reporter.py` | Per-commit / per-contributor / trend / common-patterns aggregation |
| `tools/commit_quality/runner.py` | Orchestration |

CLI **`commit-quality`** prints the repo report; opt-in `--suggest`/prompt adds LLM
rewrites for the worst messages. Added `git_client.commit_diff()` and generic
`db.save_report()` / `load_report()`.

### Tool 2 — Developer Skill Profiler (per-user)

| File | Purpose |
|------|---------|
| `core/github_client.py::GitHubAPI` | PyGithub wrapper — repos, commits-by-author, authored PRs, reviews (rate-limit-capped) |
| `pipeline/fetch_user_activity.py` | Pull + normalize a user's public activity |
| `tools/dev_profiler/classifier.py` | Rule-based type distribution (Bug Fixer / Feature Builder / Refactorer / Reviewer / Documentation Writer / Architect) — pure stdlib |
| `tools/dev_profiler/llm_analyzer.py` | Optional LLM read of PR descriptions |
| `tools/dev_profiler/profile_builder.py` | Assembles the card (reuses Tool 4's scorer for commit-message quality) |
| `tools/dev_profiler/runner.py` | Orchestration |

CLI **`profile <username>`** prints the profile card. Needs `GITHUB_TOKEN`
(degrades to a clear message / cached profile without one).

### Config & tests

- New `.env`: `LLM_PROVIDER`, `LLM_MODEL`, `LOCAL_LLM_BASE_URL`, `ANTHROPIC_API_KEY`,
  `OPENAI_API_KEY`, `GEMINI_API_KEY`, `LLM_MAX_TOKENS`, `LLM_TEMPERATURE`,
  `PROFILE_MAX_REPOS`, `PROFILE_MAX_COMMITS_PER_REPO`, `PROFILE_PR_SAMPLE`.
  Removed the Ollama settings. Fixed the `.env` parser's inline-comment handling.
- New tests: `test_llm.py`, `test_commit_quality.py`, `test_dev_profiler.py` (all
  network-free via an in-process `FakeProvider` and synthetic data). All five suites pass.

### Optional dependencies

- `openai` (local/openai/gemini), `anthropic` (claude), `PyGithub` (profiler).
  None are required for the rule-based features.

### Next up (v0.3 — PR Review)

- ChromaDB embedding pipeline, PR Review Assistant (Tool 3), webhook + PR comment posting.

---

## [v0.1] — Foundation — 2026-06-30

The first milestone: the shared data pipeline plus **Tool 1 — Bug Hotspot
Predictor**, driven by an interactive CLI. Built on the *revised* architecture
(MongoDB + recency-weighted scorer, no XGBoost-as-primary, no GitHub Action).

### Roadmap items completed (v0.1)

- [x] GitHub/git client with MongoDB caching
- [x] Commit classification (bug-fix keyword detection)
- [x] Bug Hotspot Predictor — **recency-weighted scorer** (Tool 1)
- [x] Basic CLI output

### Architecture decisions adopted (from the revised doc)

- **MongoDB** is the primary datastore (replaces SQLite). A JSON-file cache is
  used automatically as a fallback when MongoDB isn't reachable, so the tool runs
  on any machine out of the box.
- **Tool 1 uses a transparent recency-weighted formula, not a trained XGBoost
  classifier** — chosen for explainability and because training on a single small
  repo suffers from label leakage and tiny/imbalanced data.
- **The GitHub Action was dropped**; a single PR path is the plan for later.

### What was built

| Area | File(s) | Purpose |
|------|---------|---------|
| Config | `config/settings.py` | `.env`-driven settings (stdlib `.env` parser, no hard dep) |
| Git access | `core/git_client.py` | GitPython: commit history + per-file LOC metrics |
| GitHub | `core/github_client.py` | Resolve a repo ref → local clone (clones remote URLs once) |
| Storage | `core/db.py` | `MongoStore` (primary) + `JsonStore` (fallback), same interface |
| Orchestration | `core/analysis.py` | End-to-end: clone → cache → classify → features → score → explain |
| Pipeline | `pipeline/classify_commits.py` | Bug-fix detection via word-boundary keyword matching |
| Pipeline | `pipeline/extract_features.py` | Per-file features incl. recency-weighted bug score |
| Pipeline | `pipeline/fetch_commits.py` | Pull + classify + cache commit history |
| Tool 1 | `tools/bug_hotspot/scorer.py` | Weighted risk score (bug/churn/authors/complexity) |
| Tool 1 | `tools/bug_hotspot/explainer.py` | Plain-English "why" for every score |
| CLI | `cli.py` + `scripts/` | Interactive (`input()`-driven) menu interface |
| Tests | `tests/test_bug_hotspot.py` | Classifier, features, scorer, explanations |

### How the hotspot score works

For each file present at HEAD:

```
score = 0.40·bug + 0.25·churn + 0.15·authors + 0.20·complexity
```

- **bug** = Σ over bug-fix commits of `0.5 ^ (age_days / halflife)` (recent bugs
  weigh more; old ones decay). Half-life defaults to 30 days.
- **churn** = changes in the last 30 days.
- **authors** = distinct authors who touched the file.
- **complexity** = lines of code (LOC).

Each component is min-max normalized within the repo, so the score is a *relative*
ranking inside one repository — not a probability.

### Bonus — XGBoost "second opinion" (optional, ahead of schedule)

An optional ML counterpart to the weighted scorer was also built. It stays off
unless a model is trained, and is designed to generalize across languages.

| File | Purpose |
|------|---------|
| `tools/bug_hotspot/dataset.py` | Temporal-snapshot labeling (no leakage) |
| `tools/bug_hotspot/normalize.py` | Per-repo percentile normalization |
| `tools/bug_hotspot/ml_scorer.py` | XGBoost train / evaluate / predict |
| `pipeline/build_training_data.py` | Pool multiple repos → labeled dataset → train |
| `train_repos.txt` | List of repos to train on (with optional language tags) |
| `tests/test_ml_scorer.py` | Normalization, no-leakage labeling, train/predict |

Highlights: language-agnostic features (process metrics + LOC only), temporal
labeling to avoid leakage, cross-repo + held-out-language AUC evaluation, and an
honest `reliable: False` flag when there are too few positive examples. Train once,
reuse for all analyses. When a model exists, `analyze` adds an `ML` column and
flags files where the formula and the model disagree.

### CLI

Interactive menu (run `python cli.py`):

```
1) analyze        rank bug-hotspot files (+ XGBoost second opinion if trained)
2) pull           fetch & cache commit history
3) train          train the XGBoost second-opinion model (from train_repos.txt)
4) setup-indexes  create MongoDB indexes
5) config         show resolved settings
6) quit
```

### Tests

```
python tests/test_bug_hotspot.py     # weighted scorer, classifier, features
python tests/test_ml_scorer.py       # normalization, no-leakage labeling, train/predict
```
Both suites pass. The pure-logic core uses only the standard library, so the
weighted-scorer tests run with nothing installed.

### Dependencies

- **Required for full runs:** GitPython (installed). pymongo / radon are optional —
  the code degrades gracefully (JSON cache; LOC instead of cyclomatic complexity).
- **Optional (ML second opinion):** xgboost, scikit-learn, numpy.

### Known limitations / follow-ups

- The keyword classifier credits **every file in a "fix…" commit** as bug-related,
  so docs/config files (e.g. `README.md`, `.toml`) can show false-positive bug
  history. A targeted fix is planned.
- Hotspot rankings are coarse on very small repos (few commits / bug fixes).
- No hold-out validation yet — planned, to put a real accuracy number on Tool 1.

### Next up (v0.2 — Intelligence Layer)

- Ollama integration (local LLM)
- Commit Message Quality Analyzer (Tool 4)
- Developer Skill Profiler — basic classification (Tool 2)
