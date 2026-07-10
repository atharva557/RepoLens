"""Tests for the FastAPI layer (v0.4).

Network-free: the app is built with an in-test FakeStore and stubbed engine
entry points, so no git, GitHub, MongoDB, or LLM is touched. Skips cleanly when
fastapi isn't installed (the API is an optional layer, like the LLM SDKs).

    python tests/test_api.py
"""
import hashlib
import hmac
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from fastapi.testclient import TestClient
except ImportError:
    print("fastapi not installed - skipping API tests (pip install fastapi httpx)")
    sys.exit(0)

import api.main as api_main
from api.jobs import JobRegistry
from api.main import create_app
from config.settings import Settings


class FakeStore:
    """Minimal in-memory stand-in for MongoStore/JsonStore."""

    backend = "fake"

    def __init__(self):
        self.hotspots: dict = {}
        self.reports: dict = {}
        self.commits: dict = {}

    def ensure_indexes(self):
        pass

    def save_commits(self, key, commits):
        self.commits[key] = list(commits)
        return len(commits)

    def load_commits(self, key):
        return list(self.commits.get(key, []))

    def save_hotspots(self, key, rows):
        self.hotspots[key] = {"repo": key, "rows": rows}
        return len(rows)

    def load_hotspots(self, key):
        doc = self.hotspots.get(key)
        return dict(doc) if doc else None

    def save_report(self, kind, key, doc):
        self.reports[(kind, key)] = {"key": key, **doc}

    def load_report(self, kind, key):
        doc = self.reports.get((kind, key))
        return dict(doc) if doc else None

    def list_reports(self, kind, fields=()):
        if kind == "commits":
            return [{"key": k, "commits": len(v)} for k, v in sorted(self.commits.items())]
        if kind == "hotspots":
            return [{"key": k, "generated_at": None, "files": len(d.get("rows") or [])}
                    for k, d in sorted(self.hotspots.items())]
        out = []
        for (knd, key), doc in sorted(self.reports.items()):
            if knd != kind:
                continue
            row = {"key": key, "generated_at": doc.get("generated_at")}
            row.update({f: doc[f] for f in fields if f in doc})
            out.append(row)
        return out


def _client(settings=None, store=None):
    return TestClient(create_app(settings=settings or Settings(), store=store or FakeStore()))


def test_health_root_and_config():
    with _client(settings=Settings(github_token="secret-token")) as c:
        assert c.get("/health").json()["store"] == "fake"
        assert c.get("/").json()["docs"] == "/docs"
        cfg = c.get("/config").json()
        assert cfg["github_token"] == "***"          # masked, never leaked
        assert cfg["llm_provider"] == "local"
    print("  ok: health / root / masked config")


def test_read_endpoints_404_then_hit():
    store = FakeStore()
    with _client(store=store) as c:
        assert c.get("/repos/owner/repo/hotspots").status_code == 404
        assert c.get("/repos/owner/repo/commit-quality").status_code == 404
        assert c.get("/repos/owner/repo/pr-reviews/7").status_code == 404
        assert c.get("/profiles/alice").status_code == 404

        store.save_hotspots("owner/repo", [{"path": "a.py", "score": 0.9}])
        store.save_hotspots("localrepo", [{"path": "b.py", "score": 0.5}])
        store.save_report("commit_quality", "owner/repo", {"commits": 3, "avg_score": 6.5})
        store.save_report("pr_review", "owner/repo#7", {"level": "LOW", "markdown": "ok"})
        store.save_report("developer_profile", "alice", {"username": "alice"})

        # owner/repo keys and bare local-clone keys both resolve (:path param)
        assert c.get("/repos/owner/repo/hotspots").json()["rows"][0]["path"] == "a.py"
        assert c.get("/repos/localrepo/hotspots").json()["rows"][0]["path"] == "b.py"
        assert c.get("/repos/owner/repo/hotspots?top=0").json()["rows"] == []
        assert c.get("/repos/owner/repo/commit-quality").json()["avg_score"] == 6.5
        assert c.get("/repos/owner/repo/pr-reviews/7").json()["level"] == "LOW"
        assert c.get("/profiles/alice").json()["username"] == "alice"
    print("  ok: read layer (404 -> seeded hits, both key shapes)")


