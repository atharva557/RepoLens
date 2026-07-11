"""Per-repo (per-snapshot) percentile normalization.

The single most important trick for pooling repos across sizes *and* languages:
convert each raw feature into its **percentile rank within its own snapshot**.

Why this matters:
  - 50 changes is extreme in a 100-commit repo but ordinary in a 5,000-commit one.
    Raw counts would teach the model "big repo vs small repo" instead of
    "risky vs safe." Percentile rank makes "90th-percentile churn" mean the same
    thing everywhere.
  - It also neutralizes Python-vs-JS magnitude differences (e.g. LOC), so a model
    trained on one language transfers to another.
  - It is self-contained per snapshot, so there is **no scaler to persist** and no
    train/serve skew: the same transform runs at training and prediction time.

Pure stdlib.
"""
from __future__ import annotations

from collections import defaultdict

# the language-agnostic, git-derived features the ML model consumes (LOC only —
# no language-specific cyclomatic complexity, so this transfers across languages)
ML_FEATURES = [
    "commits",
    "churn_window",
    "churn_lines",
    "authors",
    "bugfix_count",
    "bug_score",
    "last_change_days",
    "loc",
]


def _percentile_ranks(values: list[float]) -> list[float]:
    """Map each value to its percentile rank in (0, 1) using midpoint ranking.

    rank(v) = (#strictly_less + 0.5 * #equal) / n  -> stable, ties share a rank,
    single-element groups map to 0.5 (neutral).
    """
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [0.5]
    order = sorted(values)
    # precompute counts via binary-search-free approach (n is small per snapshot)
    less = {}
    equal = {}
    for v in set(values):
        less[v] = sum(1 for x in order if x < v)
        equal[v] = sum(1 for x in order if x == v)
    return [(less[v] + 0.5 * equal[v]) / n for v in values]


def percentile_normalize(
    rows: list[dict],
    *,
    group_key: str = "snapshot_id",
    features: list[str] = ML_FEATURES,
    suffix: str = "_pr",
) -> list[dict]:
    """Add `<feature>{suffix}` columns holding per-group percentile ranks.

    Mutates and returns `rows`. Each group (one repo at one point in time) is
    normalized independently.
    """
    groups: dict[object, list[dict]] = defaultdict(list)
    for r in rows:
        groups[r.get(group_key)].append(r)

    for grp in groups.values():
        for feat in features:
            ranks = _percentile_ranks([float(r.get(feat) or 0) for r in grp])
            for r, pr in zip(grp, ranks):
                r[f"{feat}{suffix}"] = round(pr, 6)
    return rows


def feature_matrix(rows: list[dict], features: list[str] = ML_FEATURES, suffix: str = "_pr"):
    """Return X (list of feature vectors) from normalized rows."""
    return [[r.get(f"{f}{suffix}", 0.0) for f in features] for r in rows]
