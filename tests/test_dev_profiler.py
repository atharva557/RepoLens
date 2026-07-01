"""Tests for the Developer Skill Profiler (Tool 2).

The classifier and profile builder are pure stdlib (the GitHub API and LLM are
injected), so they're tested with synthetic activity — no network, no token, no
LLM SDK.

    python tests/test_dev_profiler.py
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.llm import FakeProvider
from tools.dev_profiler.classifier import DEV_TYPES, classify
from tools.dev_profiler.profile_builder import build_profile


def _commit(msg, files, additions=10, deletions=2, bug=False):
    return {"message": msg, "additions": additions, "deletions": deletions,
            "is_bugfix": bug, "files": files}


def _settings(**over):
    base = dict(llm_provider="local")
    base.update(over)
    return SimpleNamespace(**base)


def test_bug_fixer_dominant():
    commits = [_commit("Fix crash", [{"path": "a.py", "status": "modified"}], bug=True)
               for _ in range(8)]
    commits += [_commit("Add thing", [{"path": "b.py", "status": "added"}])]
    result = classify({"username": "u", "commits": commits})
    assert result["primary_type"] == "Bug Fixer", result["distribution"]
    print("  ok: bug fixer dominant")


def test_feature_builder_dominant():
    commits = [_commit("Add feature", [{"path": f"f{i}.py", "status": "added"}])
               for i in range(8)]
    result = classify({"username": "u", "commits": commits})
    assert result["primary_type"] == "Feature Builder", result["distribution"]
    print("  ok: feature builder dominant")


def test_doc_writer_dominant():
    commits = [_commit("Update docs", [{"path": "docs/guide.md", "status": "modified"}])
               for _ in range(6)]
    result = classify({"username": "u", "commits": commits})
    assert result["primary_type"] == "Documentation Writer", result["distribution"]
    print("  ok: documentation writer dominant")


def test_reviewer_signal():
    commits = [_commit("Fix x", [{"path": "a.py", "status": "modified"}]) for _ in range(3)]
    result = classify({"username": "u", "commits": commits, "reviews_count": 30})
    assert result["primary_type"] == "Reviewer", result["distribution"]
    print("  ok: reviewer signal")


def test_distribution_sums_and_empty():
    commits = [_commit("Fix", [{"path": "a.py", "status": "modified"}], bug=True),
               _commit("Add", [{"path": "b.py", "status": "added"}])]
    dist = classify({"username": "u", "commits": commits})["distribution"]
    assert abs(sum(dist.values()) - 100) <= 2          # rounding tolerance
    assert classify({"username": "u", "commits": []})["primary_type"] == "Unknown"
    print("  ok: distribution sums; empty handled")


def test_profile_assembly_with_fake_llm():
    commits = [
        _commit("Fix null pointer in session validation\n\nbecause it crashed. Closes #1",
                [{"path": "auth.py", "status": "modified"}], bug=True),
        _commit("Add payments route", [{"path": "pay.py", "status": "added"}]),
    ]
    activity = {
        "username": "alice", "commits": commits,
        "languages": {"Python": 3, "Go": 1}, "repos": ["a/b", "a/c"],
        "authored_prs": 12, "pr_samples": ["Implements payments"], "reviews_count": 5,
    }
    profile = build_profile(activity, _settings(), llm=FakeProvider("Strong, detail-oriented."))
    assert profile["username"] == "alice"
    assert profile["primary_type"] in DEV_TYPES
    assert profile["top_languages"][0] == "Python"
    assert 0 <= profile["commit_message_quality"] <= 10
    assert profile["authored_prs"] == 12
    assert profile["llm_summary"] == "Strong, detail-oriented."
    # without an LLM, summary is simply None
    assert build_profile(activity, _settings(), llm=None)["llm_summary"] is None
    print("  ok: profile assembly (+ fake LLM, + no LLM)")


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    print(f"running {len(fns)} test(s)...")
    for fn in fns:
        fn()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    _run_all()
