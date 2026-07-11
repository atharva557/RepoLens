# RepoLens — Project Overview

**GitHub Analytics & Intelligence Platform** · Semester-4 Project · Atharva Shah

RepoLens (formerly GitPulse) analyzes a repository's git history to answer questions maintainers
actually have: *Which files are most likely to break next? Who writes what kind
of code? Is this pull request risky? Are our commit messages any good?*

It is built as four analysis tools on one shared data pipeline, exposed through
an interactive CLI and a FastAPI web backend, with results persisted in MongoDB.

| | |
|---|---|
| **Codebase** | ~3,800 lines of Python (~3,000 excl. tests) across 40+ modules |
| **Tests** | 41 tests in 8 suites — all network-free, all passing |
| **Status** | v0.4 — all four tools + API layer shipped; React dashboard next |
| **Stack** | Python 3.13 · GitPython · MongoDB · FastAPI · XGBoost (optional) · pluggable LLM (optional) |

---

## 1. The four tools

| # | Tool | Question it answers | Core technique |
|---|------|--------------------|----------------|
| 1 | **Bug Hotspot Predictor** | Which files will break next? | Recency-weighted risk score over git history + optional XGBoost second opinion |
| 2 | **Developer Skill Profiler** | What kind of developer is @user? | Rule-based activity classification across a user's public GitHub history |
| 3 | **PR Review Assistant** | Is this pull request risky? | Hotspot membership + mechanical checks + diff-similarity to past bug fixes + LLM summary |
| 4 | **Commit Message Quality Analyzer** | Are our commit messages useful? | Rule-based 0–10 scoring + optional LLM rewrites from the actual diff |

Every prediction ships with a plain-English reason — explainability over
black-box accuracy is the project's founding principle.

---

## 2. Architecture

```
                        ┌─────────────────────────────────────┐
   interfaces           │  cli.py (interactive menu)          │
                        │  api/  (FastAPI: reads, job         │
                        │        triggers, GitHub PR webhook) │
                        └──────────────┬──────────────────────┘
                                       │
                        ┌──────────────▼──────────────────────┐
   tools                │  tools/bug_hotspot    tools/dev_profiler
                        │  tools/pr_reviewer    tools/commit_quality
                        └──────────────┬──────────────────────┘
                                       │
                        ┌──────────────▼──────────────────────┐
   shared pipeline      │  pipeline/  fetch → classify →      │
                        │             extract features        │
                        └──────────────┬──────────────────────┘
                                       │
                        ┌──────────────▼──────────────────────┐
   core services        │  core/git_client    (GitPython)     │
                        │  core/github_client (PyGithub)      │
                        │  core/db            (Mongo + JSON)  │
                        │  core/llm           (4 providers)   │
                        │  core/embeddings    (Chroma + Lite) │
                        └─────────────────────────────────────┘
```

**Data flow (Tool 1 example):** clone/read repo → pull commit history with
per-file stats → classify bug-fix commits (keyword detection with word
boundaries, the SZZ starting point) → aggregate per-file features → score →
explain → persist. The cached history is reused by all four tools.

### Graceful degradation everywhere

A deliberate design theme: every heavy dependency is optional, and the system
picks the best available backend at runtime.

| Layer | Preferred | Fallback | Trigger |
|---|---|---|---|
| Storage | MongoDB | JSON file cache | Mongo unreachable |
| Similarity (Tool 3) | sentence-transformers + ChromaDB | stdlib TF-IDF cosine index | deps not installed |
| ML (Tool 1) | XGBoost second opinion | weighted score only | no trained model |
| LLM (all tools) | LM Studio / OpenAI / Claude / Gemini | feature skipped with a clear message | not configured |
| Complexity metric | radon cyclomatic (Python) | LOC | radon missing / non-Python |

The result: `python cli.py` works on a bare machine with only GitPython
installed, and silently upgrades as infrastructure is added.

---

## 3. Key design decisions (and why)

These deviate from the original project guide, deliberately:

1. **The hotspot score is a transparent formula, not a trained classifier.**
   Training XGBoost on a single repo's history suffers from label leakage and
   tiny, imbalanced data — the model would memorize, not predict. The
   recency-weighted formula needs no training, works on small repos, and every
   score is explainable.

