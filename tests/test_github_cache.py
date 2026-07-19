"""Tests for the GitHub-data freshness policy (core/github_client.get_repo_meta).

Repo metadata is cheap to refetch (two API calls), so it is cached with a TTL
and refreshes itself once stale — the dashboard must not show the stars and
description captured on the very first analysis forever.

Network-free: `GitHubAPI` is stubbed, so no token and no HTTP are involved.

    python tests/test_github_cache.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.github_client as gh
from core.github_client import get_repo_meta


class Store:
    """Store twin that stamps `generated_at` the way Mongo/Json stores do."""

    backend = "fake"

    def __init__(self):
        self.reports: dict = {}

    def save_report(self, kind, key, doc):
        self.reports[(kind, key)] = {
            "key": key, "generated_at": datetime.now(timezone.utc), **doc}

    def load_report(self, kind, key):
        doc = self.reports.get((kind, key))
        return dict(doc) if doc else None

    def seed(self, key, doc, *, age_hours: float):
        """Pre-load a cached copy with a specific age."""
        self.reports[("repo_meta", key)] = {
            "key": key,
            "generated_at": datetime.now(timezone.utc) - timedelta(hours=age_hours),
            **doc,
        }


def _settings(**over):
    base = dict(github_token="tok", profile_cache_hours=24)
    base.update(over)
    return SimpleNamespace(**base)


class _FakeAPI:
    """Stub for GitHubAPI — counts calls, never touches the network."""

    calls = 0

    def __init__(self, token):
        pass

    def repo_meta(self, full_name):
        _FakeAPI.calls += 1
        return {"full_name": full_name, "stars": 100, "languages": []}


def _patched(fn):
    """Run `fn` with GitHubAPI stubbed and the call counter reset."""
    original, _FakeAPI.calls = gh.GitHubAPI, 0
    gh.GitHubAPI = _FakeAPI
    try:
        fn()
    finally:
        gh.GitHubAPI = original


def test_clone_dest_keeps_the_owner():
    """'pallets/flask' and 'yourfork/flask' are different repos — the clone
    directory must carry the owner, or the second analysis silently reuses
    the first repo's clone and caches the wrong history under its own key."""
    a = gh._clone_dest("cache", "pallets/flask")
    b = gh._clone_dest("cache", "yourfork/flask")
    assert a != b
    assert a.endswith(os.path.join("clones", "pallets__flask"))
    assert b.endswith(os.path.join("clones", "yourfork__flask"))
    # bare local-clone keys (no owner) slug to themselves
    assert gh._clone_dest("cache", "localrepo").endswith(
        os.path.join("clones", "localrepo"))
    print("  ok: clone destinations keep the owner (no name collisions)")


def test_fresh_cache_is_served_without_calling_github():
    def body():
        store = Store()
        store.seed("owner/repo", {"stars": 5}, age_hours=1)
        doc = get_repo_meta("owner/repo", _settings(), store)
        assert doc["stars"] == 5          # the cached copy
        assert _FakeAPI.calls == 0        # GitHub never contacted
    _patched(body)
    print("  ok: fresh cache served, no GitHub call")


def test_stale_cache_refetches_itself():
    def body():
        store = Store()
        store.seed("owner/repo", {"stars": 5}, age_hours=48)   # older than the 24h TTL
        doc = get_repo_meta("owner/repo", _settings(), store)
        assert _FakeAPI.calls == 1        # went back to GitHub
        assert doc["stars"] == 100        # live value, not the stale 5
        # and the refreshed copy is now cached & fresh
        assert get_repo_meta("owner/repo", _settings(), store)["stars"] == 100
        assert _FakeAPI.calls == 1        # served from the new cache
    _patched(body)
    print("  ok: stale cache refetches, then re-caches")


def test_explicit_refresh_ignores_a_fresh_cache():
    def body():
        store = Store()
        store.seed("owner/repo", {"stars": 5}, age_hours=1)
        doc = get_repo_meta("owner/repo", _settings(), store, refresh=True)
        assert _FakeAPI.calls == 1 and doc["stars"] == 100
    _patched(body)
    print("  ok: refresh=True forces a refetch")


def test_missing_cache_fetches():
    def body():
        store = Store()
        assert get_repo_meta("owner/repo", _settings(), store)["stars"] == 100
        assert _FakeAPI.calls == 1
    _patched(body)
    print("  ok: first fetch populates the cache")


def test_no_github_side_for_local_keys_or_without_token():
    def body():
        store = Store()
        # a bare local-clone key has no owner/repo -> nothing to fetch
        assert get_repo_meta("localrepo", _settings(), store) is None
        # no token -> serve whatever is cached, never call GitHub
        store.seed("owner/repo", {"stars": 5}, age_hours=999)
        assert get_repo_meta("owner/repo", _settings(github_token=""), store)["stars"] == 5
        assert _FakeAPI.calls == 0
    _patched(body)
    print("  ok: local keys / no token never hit GitHub")


def test_stale_cache_survives_github_being_down():
    """Stale beats nothing: a failed refresh must not blank the dashboard."""
    class _Down(_FakeAPI):
        def repo_meta(self, full_name):
            _FakeAPI.calls += 1
            raise RuntimeError("github unreachable")

    original, _FakeAPI.calls = gh.GitHubAPI, 0
    gh.GitHubAPI = _Down
    try:
        store = Store()
        store.seed("owner/repo", {"stars": 5}, age_hours=48)
        doc = get_repo_meta("owner/repo", _settings(), store)
        assert _FakeAPI.calls == 1 and doc["stars"] == 5   # served the stale copy

        # ...but with nothing cached there is nothing to fall back to
        try:
            get_repo_meta("other/repo", _settings(), Store())
        except RuntimeError:
            pass
        else:
            raise AssertionError("expected the GitHub error to propagate")
    finally:
        gh.GitHubAPI = original
    print("  ok: failed refresh falls back to the stale copy")


def _run_all():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    print(f"running {len(fns)} test(s)...")
    for fn in fns:
        fn()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    _run_all()
