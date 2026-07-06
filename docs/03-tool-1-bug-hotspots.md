# 03 — Tool 1: Bug Hotspot Predictor

**Question it answers:** *which files in this repository are most likely to
break next?*

Orchestrated by `core/analysis.run_hotspot_analysis()` — used verbatim by the
CLI (`analyze`), the API (`POST /analyze`), and Tool 3 (which needs the
hotspot list for its file-risk check).

## Pipeline

```
target (path or URL)
  → ensure_local_clone            data/cache/clones/, reused across runs
  → load cached commits           (or pull + classify + cache on first run)
  → HEAD file metrics             LOC for every scored file; radon cyclomatic for .py
  → build_file_features           one row per file          [pipeline/extract_features.py]
  → score_files                   weighted, normalized score [tools/bug_hotspot/scorer.py]
  → explain_all                   plain-English reasons      [tools/bug_hotspot/explainer.py]
  → (optional) predict_scores     XGBoost second opinion     [tools/bug_hotspot/ml_scorer.py]
  → store.save_hotspots           persisted, readable via API
```

## Step 1 — Bug-fix classification (`pipeline/classify_commits.py`)

A commit is a *bug fix* if its message contains one of the configured keywords
(default `fix, bug, resolve, patch, hotfix, closes` — the SZZ starting point).
Matching is careful:

- Alphanumeric keywords compile to a **left word-boundary regex**:
  `fix` matches *fix / fixes / fixed / fixing* but **not** *prefix* or
  *postfix*; `patch` does not match *dispatch*.
- Keywords containing spaces or symbols (e.g. `closes #`) fall back to plain
  substring search.

Pure stdlib, `lru_cache`d compilation, fully unit-tested.

## Step 2 — Per-file features (`pipeline/extract_features.py`)

One pass over the classified commits accumulates, per file:

| Feature | Meaning |
|---|---|
| `bug_score` | **the headline feature** — Σ over bug-fix commits of `0.5^(age_days / halflife)`; a bug fixed yesterday counts ~1.0, one fixed `halflife` days ago (default 30) counts 0.5, one from a year ago ~0.0002 |
| `churn_window` | number of changes in the last `CHURN_WINDOW_DAYS` (default 30) |
| `churn_lines` | lifetime insertions + deletions |
| `authors` | count of distinct author emails |
| `bugfix_count` | raw bug-fix commit count |
| `last_change_days`, `last_was_bugfix` | recency signals (used by explainer + ML) |
| `loc`, `cyclomatic` | size/complexity at HEAD (`GitClient.file_metrics`) |

Two correctness gates:

- **Only files still present at HEAD are scored** (`existing_files` filter) —
  deleted files can't be hotspots.
- **Bug credit only goes to real source files** (`core/paths.is_code_file`).
  A `"fix session bug"` commit that also touches `README.md` or
  `pyproject.toml` still counts toward those files' churn, but not their bug
  history. This killed the v0.1 false positives where docs/config files
  ranked as top hotspots; it has a regression test.

## Step 3 — The weighted score (`tools/bug_hotspot/scorer.py`)

```
score = 0.40 · bug         (from bug_score)
      + 0.25 · churn       (from churn_window)
      + 0.15 · authors     (from authors)
      + 0.20 · complexity  (from loc)
```

Each component is **min–max normalized across the repo's files** (divided by
the repo max), so every component is 0..1 and the score is a *relative ranking
within that repository* — which is exactly what a hotspot list is. Weights
follow the defect-prediction literature (bug history strongest, then churn)
and live in `DEFAULT_WEIGHTS`.

This formula deliberately **replaces** a per-repo trained classifier: training
on one repo's history means tiny, imbalanced data and label leakage. The
formula needs no training, works on a 50-commit repo, and every score is
explainable.

## Step 4 — Explanations (`tools/bug_hotspot/explainer.py`)

Each `FileScore` gets up to 3 reasons, ordered by contribution — e.g.
`"9 bug-fix commit(s) (recency-weighted 3.4)"`, `"6 change(s) in last 30d"`,
`"7 distinct authors"`, `"cyclomatic complexity 42"`. These render in the CLI
table, the stored report, and the dashboard.

## Optional: the XGBoost "second opinion"

A trained model that runs *alongside* the formula (never instead of it). When
`data/models/hotspot_xgb.json` exists, the results table gains an `ML` column
and flags files where formula and model disagree. Three ideas make the trained
model legitimate:

1. **Temporal labeling — no leakage** (`tools/bug_hotspot/dataset.py`).
   For several cutoff dates per repo: features are computed only from commits
   *before* the cutoff (reusing the exact same extractor as the live scorer);
   the label is whether the file received a bug fix in the window *after* it
   (`ML_LABEL_WINDOW_DAYS`, default 90). Future bugs never leak into features.

2. **Per-repo percentile normalization** (`tools/bug_hotspot/normalize.py`).
   Every feature becomes its percentile rank *within its own snapshot*, so
   "90th-percentile churn" means the same thing in a 100-commit JS repo and a
   5,000-commit Python one. Features are language-agnostic process metrics
   plus LOC — no language-specific complexity — so the model transfers across
   languages. Bonus: no scaler to persist, no train/serve skew.

3. **Honest evaluation** (`tools/bug_hotspot/ml_scorer.py`). Reports
   **cross-repo AUC** (GroupKFold grouped by repo — measures generalization to
   unseen repos, not memorization) and **held-out-language AUC** (train
   without a language, test on it). With fewer than `ML_MIN_POSITIVES`
   positive examples it refuses to train and says so (`reliable: False`).

Training: list repos in `train_repos.txt` (`<url>[,<language>]` per line),
run CLI option 3. `pipeline/build_training_data.py` clones each repo, builds
the pooled snapshot dataset, trains, evaluates, and saves the model.
Needs `xgboost scikit-learn numpy`; without them (or a model file) the whole
ML path silently stays off.

## Output

`store.save_hotspots(repo_key, rows)` persists the top rows (at least 50) as
dicts: `{path, score, components, raw, reasons, ml_prob}`. Read back via
CLI, `GET /repos/{key}/hotspots`, and Tool 3's file-risk check.
