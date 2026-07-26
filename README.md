# RepoLens — v0.4 (API Layer)

GitHub analytics & intelligence platform, exposed through an interactive CLI.
See [CHANGELOG.md](CHANGELOG.md) for the per-version breakdown, and
[docs/](docs/README.md) for the technical documentation (architecture, data
model, per-tool internals, API, configuration, testing).

Two capstone documents:
- **[PITCH.md](PITCH.md)** — the non-technical guide: explain, demo, and
  defend the project without programming knowledge.
- **[TECHNICAL_DEEP_DIVE.md](TECHNICAL_DEEP_DIVE.md)** — the engineering
  "why": every major decision with its alternatives, the live-demo slowdown
  map, security posture, limitations.

It follows the *revised* architecture (see `../GitPulse_Revised_Sections.md`):

- **MongoDB** as the primary datastore (with a transparent JSON-file fallback so
  it runs before Mongo is installed).
- A **recency-weighted risk score** instead of a trained XGBoost classifier —
  no training data, works on small repos, fully explainable.
- A **pluggable LLM provider** — run a local model (LM Studio) *or* bring your own
  Claude / OpenAI / Gemini API key. The LLM is always optional.

## What's implemented

**v0.1 — Foundation**

| Roadmap item | Where |
|---|---|
| GitHub/git client with MongoDB caching | `core/git_client.py`, `core/github_client.py`, `core/db.py` |
| Commit classification (bug-fix keyword detection) | `pipeline/classify_commits.py` |
| Bug Hotspot Predictor — recency-weighted scorer (Tool 1) | `tools/bug_hotspot/scorer.py`, `explainer.py` |
| Feature engineering | `pipeline/extract_features.py` |
| Interactive CLI | `cli.py` (+ thin `scripts/`) |
| *Bonus:* XGBoost "second opinion" | `tools/bug_hotspot/{dataset,normalize,ml_scorer}.py` |

**v0.2 — Intelligence Layer**

| Roadmap item | Where |
|---|---|
| Pluggable LLM provider (LM Studio / Claude / OpenAI / Gemini) | `core/llm.py` |
| Commit Message Quality Analyzer (Tool 4) | `tools/commit_quality/` |
| Developer Skill Profiler — per-user (Tool 2) | `tools/dev_profiler/`, `pipeline/fetch_user_activity.py` |

**v0.3 — PR Review**

| Roadmap item | Where |
|---|---|
| Diff-similarity engine (ChromaDB / stdlib fallback) | `core/embeddings.py`, `pipeline/build_bug_index.py` |
| PR Review Assistant (Tool 3) | `tools/pr_reviewer/` |
| Tool 1 cleanup (docs/config false positives) | `core/paths.py`, `pipeline/extract_features.py` |

**v0.4 — API Layer**

| Roadmap item | Where |
|---|---|
| FastAPI backend (read layer + BackgroundTasks triggers) | `api/main.py`, `api/jobs.py` |
| PR-review webhook (deferred from v0.3) | `api/webhook.py` |

The React dashboard completes v0.4.

## Web API (v0.4)

```bash
pip install fastapi "uvicorn[standard]"
python -m uvicorn api.main:app --reload   # from this directory
```

Interactive docs at `http://127.0.0.1:8000/docs`. The API is a thin layer over
the same engine the CLI uses — reads come from the store, analyses run as
background jobs:

| Endpoint | What |
|---|---|
| `GET /health`, `GET /config` | liveness + masked settings |
| `POST /analyze` `{"repo": ...}` | run Tool 1 in the background → `202` + job id |
| `POST /commit-quality` `{"repo": ...}` | run Tool 4 in the background |
| `POST /profiles/{user}` / `POST /repos/{o}/{r}/pr-reviews/{n}` | run Tools 2 / 3 (need `GITHUB_TOKEN`) |
| `GET /jobs/{id}` | job status + result summary |
| `GET /repos/{key}/hotspots` · `/commit-quality` · `/pr-reviews/{n}` | read stored reports |
| `GET /profiles/{username}` | read a stored profile |
| `POST /webhook/github` | GitHub PR webhook → auto-runs Tool 3 |

The webhook needs `GITHUB_WEBHOOK_SECRET` (HMAC-verified; disabled otherwise) and
reviews PRs on `opened / reopened / synchronize / ready_for_review`. Set
`GITPULSE_WEBHOOK_POST=true` to also post the report back as a PR comment.

## How the hotspot score works

For every file still present at HEAD:

