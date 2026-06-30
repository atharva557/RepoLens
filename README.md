# GitPulse — v0.1 (Foundation)

GitHub analytics & intelligence platform. This is the **v0.1 Foundation**
milestone: the data pipeline plus **Tool 1 — Bug Hotspot Predictor**, exposed
through a CLI.

It follows the *revised* architecture (see `../GitPulse_Revised_Sections.md`):

- **MongoDB** as the primary datastore (with a transparent JSON-file fallback so
  it runs before Mongo is installed).
- A **recency-weighted risk score** instead of a trained XGBoost classifier —
  no training data, works on small repos, fully explainable.

## What's implemented in v0.1

| Roadmap item (v0.1) | Where |
|---|---|
| GitHub/git client with MongoDB caching | `core/git_client.py`, `core/github_client.py`, `core/db.py` |
| Commit classification (bug-fix keyword detection) | `pipeline/classify_commits.py` |
| Bug Hotspot Predictor — recency-weighted scorer | `tools/bug_hotspot/scorer.py`, `explainer.py` |
| Feature engineering | `pipeline/extract_features.py` |
| Basic CLI output | `cli.py` (+ thin `scripts/`) |

Tools 2–4 (Dev Profiler, PR Review, Commit Quality), the FastAPI API, and the
React dashboard arrive in later milestones (v0.2–v0.4).

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
GitPulse v0.1 - Bug Hotspot foundation
======================================
  1) analyze        rank bug-hotspot files in a repo
  2) pull           fetch & cache commit history
  3) setup-indexes  create MongoDB indexes
  4) config         show resolved settings
  5) quit

Select an option (1-5): 1
Repo path or URL: /path/to/some/repo
Rows to display [15]:
Re-pull history (ignore cache)? [y/N]:
Max commits to scan (0 = all) [0]:
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

## Run the tests

The core logic is pure stdlib, so the tests run with no dependencies installed:

```bash
python tests/test_bug_hotspot.py     # weighted scorer, classifier, features
python tests/test_ml_scorer.py       # normalization, no-leakage labeling, train/predict
# or:  pytest tests/
```

## Project layout (v0.1 subset)

```
test_1/
├── cli.py                     # CLI entry point
├── config/settings.py         # .env-driven configuration
├── core/
│   ├── git_client.py          # GitPython: commit history + file metrics
│   ├── github_client.py       # clone remote URLs -> local path
│   ├── db.py                  # MongoStore + JsonStore fallback
│   └── analysis.py            # end-to-end orchestration
├── pipeline/
│   ├── fetch_commits.py       # git -> classify -> cache
│   ├── classify_commits.py    # bug-fix keyword detection
│   ├── extract_features.py    # per-file feature engineering
│   └── build_training_data.py # pool repos -> labeled dataset -> train (XGBoost)
├── tools/bug_hotspot/
│   ├── scorer.py              # recency-weighted risk score (primary)
│   ├── explainer.py           # plain-English reasons
│   ├── dataset.py             # temporal-snapshot labeling (no leakage)
│   ├── normalize.py           # per-repo percentile normalization
│   └── ml_scorer.py           # XGBoost train / evaluate / predict (second opinion)
├── train_repos.txt            # list of repos to train the ML model on
├── scripts/                   # thin wrappers (setup_indexes, pull_repo, run_analysis)
└── tests/
    ├── test_bug_hotspot.py
    └── test_ml_scorer.py
```