2. **XGBoost survives as an optional "second opinion"** — trained once across
   *pooled* repos with strict temporal labeling (features from before a cutoff,
   labels from after it — no leakage), per-repo percentile normalization (so
   "90th-percentile churn" means the same in a 100-commit repo and a
   5,000-commit one, and models transfer across languages), and honest
   evaluation (cross-repo GroupKFold AUC + held-out-language AUC; the model
   flags itself `reliable: False` on thin data rather than pretending).

3. **The LLM is a pluggable provider, always optional.** `LLM_PROVIDER` selects
   LM Studio (local, default), OpenAI, Claude, or Gemini. Every rule-based
   feature works with no LLM at all; the LLM only adds rewrites and summaries.

4. **MongoDB replaces SQLite** — reports are document-shaped — with a
   transparent JSON fallback so nothing blocks on infrastructure.

5. **Bug history is credited only to source files.** A "fix …" commit that also
   touches `README.md` or a `.toml` no longer marks those as hotspots
   (a v0.1 false-positive found and fixed in v0.3, with a regression test).

---

## 4. How the hotspot score works (Tool 1)

For every file still present at HEAD:

```
score = 0.40 · bug        Σ over bug-fix commits of 0.5^(age_days / 30)
      + 0.25 · churn      changes in the last 30 days
      + 0.15 · authors    distinct authors who touched the file
      + 0.20 · complexity LOC (radon cyclomatic shown for Python)
```

Recent bugs dominate; ancient ones decay exponentially. Each component is
normalized within the repo, so the score is a *relative ranking* — exactly what
a hotspot list is. Weights follow the defect-prediction literature (bug history
strongest, then churn) and are tunable via `.env`.

---

## 5. Validation on real repositories

Run against well-known open-source projects (400 newest commits each):

**Tool 1 — the top hotspots are the files maintainers would actually name:**

| Repo | History analyzed | #1 hotspot | Why |
|---|---|---|---|
| `pallets/flask` | 238 commits, 53 bug-fix | `src/flask/app.py` (0.586) | 4 bug-fixes, cyclomatic 167 — the core class |
| `expressjs/express` | 390 commits, 140 bug-fix | `lib/response.js` (0.679) | 21 bug-fix commits, 23 authors, latest change was a fix |
| `psf/requests` | 163 commits, 22 bug-fix | `src/requests/models.py` (0.855) | the request/response model core |

The v0.3 cleanup is visible in the results: Express's `History.md` and
`package.json` rank on churn/authors only, with zero bug-fix credit.

**Tool 4 — commit quality:** Express averages **8.02/10** (341 good / 13 weak
of 390); its weakest messages are version-bump commits like `"4.18.2"`,
correctly flagged *short / vague / no context*. Flask averages **7.17/10**,
with "no issue reference" the dominant gap (232 of 238 commits).

**API end-to-end:** `POST /analyze` on `psf/requests` returned `202` with a job
id; polling `/jobs/{id}` returned the completed ranking; the persisted report
was then readable at `GET /repos/psf/requests/hotspots`.

---

## 6. Tool details