```
score = 0.40 * bug      # Σ over bug-fix commits of 0.5^(age_days / halflife)
      + 0.25 * churn     # changes in the last CHURN_WINDOW_DAYS
      + 0.15 * authors   # distinct authors who touched the file
      + 0.20 * complexity# size (LOC); radon cyclomatic shown for .py files
```

Each component is min-max normalized across the repo, so the result is a
*relative* ranking within that repository. Every score ships with plain-English
reasons.

## Troubleshooting

**"Cannot analyze 'owner/repo': it has no cached commits and the repository
could not be opened."** — the interpreter running the server does not have
**GitPython**. This is easy to hit when `python` on your PATH resolves to an
unrelated virtualenv that happens to have FastAPI: the server starts, serves
repos that are already cached, and fails on every *new* one. The error now
prints the offending interpreter path. Fix it with
`python -m pip install -r requirements.txt`, or launch via `run.bat`, which
refuses any interpreter lacking GitPython.

**AI features do nothing (`local` provider).** LM Studio can be running with
*no model loaded*, and `LLM_MODEL` must be its **exact id including the
publisher prefix** (`google/gemma-4-e4b`, not `gemma-4-e4b`). Set
`LOCAL_LLM_AUTOLOAD=true` to have RepoLens load a model for you. Check with
CLI option 7 (`test-llm`) or `GET /test`.

**Dashboard shows old/empty data.** If `pymongo` is missing from the running
interpreter, the API silently falls back to the JSON cache in `data/cache/`
instead of MongoDB. `GET /health` reports which store is active.

**Server restarts itself mid-analysis / jobs vanish while polling.** If you run
uvicorn with a bare `--reload`, the reloader watches the *whole* project — and
the thousands of files a clone drops into `data/cache/clones/` trigger a
restart mid-job, wiping the in-memory job registry (the log shows
`WatchFiles detected changes in 'data\cache\clones\...' Reloading...`).
Use `run.bat`, or pass explicit reload dirs:
`uvicorn api.main:app --reload --reload-dir api --reload-dir core --reload-dir pipeline --reload-dir tools --reload-dir config`.

## Quick start

```bash
# 0. easiest: double-click run.bat  (starts API + dashboard, checks deps)

# 1. (optional) create a virtualenv
python -m venv venv
venv\Scripts\activate          # Windows  (source venv/bin/activate on *nix)

# 2. install dependencies
pip install -r requirements.txt

# 3. configure (optional — sensible defaults work out of the box)
copy .env.example .env          # cp on *nix

# 4. launch the interactive CLI and follow the prompts
python cli.py
```

> No MongoDB? No problem. The CLI prints a warning and caches to
> `data/cache/` as JSON instead. Set `GITPULSE_STORE=mongo` to require Mongo.

## Interactive CLI

The tool is menu-driven — run `python cli.py` and pick an option; it asks for
whatever it needs via `input()` prompts (press Enter to accept the `[default]`).

```
RepoLens - GitHub Analytics & Intelligence
==========================================
  1) analyze        rank bug-hotspot files (+ XGBoost second opinion if trained)
  2) pull           fetch & cache commit history
  3) train          train the XGBoost second-opinion model (from train_repos.txt)
  4) commit-quality score commit messages (+ LLM rewrites)
  5) profile        build a developer skill profile for a GitHub user
  6) review-pr      pre-review report for a pull request (Tool 3)
  7) test-llm       check the configured LLM provider
  8) setup-indexes  create MongoDB indexes
  9) config         show resolved settings
 10) evaluate      temporal hold-out validation of the hotspot score
 11) quit
```

`Repo path or URL` is a local git repository path or a remote URL (cloned once).

The `scripts/` entry points are single-action interactive shortcuts:

```
python scripts/run_analysis.py   # prompts, then runs analyze
python scripts/pull_repo.py      # prompts, then caches history
python scripts/setup_indexes.py  # creates MongoDB indexes
```

### Example output

```
Bug Hotspots - owner/repo  (842 commits, 137 bug-fix, 211 files scored)
============================================================================================
#    File                                         Score  Top reasons
--------------------------------------------------------------------------------------------
1    src/auth/session.py                          0.873  9 bug-fix commit(s) (recency-weighted 3.4); 6 change(s) in last 30d; 7 distinct authors
2    api/routes/payments.py                       0.804  5 bug-fix commit(s) (recency-weighted 2.1); cyclomatic complexity 42
...
```

## Optional: XGBoost "second opinion"

