# Changelog

All notable changes to GitPulse are documented here.
This project follows the milestone roadmap in `../GitPulse_Revised_Sections.md`.

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