def test_profile_read_reports_freshness():
    """The profile GET stays a pure read but tells the UI how old it is, so a
    cached-forever profile can prompt a re-sync instead of silently going stale."""
    store = FakeStore()
    now = datetime.now(timezone.utc)
    with _client(store=store) as c:
        store.save_report("developer_profile", "fresh",
                          {"username": "fresh", "generated_at": now - timedelta(hours=1)})
        store.save_report("developer_profile", "old",
                          {"username": "old", "generated_at": now - timedelta(days=9)})
        store.save_report("developer_profile", "undated", {"username": "undated"})

        fresh = c.get("/profiles/fresh").json()
        assert fresh["stale"] is False and 0 <= fresh["age_hours"] <= 2

        old = c.get("/profiles/old").json()          # older than PROFILE_CACHE_HOURS (24)
        assert old["stale"] is True and old["age_hours"] > 24

        undated = c.get("/profiles/undated").json()  # no timestamp -> unknown, not stale
        assert undated["age_hours"] is None and undated["stale"] is False
    print("  ok: profile read reports age_hours + stale")


def test_analyze_trigger_and_job_lifecycle():
    calls = []

    def fake_analysis(target, settings, store, *, refresh=False, max_commits=None,
                      top=15, progress=None):
        calls.append(target)
        if progress:  # jobs thread a phase reporter into the engine
            progress("scoring files (weighted formula)", pct=50, detail="fake")

        class S:  # minimal FileScore stand-in
            def to_dict(self):
                return {"path": "a.py", "score": 1.0}

        return {"repo": "r", "commits": 5, "bugfix_commits": 2,
                "files_scored": 1, "ml_used": False, "scores": [S()]}

    original = api_main.run_hotspot_analysis
    api_main.run_hotspot_analysis = fake_analysis
    try:
        with _client() as c:
            assert c.post("/analyze", json={}).status_code == 422       # repo required
            r = c.post("/analyze", json={"repo": "some/repo", "top": 1})
            assert r.status_code == 202
            job = c.get(r.json()["status_url"]).json()
            assert job["status"] == "done", job
            assert job["result"]["top"] == [{"path": "a.py", "score": 1.0}]
            # the engine's phase reports surface on the job for the UI's bar
            assert job["progress"]["phase"] == "scoring files (weighted formula)"
            assert job["progress"]["pct"] == 50
            assert calls == ["some/repo"]
            assert c.get("/jobs/nope").status_code == 404
    finally:
        api_main.run_hotspot_analysis = original
    print("  ok: analyze trigger -> background job -> done")


def test_failed_job_is_recorded_not_fatal():
    def boom(*a, **kw):
        raise SystemExit("no cached commits")  # engine ops errors use SystemExit

    original = api_main.run_hotspot_analysis
    api_main.run_hotspot_analysis = boom
    try:
        with _client() as c:
            r = c.post("/analyze", json={"repo": "x"})
            job = c.get(r.json()["status_url"]).json()
            assert job["status"] == "failed"
            assert "no cached commits" in job["error"]
            assert c.get("/health").status_code == 200  # server survived
    finally:
        api_main.run_hotspot_analysis = original
    print("  ok: failed job recorded, server alive")


def test_pr_review_and_profile_need_token():
    with _client() as c:  # default settings: no token
        assert c.post("/repos/owner/repo/pr-reviews/1").status_code == 400
        assert c.post("/profiles/alice").status_code == 400
    print("  ok: triggers refuse without GITHUB_TOKEN")


def _signed(secret: str, payload: dict, event: str = "pull_request"):
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, {"X-GitHub-Event": event, "X-Hub-Signature-256": sig,
                  "Content-Type": "application/json"}