The weighted score is the primary, always-on signal. You can *additionally* train
an XGBoost model that gives a second, ML-based opinion — useful for showing a real
trained model and for catching files the formula over/under-rates.

It's built to be honest and to **generalize across languages**:

- **Language-agnostic features.** It uses git-derived process metrics (churn,
  authors, recency-weighted prior fixes, last-change age) plus LOC — *no*
  language-specific complexity. So a model trained on Python repos transfers to
  JavaScript, Go, etc.
- **No label leakage.** Training uses *temporal labeling*: features come from
  commits **before** a cutoff date; the label is whether the file got a bug fix in
  the window **after** it. Future bugs never leak into the features.
- **Per-repo percentile normalization.** Every feature is ranked within its own
  repo before pooling, so "90th-percentile churn" means the same thing in a tiny
  JS repo and a huge Python one — this is what makes cross-repo/cross-language
  pooling valid.
- **Honest evaluation.** Reports **cross-repo AUC** (GroupKFold by repo) and
  **held-out-language AUC** (train without a language, test on it). If there aren't
  enough positive examples, it flags itself `reliable: False` instead of pretending.

### Train it

1. List your training repos in `train_repos.txt` (one per line, optional language tag):

   ```
   https://github.com/pallets/flask,python
   https://github.com/expressjs/express,javascript
   https://github.com/gin-gonic/gin,go
   ```

   Pool 5–15 repos across 2–3 languages, each with a few hundred commits.

2. Run the **train** option in the menu (`python cli.py` → `3`). It clones each
   repo, builds the temporal-snapshot dataset, trains, prints an evaluation report,
   and saves the model to `data/models/hotspot_xgb.json`.

3. Run **analyze** as usual — when a trained model exists, the table automatically
   gains an `ML` column and flags files where the formula and the model disagree:

   ```
   #    File                  Wtd    ML     Top reasons
   1    src/auth/session.py   1.000  0.81   6 bug-fix commit(s)...
   2    api/payments.py       0.323  0.12   2 change(s) in last 30d...
   ----------------------------------------------------------------------
   Disagreements (worth a look):
     - api/payments.py: formula HIGH but ML LOW
   ```

> Needs `pip install xgboost scikit-learn numpy`. Without them, RepoLens runs
> exactly as before (weighted score only) — the ML path is fully optional.

## Intelligence Layer (v0.2)

### Pluggable LLM provider

Pick a backend in `.env` with `LLM_PROVIDER` — the LLM is always optional and
every rule-based feature works without it.

| `LLM_PROVIDER` | Backend | Needs |
|---|---|---|
| `local` (default) | LM Studio (or any OpenAI-compatible server) | LM Studio running; `pip install openai` |
| `openai` | OpenAI API | `OPENAI_API_KEY`; `pip install openai` |
| `gemini` | Google Gemini | `GEMINI_API_KEY`; `pip install openai` |
| `claude` | Anthropic API (default model `claude-opus-4-8`) | `ANTHROPIC_API_KEY`; `pip install anthropic` |

Check it from the menu (**option 7, `test-llm`**) — it reports the provider and
sends a one-line test prompt.

For LM Studio, `LOCAL_LLM_AUTOLOAD=true` makes RepoLens load a model
automatically when the server is running but nothing is loaded: it uses
`LLM_MODEL` if that model is downloaded (otherwise the first available one)
and triggers LM Studio's just-in-time load, falling back to the `lms` CLI.
Default is off.

### Tool 4 — Commit Message Quality Analyzer

Menu **option 4**. Scores every commit message 0–10 (length, vagueness,
imperative verb, "why" context, issue reference), with per-contributor health,
repo-wide trends, and the most common bad patterns. Answer **yes** to the
rewrite prompt and a configured LLM proposes better messages for the worst ones
(it reads the actual diff, not just the old message).

### Tool 2 — Developer Skill Profiler

Menu **option 5**. Enter a GitHub `@username` and it builds a skill profile from
their public history across repos — a percentage split over **Bug Fixer /
Feature Builder / Refactorer / Reviewer / Documentation Writer / Architect**,
top languages, commit-message quality (reusing Tool 4), and review participation,
plus an optional LLM summary of their PR descriptions.

> Needs `GITHUB_TOKEN` in `.env` and `pip install PyGithub`. Without a token it
> prints a clear message (or shows a cached profile).

### Tool 3 — PR Review Assistant

Menu **option 6**. Enter a PR as `owner/repo#number` (or a PR URL) and it produces
a **pre-review report** before any human looks at it:

