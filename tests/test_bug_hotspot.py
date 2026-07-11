"""Unit tests for the v0.1 Bug Hotspot foundation.

These exercise the pure-logic core (classification, feature extraction,
scoring, explanation) with synthetic commit data — no git, MongoDB, or network
required. Run directly:

    python tests/test_bug_hotspot.py

or under pytest:

    pytest tests/test_bug_hotspot.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.classify_commits import classify_commits, is_bugfix
from pipeline.extract_features import build_file_features
from tools.bug_hotspot.explainer import explain_all
from tools.bug_hotspot.scorer import score_files

NOW = datetime(2026, 6, 29, tzinfo=timezone.utc)


def _commit(sha, days_ago, msg, files, author="alice"):
    return {
        "sha": sha,
        "author": author,
        "email": f"{author}@example.com",
        "date": NOW - timedelta(days=days_ago),
        "message": msg,
        "files": [{"path": p, "insertions": 5, "deletions": 2} for p in files],
    }


def test_classification_word_boundaries():
    assert is_bugfix("Fix null pointer in session")
    assert is_bugfix("fixes the crash")           # prefix match -> fixes
    assert is_bugfix("hotfix for prod")
    assert is_bugfix("closes #142")
    assert not is_bugfix("add prefix to ids")     # 'prefix' must NOT match 'fix'
    assert not is_bugfix("dispatch new events")   # 'dispatch' must NOT match 'patch'
    assert not is_bugfix("update README")
    assert not is_bugfix("")
    print("  ok: classification word-boundaries")


def test_recency_weighting_ranks_recent_bugs_higher():
    # same number of bug fixes, different recency -> recent file scores higher
    commits = [
        _commit("a1", 2, "fix crash", ["recent.py"]),
        _commit("a2", 5, "fix overflow", ["recent.py"]),
        _commit("b1", 300, "fix typo", ["old.py"]),
        _commit("b2", 320, "fix race", ["old.py"]),
    ]
    classify_commits(commits)
    feats = build_file_features(commits, as_of=NOW, churn_window_days=30, halflife_days=30)
    scores = score_files(feats)
    by = {s.path: s for s in scores}
    assert scores[0].path == "recent.py", [s.path for s in scores]
    assert by["recent.py"].score > by["old.py"].score
    # the decayed bug score of the ancient file is a tiny fraction of the recent one
    assert by["recent.py"].raw["bug_score"] > 10 * by["old.py"].raw["bug_score"]
    print("  ok: recency weighting ranks recent bugs higher")


def test_bug_history_beats_equal_recency_no_bugs():
    # two files changed equally recently; the one with bug history ranks higher
    commits = [
        _commit("a1", 3, "fix login bug", ["buggy.py"]),
        _commit("c1", 3, "add docs", ["clean.py"]),
    ]
    classify_commits(commits)
    feats = build_file_features(commits, as_of=NOW)
    scores = score_files(feats)
    by = {s.path: s for s in scores}
    assert by["buggy.py"].score > by["clean.py"].score
    print("  ok: bug history beats equal-recency no-bug file")


def test_features_and_explanations():
    commits = [
        _commit("a1", 3, "fix auth bug", ["auth.py"], author="alice"),
        _commit("a2", 10, "fix session expiry", ["auth.py"], author="bob"),
        _commit("a3", 20, "refactor auth", ["auth.py"], author="carol"),
    ]
    classify_commits(commits)
    feats = build_file_features(
        commits, as_of=NOW, churn_window_days=30, halflife_days=30,
        metrics_by_file={"auth.py": {"loc": 120, "cyclomatic": 18}},
    )
    row = next(f for f in feats if f["path"] == "auth.py")
    assert row["commits"] == 3
    assert row["authors"] == 3
    assert row["bugfix_count"] == 2
    assert row["bug_score"] > 0
    assert row["loc"] == 120 and row["cyclomatic"] == 18

    scores = explain_all(score_files(feats))
    reasons = scores[0].reasons
    assert any("bug-fix" in r for r in reasons), reasons
    assert any("authors" in r for r in reasons), reasons
    print("  ok: features and explanations")


def test_empty_input_is_safe():
    assert score_files([]) == []
    assert build_file_features([], as_of=NOW) == []
    print("  ok: empty input is safe")


def test_bug_credit_only_for_code_files():
    # a bug-fix commit that touches a code file AND a README/config
    commits = [
        _commit("a1", 2, "fix crash in parser", ["core/parser.py", "README.md"]),
        _commit("a2", 5, "fix config bug", ["core/parser.py", ".streamlit/config.toml"]),
    ]
    classify_commits(commits)
    feats = build_file_features(commits, as_of=NOW)
    by = {f["path"]: f for f in feats}
    # code file accrues bug history...
    assert by["core/parser.py"]["bugfix_count"] == 2
    assert by["core/parser.py"]["bug_score"] > 0
    # ...docs/config do not (the old false positive)
    assert by["README.md"]["bugfix_count"] == 0
    assert by["README.md"]["bug_score"] == 0
    assert by[".streamlit/config.toml"]["bug_score"] == 0
    print("  ok: bug credit only for code files")


def test_clone_failure_message_names_the_real_cause():
    """A repo that cannot be cloned must say *why*. Swallowing the exception
    turned "GitPython isn't installed" into a baffling "no cached commits",
    which only ever surfaces on a repo that was never analyzed before."""
    from types import SimpleNamespace

    from core.analysis import _clone_hint, run_hotspot_analysis

    assert _clone_hint(None) == ""

    hint = _clone_hint(ModuleNotFoundError("No module named 'git'", name="git"))
    assert "GitPython is not installed" in hint and "pip install GitPython" in hint

    assert "ValueError: bad url" in _clone_hint(ValueError("bad url"))

    # end-to-end: an unclonable target with nothing cached surfaces the reason
    class _EmptyStore:
        backend = "fake"

        def load_commits(self, key):
            return []

    settings = SimpleNamespace(cache_dir="data/cache", bug_keywords=["fix"],
                               churn_window_days=30,
                               hotspot_recency_halflife_days=30,
                               ml_model_path="does-not-exist.json",
                               github_token="")
    try:
        run_hotspot_analysis("not-a-repo-or-url", settings, _EmptyStore())
    except SystemExit as exc:
        msg = str(exc)
        assert "Cannot analyze" in msg and "could not be opened" in msg
        assert "ValueError" in msg          # the real cause, not a generic line
    else:
        raise AssertionError("expected SystemExit for an unclonable repo")
    print("  ok: clone failure explains the real cause")


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    print(f"running {len(fns)} test(s)...")
    for fn in fns:
        fn()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    _run_all()