def test_webhook_security_and_dispatch():
    payload = {"action": "opened",
               "repository": {"full_name": "owner/repo"},
               "pull_request": {"number": 42}}

    # disabled without a secret
    with _client() as c:
        assert c.post("/webhook/github", json=payload).status_code == 503

    settings = Settings(github_webhook_secret="whsec", github_token="tok")
    seen = []

    def fake_review(pl, st, store, progress=None):
        seen.append(pl["pull_request"]["number"])
        return {"pr": "owner/repo#42", "level": "LOW"}

    original = api_main.review_pr_from_payload
    api_main.review_pr_from_payload = fake_review
    try:
        with _client(settings=settings) as c:
            # wrong signature rejected
            body, headers = _signed("wrong-secret", payload)
            assert c.post("/webhook/github", content=body, headers=headers).status_code == 401
            # non-PR events and non-review actions acknowledged but ignored
            body, headers = _signed("whsec", payload, event="ping")
            assert "ignored" in c.post("/webhook/github", content=body, headers=headers).json()
            closed = {**payload, "action": "closed"}
            body, headers = _signed("whsec", closed)
            assert "ignored" in c.post("/webhook/github", content=body, headers=headers).json()
            # a real opened-PR event dispatches Tool 3 in the background
            body, headers = _signed("whsec", payload)
            r = c.post("/webhook/github", content=body, headers=headers)
            assert r.status_code == 202
            job = c.get(r.json()["status_url"]).json()
            assert job["status"] == "done" and seen == [42], job
    finally:
        api_main.review_pr_from_payload = original
    print("  ok: webhook (secret gate, HMAC, ignore rules, dispatch)")


def test_discovery_endpoints():
    store = FakeStore()
    with _client(store=store) as c:
        # empty store -> empty (but valid) discovery responses
        assert c.get("/repos").json() == {"repos": []}
        assert c.get("/profiles").json() == {"profiles": []}
        assert c.get("/repos/owner/repo/pr-reviews").json()["pr_reviews"] == []

        store.save_commits("owner/repo", [{"sha": "1"}, {"sha": "2"}])
        store.save_hotspots("owner/repo", [{"path": "a.py"}, {"path": "b.py"}])
        store.save_report("commit_quality", "owner/repo", {"avg_score": 6.5})
        store.save_report("pr_review", "owner/repo#7", {"level": "LOW"})
        store.save_report("pr_review", "owner/repo#3", {"level": "HIGH"})
        store.save_report("pr_review", "other/repo#1", {"level": "LOW"})
        store.save_report("developer_profile", "alice", {"primary_type": "Bug Fixer"})

        repos = {r["repo"]: r for r in c.get("/repos").json()["repos"]}
        assert set(repos) == {"owner/repo", "other/repo"}
        assert repos["owner/repo"]["commits"] == 2
        assert repos["owner/repo"]["hotspots"]["files"] == 2
        assert repos["owner/repo"]["pr_reviews"] == [3, 7]
        assert repos["other/repo"]["hotspots"] is None

        profs = c.get("/profiles").json()["profiles"]
        assert profs == [{"username": "alice", "generated_at": None,
                          "primary_type": "Bug Fixer"}]

        revs = c.get("/repos/owner/repo/pr-reviews").json()["pr_reviews"]
        assert [r["number"] for r in revs] == [3, 7]
        assert revs[0]["level"] == "HIGH"
        # the per-number read route still resolves alongside the list route
        assert c.get("/repos/owner/repo/pr-reviews/7").json()["level"] == "LOW"
    print("  ok: discovery layer (/repos, /profiles, pr-review lists)")


def test_cors_headers():
    with _client() as c:  # default settings: allow all origins
        r = c.get("/health", headers={"Origin": "http://localhost:5173"})
        assert r.headers.get("access-control-allow-origin") == "*"
        pre = c.options("/repos", headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        })
        assert pre.status_code == 200
        assert "GET" in pre.headers.get("access-control-allow-methods", "")
    print("  ok: CORS headers (simple + preflight)")


def test_selftest_endpoint():
    import core.llm as core_llm

    original = core_llm.get_llm
    core_llm.get_llm = lambda s: core_llm.FakeProvider("pong")
    try:
        with _client(settings=Settings(github_token="tok")) as c:
            body = c.get("/test").json()
            assert body["ok"] is True
            assert body["store"] == {"backend": "fake", "ok": True}  # real round-trip
            assert body["llm"]["available"] is True
            assert body["github_token"] is True
            assert body["webhook"]["enabled"] is False
            assert "similarity" in body
    finally:
        core_llm.get_llm = original
    print("  ok: /test self-test (store round-trip, llm, config flags)")


