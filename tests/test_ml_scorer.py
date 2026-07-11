"""Tests for the XGBoost "second opinion" pipeline.

Covers the pure-logic pieces (percentile normalization, temporal no-leakage
labeling) with no dependencies, plus an end-to-end train/predict on synthetic
data when xgboost/scikit-learn are installed (otherwise that test self-skips).

    python tests/test_ml_scorer.py
"""
import os
import random
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.classify_commits import classify_commits
from tools.bug_hotspot.dataset import make_dataset
from tools.bug_hotspot.normalize import ML_FEATURES, percentile_normalize

NOW = datetime(2026, 6, 29, tzinfo=timezone.utc)


def _commit(days_ago, msg, files):
    return {
        "sha": f"s{days_ago}",
        "author": "alice",
        "email": "alice@example.com",
        "date": NOW - timedelta(days=days_ago),
        "message": msg,
        "files": [{"path": p, "insertions": 4, "deletions": 1} for p in files],
    }


def test_percentile_normalize():
    rows = [
        {"snapshot_id": "g", "churn_window": v, **{k: 0 for k in ML_FEATURES if k != "churn_window"}}
        for v in [0, 5, 10, 100]
    ]
    percentile_normalize(rows)
    prs = [r["churn_window_pr"] for r in rows]
    assert prs == sorted(prs)          # order preserved
    assert all(0 <= p <= 1 for p in prs)
    assert prs[-1] > prs[0]
    # single-element group -> neutral 0.5
    solo = [{"snapshot_id": "x", **{k: 9 for k in ML_FEATURES}}]
    percentile_normalize(solo)
    assert solo[0]["churn_window_pr"] == 0.5
    print("  ok: percentile normalization")


def test_temporal_labeling_no_leakage():
    # leak.py is created early, then bug-fixed only RECENTLY (after the cutoffs'
    # feature window). It must be labeled positive, yet its feature-side bug_score
    # must be 0 -- proving the future fix did not leak into the features.
    commits = [
        _commit(400, "add leak module", ["leak.py"]),
        _commit(380, "add core", ["core.py"]),
        _commit(300, "update core", ["core.py"]),
        _commit(200, "refactor core", ["core.py"]),
        _commit(10, "fix leak crash", ["leak.py"]),   # the future bug fix
    ]
    classify_commits(commits)
    rows = make_dataset(
        commits, "repo", language="python",
        n_snapshots=3, label_window_days=90, churn_window_days=30, halflife_days=30,
    )
    assert rows, "expected snapshot rows"
    for r in rows:  # schema check
        assert {"repo", "language", "snapshot_id", "label", *ML_FEATURES} <= set(r)

    leak_pos = [r for r in rows if r["path"] == "leak.py" and r["label"] == 1]
    assert leak_pos, "leak.py should be labeled positive from a future bug fix"
    assert all(r["bug_score"] == 0 for r in leak_pos), \
        "no leakage: features must not see the future bug fix"
    print("  ok: temporal labeling has no leakage")


def _synthetic_dataset(n_repos=4, files_per=70, seed=0):
    rng = random.Random(seed)
    langs = ["python", "javascript", "go"]
    rows = []
    for ri in range(n_repos):
        repo = f"repo{ri}"
        lang = langs[ri % len(langs)]
        for fi in range(files_per):
            churn = rng.randint(0, 20)
            authors = rng.randint(1, 8)
            bug = rng.random() * 3
            loc = rng.randint(10, 800)
            risk = 0.5 * (bug / 3) + 0.3 * (churn / 20) + 0.2 * (authors / 8)
            label = 1 if risk + rng.uniform(-0.12, 0.12) > 0.6 else 0
            rows.append({
                "repo": repo, "language": lang, "snapshot_id": f"{repo}@s",
                "path": f"{repo}/f{fi}.py",
                "commits": churn + rng.randint(0, 10),
                "churn_window": churn, "churn_lines": churn * 7,
                "authors": authors, "bugfix_count": int(bug), "bug_score": bug,
                "last_change_days": rng.randint(0, 200), "loc": loc,
                "label": label,
            })
    return rows


def test_train_and_predict_end_to_end():
    try:
        import xgboost  # noqa: F401
        import sklearn  # noqa: F401
    except ImportError:
        print("  skip: xgboost/scikit-learn not installed")
        return
    from tools.bug_hotspot.ml_scorer import predict_scores, train

    rows = _synthetic_dataset()
    model, report = train(rows, min_positives=5)
    assert report["positives"] > 0 and report["negatives"] > 0
    # the planted signal should be learnable above chance
    assert report["auc_cross_repo"] is None or report["auc_cross_repo"] > 0.65, report
    assert len(report["importances"]) == len(ML_FEATURES)

    # predict on fresh "live" feature rows
    feature_rows = [
        {"path": "hot.py", "commits": 30, "churn_window": 20, "churn_lines": 140,
         "authors": 8, "bugfix_count": 3, "bug_score": 2.8, "last_change_days": 2, "loc": 700},
        {"path": "cold.py", "commits": 1, "churn_window": 0, "churn_lines": 2,
         "authors": 1, "bugfix_count": 0, "bug_score": 0.0, "last_change_days": 180, "loc": 30},
    ]
    probs = predict_scores(model, feature_rows)
    assert set(probs) == {"hot.py", "cold.py"}
    assert all(0.0 <= p <= 1.0 for p in probs.values())
    assert probs["hot.py"] > probs["cold.py"], probs
    print(f"  ok: train+predict end-to-end (AUC={report['auc_cross_repo']})")


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    print(f"running {len(fns)} test(s)...")
    for fn in fns:
        fn()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    _run_all()
