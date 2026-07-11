"""Tests for the Developer Skill Profiler (Tool 2).

The classifier and profile builder are pure stdlib (the GitHub API and LLM are
injected), so they're tested with synthetic activity — no network, no token, no
LLM SDK.

    python tests/test_dev_profiler.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.llm import FakeProvider
from tools.dev_profiler.classifier import DEV_TYPES, classify
from tools.dev_profiler.profile_builder import build_profile
from tools.dev_profiler.runner import run_developer_profile


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
    now = datetime.now(timezone.utc)
    commits = [
        _commit("Fix null pointer in session validation\n\nbecause it crashed. Closes #1",
                [{"path": "auth.py", "status": "modified"}], bug=True),
        _commit("Add payments route", [{"path": "pay.py", "status": "added"}]),
    ]
    commits[0]["date"] = now - timedelta(days=2)
    commits[1]["date"] = now - timedelta(days=2)
    activity = {
        "username": "alice", "commits": commits,
        "languages": {"Python": 3, "Go": 1}, "repos": ["a/b", "a/c"],
        "authored_prs": 12, "pr_samples": ["Implements payments"], "reviews_count": 5,
        "merged_prs": 9, "issues_resolved": 4,
        "user": {"followers": 10, "bio": "hi", "years_active": 3.5},
    }
    profile = build_profile(activity, _settings(), llm=FakeProvider("Strong, detail-oriented."))
    assert profile["username"] == "alice"
    assert profile["primary_type"] in DEV_TYPES
    assert profile["top_languages"][0] == "Python"
    assert 0 <= profile["commit_message_quality"] <= 10
    assert profile["authored_prs"] == 12
    assert profile["llm_summary"] == "Strong, detail-oriented."
    # dashboard fields: language shares, social header, counts, daily heatmap
    assert profile["languages"][0] == {"name": "Python", "pct": 75.0}
    assert profile["prs_merged"] == 9 and profile["issues_resolved"] == 4
    assert profile["user"]["followers"] == 10
    assert sum(d["count"] for d in profile["heatmap"]) == 2
    # without an LLM, summary is simply None; missing socials stay safe defaults
    bare = build_profile({"username": "bob", "commits": []}, _settings(), llm=None)
    assert bare["llm_summary"] is None
    assert bare["user"] == {} and bare["heatmap"] == [] and bare["prs_merged"] == 0
    print("  ok: profile assembly (+ fake LLM, + no LLM, dashboard fields)")


class _FakeStore:
    """Just enough of the store interface for the runner's cache path."""

    backend = "fake"

    def __init__(self, cached=None):
        self.cached = cached
        self.saved = None

    def load_report(self, kind, key):
        return self.cached

    def save_report(self, kind, key, doc):
        self.saved = (kind, key, doc)


def test_runner_reuses_fresh_cached_profile():
    # stub out the network path: any attempt to fetch raises Sentinel
    import core.github_client as ghc
    import pipeline.fetch_user_activity as fua

    class Sentinel(Exception):
        pass

    def _no_fetch(*a, **k):
        raise Sentinel("network fetch attempted")

    orig_api, orig_fetch = ghc.GitHubAPI, fua.fetch_user_activity
    ghc.GitHubAPI, fua.fetch_user_activity = (lambda token: None), _no_fetch
    try:
        cached = {"username": "alice", "primary_type": "Bug Fixer",
                  "generated_at": datetime.now(timezone.utc) - timedelta(hours=1)}
        settings = _settings(github_token="tok", profile_cache_hours=24)
        # fresh cache -> served without touching the network
        assert run_developer_profile("alice", settings, _FakeStore(cached)) is cached
        # database-first: even a STALE cache is served — GitHub is only hit
        # on an explicit refresh (the UI's re-fetch button)
        stale = dict(cached, generated_at=datetime.now(timezone.utc) - timedelta(hours=48))
        assert run_developer_profile("alice", settings, _FakeStore(stale)) is stale
        # refresh=True -> rebuild even when the cache is fresh
        try:
            run_developer_profile("alice", settings, _FakeStore(cached), refresh=True)
            assert False, "refresh=True should bypass the cache"
        except Sentinel:
            pass
        # without a token, the cached copy is returned regardless of age
        no_token = _settings(github_token="", profile_cache_hours=24)
        assert run_developer_profile("alice", no_token, _FakeStore(stale)) is stale
    finally:
        ghc.GitHubAPI, fua.fetch_user_activity = orig_api, orig_fetch
    print("  ok: runner cache (fresh hit, stale hit, refresh bypass, token-less)")


def test_repo_meta_is_cached_with_a_ttl():
    """Repo metadata is cheap to refetch, so it is cached *with a TTL* rather
    than forever: a fresh copy is free, a stale one refreshes itself. Caching
    it forever froze the dashboard's stars/description at the first analysis."""
    import core.github_client as ghc

    class Sentinel(Exception):
        pass

    calls = []

    class _NoNetAPI:
        def __init__(self, token):
            calls.append("fetch")
            raise Sentinel("GitHub API constructed")

    orig = ghc.GitHubAPI
    ghc.GitHubAPI = _NoNetAPI
    try:
        now = datetime.now(timezone.utc)
        fresh = {"full_name": "o/r", "stars": 5,
                 "generated_at": now - timedelta(hours=1)}
        month_old = {"full_name": "o/r", "stars": 5,
                     "generated_at": now - timedelta(days=30)}
        settings = _settings(github_token="tok", profile_cache_hours=24)

        # within the TTL: served from the store, GitHub untouched
        assert ghc.get_repo_meta("o/r", settings, _FakeStore(fresh)) is fresh
        assert calls == []

        # past the TTL: refetch is attempted; when GitHub fails the stale copy
        # still wins (a broken refresh must never blank the dashboard)
        assert ghc.get_repo_meta("o/r", settings, _FakeStore(month_old)) is month_old
        assert calls == ["fetch"]

        # refresh=True refetches even a cache that is still fresh
        calls.clear()
        assert ghc.get_repo_meta("o/r", settings, _FakeStore(fresh),
                                 refresh=True) is fresh
        assert calls == ["fetch"]

        # nothing cached -> the first fetch must go to GitHub
        try:
            ghc.get_repo_meta("o/r", settings, _FakeStore(None))
            assert False, "first fetch should call GitHub"
        except Sentinel:
            pass

        # no token -> cache or None, never a network attempt
        calls.clear()
        assert ghc.get_repo_meta("o/r", _settings(github_token=""),
                                 _FakeStore(None)) is None
        assert calls == []
    finally:
        ghc.GitHubAPI = orig
    print("  ok: repo meta cached with a TTL (fresh hit, stale refetch, forced refresh)")


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    print(f"running {len(fns)} test(s)...")
    for fn in fns:
        fn()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    _run_all()