def test_activity_endpoint():
    store = FakeStore()
    now = datetime.now(timezone.utc)
    store.save_commits("owner/repo", [
        {"sha": "aaaa1111", "author": "alice", "date": now - timedelta(days=1),
         "message": "Fix crash in parser\n\nbecause", "is_bugfix": True},
        {"sha": "bbbb2222", "author": "alice", "date": now - timedelta(days=1),
         "message": "Add feature", "is_bugfix": False},
        {"sha": "cccc3333", "author": "bob", "date": now - timedelta(days=400),
         "message": "ancient commit", "is_bugfix": False},
    ])
    store.save_report("commit_quality", "owner/repo", {"avg_score": 8.0})
    with _client(store=store) as c:
        assert c.get("/repos/nope/activity").status_code == 404
        body = c.get("/repos/owner/repo/activity").json()
        assert body["total_commits"] == 3
        assert body["window_commits"] == 2          # 400-day-old commit excluded
        assert body["window_bugfix_ratio"] == 0.5
        assert body["contributors"][0] == {"author": "alice", "commits": 2,
                                           "share": 0.667}
        assert body["recent_commits"][0]["sha"] == "aaaa111"   # newest first, 7 chars
        assert body["recent_commits"][0]["subject"] == "Fix crash in parser"
        # heatmap spans all history (incl. the 400-day-old commit), unlike
        # the windowed stats above
        assert sum(d["count"] for d in body["heatmap"]) == 3
        # health composite: 0.6*8.0 + 0.4*(1-0.5)*10 = 6.8
        assert body["health"]["score"] == 6.8
    print("  ok: activity endpoint (window, contributors, heatmap, health)")


def test_meta_endpoint():
    fake_doc = {"full_name": "owner/repo", "stars": 5, "languages": []}
    calls = []

    def fake_meta(key, settings, store, *, refresh=False):
        calls.append((key, refresh))
        return fake_doc if key == "owner/repo" else None

    original = api_main.get_repo_meta
    api_main.get_repo_meta = fake_meta
    try:
        with _client() as c:
            assert c.get("/repos/owner/repo/meta").json()["stars"] == 5
            assert c.get("/repos/localonly/meta").status_code == 404
            c.get("/repos/owner/repo/meta?refresh=true")
            assert calls[-1] == ("owner/repo", True)
    finally:
        api_main.get_repo_meta = original
    print("  ok: meta endpoint (hit, 404, refresh passthrough)")


def test_insights_trigger_and_read():
    store = FakeStore()

    def fake_insights(key, settings, st, progress=None):
        st.save_report("repo_insights", key, {"repo": key, "bullets": ["a", "b"]})
        return {"repo": key, "bullets": ["a", "b"]}

    original = api_main.run_repo_insights
    api_main.run_repo_insights = fake_insights
    try:
        with _client(store=store) as c:
            assert c.get("/repos/owner/repo/insights").status_code == 404
            r = c.post("/repos/owner/repo/insights")
            assert r.status_code == 202
            job = c.get(r.json()["status_url"]).json()
            assert job["status"] == "done" and job["result"]["bullets"] == 2
            assert c.get("/repos/owner/repo/insights").json()["bullets"] == ["a", "b"]
    finally:
        api_main.run_repo_insights = original
    print("  ok: insights trigger -> job -> cached read")


def test_job_registry_bounds():
    reg = JobRegistry(max_jobs=2)
    ids = [reg.create("k", {}) for _ in range(3)]
    assert reg.get(ids[0]) is None          # oldest pruned
    assert reg.get(ids[2])["status"] == "pending"
    reg.run(ids[2], lambda: {"x": 1})
    assert reg.get(ids[2])["result"] == {"x": 1}
    print("  ok: job registry bounded + run wrapper")


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    print(f"running {len(fns)} test(s)...")
    for fn in fns:
        fn()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    _run_all()
