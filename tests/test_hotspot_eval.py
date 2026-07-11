"""Tests for the v0.5 temporal hold-out evaluation of the hotspot score.

Synthetic history, no git/network/DB. The scenario is built so the methods
disagree: `a.py` carries the bug history, `b.py` carries the recent churn —
so the weighted and bug-only rankings should find the future bug (in a.py)
at rank 1, while churn-only should not.

    python tests/test_hotspot_eval.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.bug_hotspot.evaluate import (
    evaluate_repo,
    evaluate_snapshot,
    format_report,
    WEIGHT_SETS,
)

NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)


def _c(days_ago, path, *, bug=False, author="alice"):
    return {
        "sha": f"sha{days_ago}{path}",
        "author": author, "email": f"{author}@x",
        "date": NOW - timedelta(days=days_ago),
        "message": "Fix crash" if bug else "Add feature",
        "is_bugfix": bug,
        "files": [{"path": path, "insertions": 5, "deletions": 1}],
    }


def _history():
    cutoff = NOW - timedelta(days=90)
    past = [
        # a.py: the bug magnet (fixes older than the 30d churn window)
        _c(140, "a.py", bug=True), _c(150, "a.py", bug=True), _c(160, "a.py", bug=True),
        # b.py: heavy recent churn, zero bug history
        _c(95, "b.py"), _c(96, "b.py"), _c(97, "b.py"), _c(98, "b.py"), _c(99, "b.py"),
        # docs "fix" in the past: file exists but must never be a code label
        # (kept outside the churn window so it doesn't disturb churn ranking)
        _c(130, "README.md", bug=True),
    ]
    future = [
        _c(60, "a.py", bug=True),        # the label: a.py breaks again
        _c(55, "new.py", bug=True),      # born after the cutoff -> unpredictable
        _c(50, "README.md", bug=True),   # docs-only fix -> gated out of truth
    ]
    return past + future, cutoff


def test_snapshot_truth_set_is_gated():
    commits, cutoff = _history()
    snap = evaluate_snapshot(commits, cutoff, label_window_days=60, ks=(1, 2))
    # truth is exactly {a.py}: new.py unseen before cutoff, README.md not code
    assert snap["positives"] == 1
    assert snap["files_scored"] == 3            # a.py, b.py, README.md
    assert snap["base_rate"] == round(1 / 3, 4)
    print("  ok: truth gated to pre-existing code files")


def test_methods_disagree_as_designed():
    commits, cutoff = _history()
    snap = evaluate_snapshot(commits, cutoff, label_window_days=60, ks=(1, 2))
    m = snap["methods"]
    assert set(m) == set(WEIGHT_SETS)
    # bug history dominates the weighted score -> a.py at rank 1
    assert m["weighted"]["precision@1"] == 1.0
    assert m["bug history only"]["precision@1"] == 1.0
    # churn ranks b.py first -> misses the actual future bug at rank 1
    assert m["churn only"]["precision@1"] == 0.0
    # by rank 2 churn-only has caught a.py -> recall recovers
    assert m["churn only"]["recall@2"] == 1.0
    print("  ok: weighted/bug find the future bug at rank 1; churn does not")


def test_unusable_snapshots_return_none():
    commits, cutoff = _history()
    # cutoff before all history -> no features
    assert evaluate_snapshot(commits, NOW - timedelta(days=400)) is None
    # window with no future bug fixes -> no truth -> None
    only_past = [c for c in commits if c["date"] <= cutoff]
    assert evaluate_snapshot(only_past, cutoff, label_window_days=60) is None
    print("  ok: snapshots without history or positives are skipped")


def test_repo_aggregation_and_report():
    commits, _ = _history()
    report = evaluate_repo(commits, n_snapshots=3, label_window_days=60, ks=(1, 2))
    assert report["usable_snapshots"] >= 1
    assert set(report["summary"]) == set(WEIGHT_SETS)
    for m in report["summary"].values():
        for v in m.values():
            assert 0.0 <= v <= 1.0
    # one positive across snapshots is thin data - the report must say so
    assert report["reliable"] is False

    text = format_report(report, "owner/repo", ks=(1, 2))
    assert "weighted" in text and "churn only" in text
    assert "base rate" in text
    assert "thin data" in text
    print("  ok: repo aggregation + honest formatting")


def _run_all():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    print(f"running {len(fns)} test(s)...")
    for fn in fns:
        fn()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    _run_all()
