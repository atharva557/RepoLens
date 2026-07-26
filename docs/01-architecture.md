# 01 — Architecture

## Layers

The codebase is a strict four-layer stack. Higher layers may import lower
layers, never the reverse.

```
┌────────────────────────────────────────────────────────────────┐
│ INTERFACES     cli.py (interactive menu)                       │
│                api/   (FastAPI: reads, job triggers, webhook)  │
│                frontend/ (React dashboard, talks to api/)      │
├────────────────────────────────────────────────────────────────┤
│ TOOLS          tools/bug_hotspot     tools/dev_profiler        │
│                tools/pr_reviewer     tools/commit_quality      │
│                (one folder per analysis tool; each has a       │
│                 runner.py orchestrating its pipeline)          │
├────────────────────────────────────────────────────────────────┤
│ PIPELINE       pipeline/ — reusable fetch/classify/extract     │
│                steps shared by the tools                       │
├────────────────────────────────────────────────────────────────┤
│ CORE SERVICES  core/git_client     GitPython: history, diffs,  │
│                                    per-file metrics            │
│                core/github_client  clones + GitHub REST API    │
│                core/db             MongoStore + JsonStore      │
│                core/llm            pluggable LLM providers     │
│                core/embeddings     similarity index backends   │
│                core/paths          file-type classification    │
│                core/analysis       Tool 1 orchestration        │
│                core/activity       dashboard aggregations      │
│                core/insights       LLM insight bullets         │
│                core/progress       phase-report callbacks      │
│                core/identity       accounts/sessions (Postgres,│
│                                    MULTIUSER=true only)        │
└────────────────────────────────────────────────────────────────┘
```

`config/settings.py` sits beside all of this: a dataclass loaded from `.env` /
environment variables (with a tiny stdlib parser, so `python-dotenv` is not
required). Every layer receives a `Settings` instance and a store — nothing
reads global state.

## End-to-end data flow (Tool 1 as the example)

```
 "https://github.com/pallets/flask"  or  "C:\path\to\repo"
        │
        ▼
 core/github_client.ensure_local_clone()      clone once into data/cache/clones/
        │                                     (a local path passes straight through)
        ▼
 core/git_client.GitClient.iter_commits()     newest-first commit dicts with
        │                                     per-file insertion/deletion stats
        ▼                                     (merge commits skipped — noisy diffs)
 pipeline/classify_commits.py                 is_bugfix flag via keyword match
        │                                     ("fix" matches "fixes", not "prefix")
        ▼
 core/db  store.save_commits(repo_key, ...)   cached — ALL four tools reuse this
        │
        ▼
 pipeline/extract_features.py                 one feature row per file:
        │                                     recency-decayed bug score, churn,
        │                                     authors, LOC/cyclomatic, ...
        ▼
 tools/bug_hotspot/scorer.py                  min-max normalize per component,
        │                                     weighted sum → ranked FileScores
        ▼
 tools/bug_hotspot/explainer.py               plain-English reasons per file
        │
        ▼
 store.save_hotspots(repo_key, rows)          read later by CLI / API / dashboard
```

The key architectural fact: **the cached commit history is the shared
substrate.** Tool 1 scores it, Tool 4 scores its messages, Tool 3 builds its
bug-diff similarity corpus from it, and the dashboard's activity/health
endpoints aggregate it — none of them re-read the repository once the cache
exists.

## Graceful degradation

Every heavy dependency is optional. Each subsystem probes for its preferred
backend at runtime and falls back transparently, printing a `[backend]` line
so every run states what produced its results.

| Subsystem | Preferred | Fallback | Selection logic |
|---|---|---|---|
| Storage | MongoDB | JSON files in `data/cache/` | `core/db.open_store()` — pings Mongo with an 800 ms timeout |
| Similarity (Tool 3) | sentence-transformers + ChromaDB | stdlib TF-IDF cosine (`LiteIndex`) | `core/embeddings.open_similarity_index()` |
| ML (Tool 1) | XGBoost second opinion | weighted score only | `load_model()` returns `None` if no trained model file |
| LLM (all tools) | LM Studio / OpenAI / Claude / Gemini | feature skipped with a clear message | provider's `.available()` check |
| Complexity metric | radon cyclomatic (Python files) | LOC only | `try: import radon` per file |

Forcing a backend is possible (`GITPULSE_STORE=mongo`,
`SIMILARITY_BACKEND=chroma`) — then an unavailable backend is a hard error
instead of a fallback.

A related pattern: **all heavy imports are lazy.** GitPython, pymongo,
PyGithub, the LLM SDKs, xgboost, chromadb — each is imported inside the
function that needs it. The pure-analysis modules (classifier, feature
extractor, scorers, report builders) are stdlib-only, which is what makes the
test suite runnable with zero dependencies installed.

## Entry points

| Entry point | What it is |
|---|---|
| `python cli.py` | Interactive menu (analyze / pull / train / commit-quality / profile / review-pr / test-llm / setup-indexes / config) |
| `python -m uvicorn api.main:app` | Web API on `127.0.0.1:8000`, Swagger at `/docs` |
| `scripts/run_analysis.py`, `scripts/pull_repo.py`, `scripts/setup_indexes.py` | Single-action interactive shortcuts around the same engine |
| `frontend/` → `npm run dev` | React dashboard (proxies `/api` to the FastAPI server) |

The CLI and the API call the **same** orchestration functions
(`core/analysis.run_hotspot_analysis`, `tools/*/runner.py`) — the API adds
nothing but HTTP framing, background-job bookkeeping, and the webhook.

## Directory layout

```
test_1/
├── cli.py                     # interactive CLI entry point
├── api/
│   ├── main.py                # FastAPI app factory + all routes
│   ├── auth.py                # v2 auth routes: signup/login, OAuth, session cookie
│   ├── jobs.py                # in-memory background-job registry
│   └── webhook.py             # GitHub PR webhook: HMAC verify + dispatch
├── config/settings.py         # .env-driven Settings dataclass
├── core/                      # shared services (see table above)
├── pipeline/
│   ├── fetch_commits.py       # git → classify → store
│   ├── classify_commits.py    # bug-fix keyword detection
│   ├── extract_features.py    # per-file feature engineering
│   ├── fetch_user_activity.py # GitHub user activity → normalized dict (Tool 2)
│   ├── build_bug_index.py     # bug-fix diffs → similarity index (Tool 3)
│   └── build_training_data.py # pooled multi-repo XGBoost training set
├── tools/
│   ├── bug_hotspot/           # Tool 1: scorer, explainer, dataset, normalize, ml_scorer
│   ├── commit_quality/        # Tool 4: scorer, reporter, suggester, runner
│   ├── dev_profiler/          # Tool 2: classifier, llm_analyzer, profile_builder, runner
│   └── pr_reviewer/           # Tool 3: risk_scorer, similarity, llm_summarizer,
│                              #         report_builder, runner
├── frontend/                  # React dashboard (Vite + Tailwind + Recharts)
├── scripts/                   # thin single-action wrappers
├── tests/                     # 11 network-free suites
├── docs/                      # this technical documentation
├── data/                      # runtime artifacts: cache/, models/, chroma/  (gitignore-able)
└── train_repos.txt            # repo list for optional XGBoost training
```