- **file risk** — does the PR touch files in the repo's top hotspots (Tool 1)?
- **missing tests** — source changed but no test files touched?
- **change focus** — is it unfocused (many files across many areas) or large?
- **similarity to past bugs** — the PR diff is embedded and compared against the
  repo's past **bug-fix** diffs; high cosine similarity is a warning.
- **AI summary** — an LLM describes what the PR actually does (from the diff).

The report is printed as markdown; you're then asked whether to **post it as a PR
comment**. Needs `GITHUB_TOKEN`. The similarity engine uses sentence-transformers +
ChromaDB when installed, otherwise a built-in lightweight index — no setup required.

## Run the tests

The core logic is pure stdlib, so the tests run with no dependencies installed:

```bash
python tests/test_bug_hotspot.py     # weighted scorer, classifier, features
python tests/test_ml_scorer.py       # normalization, no-leakage labeling, train/predict
python tests/test_llm.py             # provider factory + FakeProvider
python tests/test_commit_quality.py  # message scorer, reporter, suggester
python tests/test_dev_profiler.py    # developer classifier, profile assembly
python tests/test_embeddings.py      # LiteIndex similarity + factory fallback
python tests/test_pr_reviewer.py     # PR risk checks, similarity, report builder
python tests/test_api.py             # FastAPI layer (skips if fastapi not installed)
python tests/test_github_cache.py    # GitHub metadata freshness / refetch policy
python tests/test_hotspot_eval.py    # temporal hold-out validation of the score
python tests/test_identity.py        # multi-user auth, sessions, encrypted keys
# or:  pytest tests/
```

11 suites, 103 tests. Four tests in `test_identity.py` need a real Postgres
and skip unless `TEST_DATABASE_URL` points at a throwaway database — see
[docs/11-testing.md](docs/11-testing.md).

## Project layout (v0.1 subset)

```
test_1/
├── cli.py                     # CLI entry point
├── api/
│   ├── main.py                # FastAPI app: read endpoints + background triggers (v0.4)
│   ├── auth.py                # signup/login, GitHub OAuth, session cookie (v2)
│   ├── webhook.py             # GitHub PR webhook -> auto Tool 3
│   └── jobs.py                # in-memory background-job registry
├── config/settings.py         # .env-driven configuration
├── core/
│   ├── git_client.py          # GitPython: commit history + file metrics + diffs
│   ├── github_client.py       # local clones + GitHubAPI (per-user activity)
│   ├── db.py                  # MongoStore + JsonStore fallback (+ generic reports)
│   ├── llm.py                 # pluggable LLM provider (local/openai/claude/gemini)
│   ├── embeddings.py          # SimilarityIndex: ChromaIndex + LiteIndex fallback (Tool 3)
│   ├── paths.py               # shared file classification (code/doc/config/test)
│   ├── activity.py            # dashboard aggregations (activity_base + windowing)
│   ├── insights.py            # LLM insight bullets for the dashboard
│   ├── progress.py            # phase-report callbacks (CLI prints, API job progress)
│   ├── identity.py            # accounts/sessions/encrypted keys (Postgres, v2)
│   └── analysis.py            # bug-hotspot orchestration
├── pipeline/
│   ├── fetch_commits.py       # git -> classify -> cache
│   ├── fetch_user_activity.py # GitHub user activity -> normalized dict (Tool 2)
│   ├── build_bug_index.py     # repo bug-fix diffs -> similarity index (Tool 3)
│   ├── classify_commits.py    # bug-fix keyword detection
│   ├── extract_features.py    # per-file feature engineering
│   └── build_training_data.py # pool repos -> labeled dataset -> train (XGBoost)
├── tools/
│   ├── bug_hotspot/           # Tool 1: scorer, explainer, dataset, normalize, ml_scorer
│   ├── commit_quality/        # Tool 4: scorer, suggester, reporter, runner
│   ├── dev_profiler/          # Tool 2: classifier, llm_analyzer, profile_builder, runner
│   └── pr_reviewer/           # Tool 3: risk_scorer, similarity, llm_summarizer, report_builder, runner
├── train_repos.txt            # list of repos to train the ML model on
├── frontend/                  # React dashboard (Vite + Tailwind + Recharts)
├── docs/                      # technical documentation (see docs/README.md)
├── scripts/                   # thin wrappers (setup_indexes, pull_repo, run_analysis)
└── tests/                     # 11 suites, network-free (stdlib + FakeProvider + FakeStore)
```