### Tool 2 — Developer Skill Profiler
Builds a per-user profile across their public repos (PyGithub, rate-limit
capped): a percentage split over **Bug Fixer / Feature Builder / Refactorer /
Reviewer / Documentation Writer / Architect** from deterministic signals
(bug-fix share, file-creation share, deletion-heavy commits, review counts,
docs ratio, wide commits + dependency-file edits), plus top languages,
commit-message quality (reuses Tool 4's scorer), review participation, and an
optional LLM read of their PR descriptions.

### Tool 3 — PR Review Assistant
For `owner/repo#N`, produces a pre-review markdown report before any human
looks: **file risk** (does the PR touch top-10 hotspots from Tool 1?),
**missing tests** (source changed, no tests touched), **change focus** (many
files across many areas / large diff), **similarity to past bugs** (the PR diff
embedded and cosine-compared against the repo's past bug-fix diffs), and an
**AI summary** of what the diff actually does. Optionally posts the report as a
PR comment.

### Tool 4 — Commit Message Quality Analyzer
Scores each message 0–10 across five dimensions (subject length, vagueness,
imperative verb, "why" context, issue reference), aggregates per-contributor
health, monthly trends and the most common bad patterns, and can ask the LLM to
rewrite the worst messages — from the *actual diff*, not just the old message.

---

## 7. The API layer (v0.4)

A thin FastAPI backend over the same engine — reads come from the store,
analyses run as background jobs:

| Endpoint | Purpose |
|---|---|
| `GET /repos/{key}/hotspots` · `/commit-quality` · `/pr-reviews/{n}` · `GET /profiles/{user}` | read stored reports |
| `POST /analyze` · `/commit-quality` · `/profiles/{user}` · `/repos/{o}/{r}/pr-reviews/{n}` | trigger runs → `202` + job id |
| `GET /jobs/{id}` | background-job status + result summary |
| `POST /webhook/github` | GitHub PR webhook → auto-runs Tool 3 on PR open/update |
| `GET /health` · `/config` · `/docs` | liveness, masked settings, Swagger UI |

The webhook is HMAC-verified (`X-Hub-Signature-256` against
`GITHUB_WEBHOOK_SECRET`, disabled without it), reviews PRs on
`opened / reopened / synchronize / ready_for_review`, and posting the report
back as a PR comment is explicitly opt-in. Job state lives in a bounded
in-memory registry; engine errors are captured per-job and cannot crash the
server.

---

## 8. Testing

41 tests across 8 suites, each runnable standalone (`python tests/test_x.py`)
or via pytest. **All network-free**: an in-process `FakeProvider` stands in for
the LLM, a `FakeStore` for the database, synthetic commit histories for git,
and stubbed engine entry points for the API. Coverage includes:

- classifier word-boundary behavior ("fix" ≠ "prefix"), recency weighting,
  feature extraction, explanations, and the docs/config false-positive regression
- ML: percentile normalization, **no-leakage temporal labeling**, end-to-end
  train/predict (AUC ≈ 0.95 on synthetic signal)
- LLM provider factory + graceful-unavailability paths
- commit-message scoring dimensions, report aggregation, suggester fallbacks
- profiler signals and profile assembly
- similarity index ranking + backend fallback
- PR risk checks, spec parsing, report building
- API: read layer, job lifecycle (success + failure), token gates, webhook
  security (secret gate, HMAC verification, event/action filtering, dispatch)

---

## 9. Milestones

| Version | Delivered | Highlights |
|---|---|---|
| **v0.1** — Foundation | 2026-06-30 | git/GitHub client, Mongo+JSON storage, bug-fix classification, Tool 1 + explanations, interactive CLI, XGBoost second opinion (pulled forward) |
| **v0.2** — Intelligence | 2026-06-30 | pluggable LLM provider layer, Tool 4, Tool 2 |
| **v0.3** — PR Review | 2026-07-01 | diff-similarity engine (Chroma/Lite), Tool 3, PR-comment posting, Tool 1 false-positive cleanup |
| **v0.4** — API | 2026-07-02 | FastAPI backend, background jobs, HMAC-verified PR webhook, 8th test suite; audit fixed 5 bugs (incl. a Tool 4 crash and a Mongo timezone crash) |

**Remaining roadmap:** React dashboard (Tailwind + shadcn/ui + Recharts) on top
of the API (completes v0.4), then a v0.5 evaluation pass — temporal hold-out
validation of the hotspot score (precision@k on a future window the score never
saw), which also allows tuning the formula weights against data.

---

## 10. Running it

```bash
cd test_1
pip install -r requirements.txt        # or start with just GitPython
python cli.py                          # interactive menu, 10 options
```

```
1) analyze         rank bug-hotspot files (+ ML second opinion if trained)
2) pull            fetch & cache commit history
3) train           train the XGBoost second-opinion model
4) commit-quality  score commit messages (+ LLM rewrites)
5) profile         developer skill profile for a GitHub user
6) review-pr       pre-review report for a pull request
7) test-llm        check the configured LLM provider
8) setup-indexes   create MongoDB indexes
9) config          show resolved settings
```

Web API: `python -m uvicorn api.main:app` → Swagger docs at
`http://127.0.0.1:8000/docs`.

Configuration is `.env`-driven (see `.env.example`); sensible defaults work
with no configuration at all. `GITHUB_TOKEN` enables Tools 2/3;
an LLM provider enables rewrites/summaries; everything else runs offline.
