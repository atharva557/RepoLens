# GitPulse — v0.2 (Intelligence Layer)

GitHub analytics & intelligence platform, exposed through an interactive CLI.
See [CHANGELOG.md](CHANGELOG.md) for the per-version breakdown.

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

The PR Review Assistant (Tool 3), FastAPI API, and React dashboard arrive in
later milestones (v0.3–v0.4).

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

## Quick start

```bash
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
GitPulse - GitHub Analytics & Intelligence
==========================================
  1) analyze        rank bug-hotspot files (+ XGBoost second opinion if trained)
  2) pull           fetch & cache commit history
  3) train          train the XGBoost second-opinion model (from train_repos.txt)
  4) commit-quality score commit messages (+ LLM rewrites)
  5) profile        build a developer skill profile for a GitHub user
  6) test-llm       check the configured LLM provider
  7) setup-indexes  create MongoDB indexes
  8) config         show resolved settings
  9) quit
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

> Needs `pip install xgboost scikit-learn numpy`. Without them, GitPulse runs
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

Check it from the menu (**option 6, `test-llm`**) — it reports the provider and
sends a one-line test prompt.

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

## Run the tests

The core logic is pure stdlib, so the tests run with no dependencies installed:

```bash
python tests/test_bug_hotspot.py     # weighted scorer, classifier, features
python tests/test_ml_scorer.py       # normalization, no-leakage labeling, train/predict
python tests/test_llm.py             # provider factory + FakeProvider
python tests/test_commit_quality.py  # message scorer, reporter, suggester
python tests/test_dev_profiler.py    # developer classifier, profile assembly
# or:  pytest tests/
```

## Project layout (v0.1 subset)

```
test_1/
├── cli.py                     # CLI entry point
├── config/settings.py         # .env-driven configuration
├── core/
│   ├── git_client.py          # GitPython: commit history + file metrics + diffs
│   ├── github_client.py       # local clones + GitHubAPI (per-user activity)
│   ├── db.py                  # MongoStore + JsonStore fallback (+ generic reports)
│   ├── llm.py                 # pluggable LLM provider (local/openai/claude/gemini)
│   └── analysis.py            # bug-hotspot orchestration
├── pipeline/
│   ├── fetch_commits.py       # git -> classify -> cache
│   ├── fetch_user_activity.py # GitHub user activity -> normalized dict (Tool 2)
│   ├── classify_commits.py    # bug-fix keyword detection
│   ├── extract_features.py    # per-file feature engineering
│   └── build_training_data.py # pool repos -> labeled dataset -> train (XGBoost)
├── tools/
│   ├── bug_hotspot/           # Tool 1: scorer, explainer, dataset, normalize, ml_scorer
│   ├── commit_quality/        # Tool 4: scorer, suggester, reporter, runner
│   └── dev_profiler/          # Tool 2: classifier, llm_analyzer, profile_builder, runner
├── train_repos.txt            # list of repos to train the ML model on
├── scripts/                   # thin wrappers (setup_indexes, pull_repo, run_analysis)
└── tests/
    ├── test_bug_hotspot.py    test_ml_scorer.py    test_llm.py
    └── test_commit_quality.py test_dev_profiler.py
```
