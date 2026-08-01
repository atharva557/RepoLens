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


def test_mongo_load_commits_sorts_newest_first():
    """The newest-first ordering must be an explicit sort, not an accident of
    insertion order: build_bug_index takes the FIRST N qualifying commits and
    fingerprints the first/last SHA, so unordered 'natural' order would
    silently index the wrong diffs."""
    from types import SimpleNamespace

    from core.db import MongoStore

    class _Cursor:
        def __init__(self):
            self.sorted_by = None

        def sort(self, spec):
            self.sorted_by = spec
            return iter([{"sha": "new"}, {"sha": "old"}])

    class _Coll:
        def __init__(self, cursor):
            self._cursor = cursor

        def find(self, *a, **k):
            return self._cursor

    cursor = _Cursor()
    store = MongoStore.__new__(MongoStore)  # bypass the live-connection __init__
    store.db = SimpleNamespace(commits=_Coll(cursor))
    out = store.load_commits("o/r")
    assert cursor.sorted_by == [("date", -1)]
    assert [c["sha"] for c in out] == ["new", "old"]
    print("  ok: MongoStore.load_commits sorts newest-first explicitly")


def _client(settings=None, store=None, env_path=None, mailer=None):
    return TestClient(create_app(settings=settings or Settings(),
                                 store=store or FakeStore(),
                                 env_path=env_path or os.devnull,
                                 mailer=mailer))


def test_analysis_rejects_non_github_remote_urls_before_starting_a_job():
    """The API boundary must reject arbitrary clone URLs, not defer to git."""
    with _client() as c:
        response = c.post("/analyze", json={
            "repo": "https://huggingface.co/bigscience/bloom"})
    assert response.status_code == 422
    assert "only GitHub repository URLs" in response.text
    print("  ok: analysis rejects non-GitHub remote URLs")


def test_email_pr_review_endpoint():
    """The dashboard's Email button. Its route sits under the same
    `{repo_key:path}` prefix as the trigger, and `:path` is greedy — so this
    also pins that `.../pr-reviews/42/email` doesn't get swallowed as a repo
    key with number="email"."""
    from core.mailer import ConsoleMailer

    store = FakeStore()
    store.save_report("pr_review", "owner/repo#42", {
        "repo": "owner/repo", "pr": 42, "level": "HIGH",
        "warnings": ["large diff"], "oks": [], "url": "https://x/pull/42"})
    mailer = ConsoleMailer(quiet=True)
    settings = Settings(smtp_user="bot@example.com")

    with _client(settings=settings, store=store, mailer=mailer) as c:
        # a review that was never run can't be emailed
        assert c.post("/repos/owner/repo/pr-reviews/99/email").status_code == 404

        r = c.post("/repos/owner/repo/pr-reviews/42/email")
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True, "emailed": 1}
        assert len(mailer.sent) == 1
        assert mailer.sent[0]["To"] == "bot@example.com"
        assert "owner/repo#42" in mailer.sent[0]["Subject"]

    # nothing configured to send from -> an actionable 503, not a silent 200
    with _client(settings=Settings(), store=store,
                 mailer=ConsoleMailer(quiet=True)) as c:
        r = c.post("/repos/owner/repo/pr-reviews/42/email")
        assert r.status_code == 503 and "SMTP_USER" in r.json()["detail"]
    print("  ok: POST .../pr-reviews/{n}/email sends, 404s, and 503s honestly")


def test_pr_review_trigger_emails_only_when_asked():
    """The server holds no email preference — the dashboard passes the user's
    "Email PR reviews" switch per trigger, so the default must be silent."""
    from core.mailer import ConsoleMailer

    seen = {}

    def fake_job(spec, settings, store, identity=None, mailer=None,
                 email=False, progress=None):
        seen["email"] = email
        return {"pr": spec, "level": "LOW"}

    original = api_main._pr_review_job
    api_main._pr_review_job = fake_job
    try:
        settings = Settings(github_token="tok", smtp_user="bot@example.com")
        with _client(settings=settings, mailer=ConsoleMailer(quiet=True)) as c:
            c.post("/repos/owner/repo/pr-reviews/42")
            assert seen["email"] is False, "must not email unless asked"
            c.post("/repos/owner/repo/pr-reviews/42?email=true")
            assert seen["email"] is True
    finally:
        api_main._pr_review_job = original
    print("  ok: the trigger emails only when ?email=true")


def test_multiuser_discovery_scoping():
    """Home's lists must be per-user in multiuser mode: a new account sees
    nothing; each user sees only what THEY analyzed/searched."""
    from datetime import datetime, timezone

    from core.identity import MemoryIdentity

    store = FakeStore()
    now = datetime.now(timezone.utc)
    for key in ("x", "other/repo"):
        store.save_commits(key, [{"sha": "a" * 8, "author": "dev", "date": now,
                                  "message": "Add feature", "is_bugfix": False}])
    store.save_report("developer_profile", "alice", {"username": "alice"})
    store.save_report("developer_profile", "bob", {"username": "bob"})

    ident = MemoryIdentity("unused-key")
    s = Settings(multiuser=True, fernet_key="unused-key", github_token="tok")
    # tracking happens at trigger time; the background jobs themselves are
    # stubbed so this test stays network-free (the profiler would hit GitHub)
    orig_analyze = api_main.run_hotspot_analysis
    orig_profile = api_main.run_developer_profile
    api_main.run_hotspot_analysis = lambda *a, **k: {
        "repo": "x", "commits": 1, "bugfix_commits": 0, "files_scored": 0,
        "ml_used": False, "scores": []}
    api_main.run_developer_profile = lambda *a, **k: {}
    try:
        _scoping_flow(store, ident, s)
    finally:
        api_main.run_hotspot_analysis = orig_analyze
        api_main.run_developer_profile = orig_profile
    # single-user mode stays global (no filtering at all)
    with _client(store=store) as c:
        assert len(c.get("/repos").json()["repos"]) == 2
        assert len(c.get("/profiles").json()["profiles"]) == 2
    print("  ok: multiuser discovery scoped per user (new accounts see nothing)")


def _scoping_flow(store, ident, s):
    from api.auth import SESSION_COOKIE

    with TestClient(create_app(settings=s, store=store, identity=ident,
                               env_path=os.devnull)) as c:
        # anonymous discovery lists nothing (the login wall owns that UX)
        assert c.get("/repos").json()["repos"] == []
        assert c.get("/profiles").json()["profiles"] == []

        # brand-new signed-in account: still nothing
        u = ident.create_password_user("a@b.com", "irrelevant")
        c.cookies.set(SESSION_COOKIE, ident.create_session(u["id"]))
        assert c.get("/repos").json()["repos"] == []
        assert c.get("/profiles").json()["profiles"] == []

        # triggering an analysis tracks the canonical repo key for this user
        assert c.post("/analyze", json={"repo": "x"}).status_code == 202
        assert ident.user_repo_keys(u["id"]) == ["x"]
        assert [r["repo"] for r in c.get("/repos").json()["repos"]] == ["x"]

        # profile trigger tracks the username; the other profile stays hidden
        assert c.post("/profiles/alice").status_code == 202
        assert [p["username"] for p in c.get("/profiles").json()["profiles"]] \
            == ["alice"]

        # a second user starts from an empty slate
        u2 = ident.create_password_user("b@b.com", "irrelevant")
        c.cookies.clear()
        c.cookies.set(SESSION_COOKIE, ident.create_session(u2["id"]))
        assert c.get("/repos").json()["repos"] == []
        assert c.get("/profiles").json()["profiles"] == []


def test_update_config_runtime_and_env():
    import tempfile

    s = Settings()
    with tempfile.TemporaryDirectory() as td:
        env_path = os.path.join(td, ".env")
        with open(env_path, "w", encoding="utf-8") as fh:
            fh.write("LLM_PROVIDER=local\nMONGODB_DB=gitpulse\n")
        with _client(settings=s, env_path=env_path) as c:
            r = c.put("/config", json={"llm_provider": "Claude",
                                       "anthropic_api_key": " sk-ant-xyz ",
                                       "github_token": "ghp_new"})
            assert r.status_code == 200
            body = r.json()
            assert body["persisted"] is True
            assert body["applied"] == ["anthropic_api_key", "github_token",
                                       "llm_provider"]
            # applied to the live process (normalized), never echoed back
            assert s.llm_provider == "claude" and s.anthropic_api_key == "sk-ant-xyz"
            assert s.github_token == "ghp_new"
            assert body["config"]["anthropic_api_key"] == "***"
            assert "sk-ant-xyz" not in r.text
            # .env rewritten in place: matching line replaced, others kept,
            # new keys appended
            with open(env_path, encoding="utf-8") as fh:
                env = fh.read()
            assert "LLM_PROVIDER=claude" in env and "LLM_PROVIDER=local" not in env
            assert "ANTHROPIC_API_KEY=sk-ant-xyz" in env
            assert "GITHUB_TOKEN=ghp_new" in env
            assert "MONGODB_DB=gitpulse" in env
            # the live self-test sees the new token immediately
            assert c.get("/test").json()["github_token"] is True
            # validation: unknown provider 422, empty payload 400
            assert c.put("/config", json={"llm_provider": "hal9000"}).status_code == 422
            assert c.put("/config", json={}).status_code == 400
    # multiuser mode manages keys per-user (/api/v1/me, encrypted) — the
    # flat-file path must refuse SECRETS
    with TestClient(create_app(settings=Settings(multiuser=True), store=FakeStore(),
                               identity=object(), env_path=os.devnull)) as c:
        assert c.put("/config", json={"github_token": "x"}).status_code == 403
        assert c.put("/config", json={"openai_api_key": "sk-1"}).status_code == 403

        # ...but a model name is not a key. Refusing the whole endpoint left a
        # local (LM Studio) multiuser deployment unable to change its model at
        # all: /api/v1/me/llm demands a paid provider AND an api_key, so it
        # cannot stand in for non-secret operational config.
        r = c.put("/config", json={"llm_model": "qwen3-8b"})
        assert r.status_code == 200, r.text
        assert r.json()["config"]["llm_model"] == "qwen3-8b"
        assert c.put("/config", json={"llm_provider": "local"}).status_code == 200
        assert c.put("/config",
                     json={"local_llm_base_url": "http://x:1234/v1"}).status_code == 200

        # a mixed payload is still refused, and names the offending field
        r = c.put("/config", json={"llm_model": "y", "openai_api_key": "sk-1"})
        assert r.status_code == 403 and "openai_api_key" in r.json()["detail"]
        # and the rejected payload applied nothing
        assert c.get("/config").json()["llm_model"] == "qwen3-8b"
    print("  ok: PUT /config (live apply + .env persist + masking + guards)")


def test_persist_env_removes_shadowing_duplicates():
    """A key listed twice in .env used to survive a save: only the first line
    was rewritten, and _parse_env_file is last-assignment-wins, so the stale
    second line silently won on the next load while the API said persisted."""
    import tempfile

    from config.settings import _parse_env_file, persist_env

    with tempfile.TemporaryDirectory() as td:
        env_path = os.path.join(td, ".env")
        with open(env_path, "w", encoding="utf-8") as fh:
            fh.write("GITHUB_TOKEN=old1\nMONGODB_DB=gitpulse\n"
                     "GITHUB_TOKEN=old2\n# GITHUB_TOKEN=documented-example\n")
        persist_env({"GITHUB_TOKEN": "ghp_new"}, env_path=env_path,
                    example_path=os.devnull)

        with open(env_path, encoding="utf-8") as fh:
            text = fh.read()
        assert "GITHUB_TOKEN=ghp_new" in text
        assert "old1" not in text and "old2" not in text
        # untouched lines survive, including commented documentation
        assert "MONGODB_DB=gitpulse" in text
        assert "# GITHUB_TOKEN=documented-example" in text
        # and the value actually round-trips through a reload
        assert _parse_env_file(env_path)["GITHUB_TOKEN"] == "ghp_new"
    print("  ok: persist_env drops shadowing duplicates (value survives reload)")


def test_recent_pulls_endpoint():
    store = FakeStore()
    with _client(store=store) as c:
        # nothing cached + no token -> actionable 404
        r = c.get("/repos/owner/repo/pulls")
        assert r.status_code == 404
        assert "GITHUB_TOKEN" in r.json()["detail"]

        # cached list is served without touching GitHub (no token configured)
        store.save_report("recent_pulls", "owner/repo", {
            "repo": "owner/repo",
            "generated_at": datetime.now(timezone.utc),
            "pulls": [{"number": 12, "title": "Fix expiry", "state": "merged",
                       "draft": False, "author": "alice"}],
        })
        doc = c.get("/repos/owner/repo/pulls").json()
        assert doc["pulls"][0]["number"] == 12
        assert doc["age_hours"] is not None and doc["age_hours"] < 1
    print("  ok: recent-pulls read (404 -> cached list + age labeling)")


def test_health_root_and_config():
    with _client(settings=Settings(github_token="secret-token")) as c:
        assert c.get("/health").json()["store"] == "fake"
        assert c.get("/").json()["docs"] == "/docs"
        cfg = c.get("/config").json()
        assert cfg["github_token"] == "***"          # masked, never leaked
        assert cfg["llm_provider"] == "local"
    # multiuser secrets must be masked too (fernet_key leaked here once), and
    # a DATABASE_URL with embedded credentials must have them redacted
    s2 = Settings(github_token="t", fernet_key="fk", session_secret="ss",
                  github_oauth_client_secret="cs",
                  database_url="postgresql://admin:hunter2@db:5432/gitpulse")
    with _client(settings=s2) as c:
        cfg = c.get("/config").json()
        assert cfg["fernet_key"] == "***"
        assert cfg["session_secret"] == "***"
        assert cfg["github_oauth_client_secret"] == "***"
        assert "hunter2" not in cfg["database_url"]
        assert cfg["database_url"] == "postgresql://***@db:5432/gitpulse"
    print("  ok: health / root / masked config (incl. multiuser secrets)")


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
        # negative top used to hit Python negative slicing ("all but last 5")
        assert c.get("/repos/owner/repo/hotspots?top=-5").status_code == 422
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

    # identity/mailer ride along so the webhook can email the finished report;
    # both are None on this single-user client
    def fake_review(pl, st, store, identity=None, mailer=None, progress=None):
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
        # keyword "fix" that only touched docs: must NOT wear a BUGFIX badge
        # or count toward the bug-fix ratio (display gate = scorer's gate)
        {"sha": "dddd4444", "author": "bob",
         "date": now - timedelta(days=1, hours=1),
         "message": "Fix typo in the changelog", "is_bugfix": True,
         "files": [{"path": "CHANGES.rst", "insertions": 1, "deletions": 1}]},
    ])
    store.save_report("commit_quality", "owner/repo", {"avg_score": 8.0})
    with _client(store=store) as c:
        assert c.get("/repos/nope/activity").status_code == 404
        body = c.get("/repos/owner/repo/activity").json()
        assert body["total_commits"] == 4
        assert body["window_commits"] == 3          # 400-day-old commit excluded
        # only the code fix counts: docs-only "fix" is gated out -> 1 of 3
        assert body["window_bugfix_ratio"] == 0.333
        assert body["contributors"][0] == {"author": "alice", "commits": 2,
                                           "share": 0.5}
        assert body["recent_commits"][0]["sha"] == "aaaa111"   # newest first, 7 chars
        assert body["recent_commits"][0]["subject"] == "Fix crash in parser"
        badges = {r["sha"]: r["is_bugfix"] for r in body["recent_commits"]}
        assert badges["aaaa111"] is True    # no file info cached -> trust flag
        assert badges["dddd444"] is False   # docs-only fix -> no badge
        # heatmap spans all history (incl. the 400-day-old commit), unlike
        # the windowed stats above
        assert sum(d["count"] for d in body["heatmap"]) == 4
        # health composite: 0.6*8.0 + 0.4*(1 - 0.333)*10 = 7.5 (rounded)
        assert body["health"]["score"] == 7.5
        # param validation: negative/zero values are rejected, not sliced
        assert c.get("/repos/owner/repo/activity?days=0").status_code == 422
        assert c.get("/repos/owner/repo/activity?recent=-1").status_code == 422
        # the base cap is a contract now, not a silent slice
        assert c.get("/repos/owner/repo/activity?recent=51").status_code == 422

        # the first GET healed the cache: the aggregate is stored, and serving
        # no longer reads the commit list at all (the perf fix under test)
        assert store.load_report("activity_base", "owner/repo") is not None
        store.commits.clear()
        body2 = c.get("/repos/owner/repo/activity").json()
        assert body2["total_commits"] == 4
        assert body2["window_commits"] == 3
        assert body2["health"]["score"] == 7.5
    print("  ok: activity endpoint (window, gate, contributors, heatmap, health)")


def test_insights_bullet_filter():
    """keep_bullet drops the local-model failure mode we saw live: tool
    advice with no numbers ("use git log to view history")."""
    from core.insights import keep_bullet

    assert keep_bullet("44 of 96 recent commits were bug fixes, concentrated "
                       "in 3 of the top 5 hotspot files")
    # no digits -> not derived from the stats digest
    assert not keep_bullet("Maintainers can use the `git log` command to view history")
    assert not keep_bullet("The codebase appears healthy overall")
    # advice phrasing is rejected even when it carries a number
    assert not keep_bullet("Consider reviewing the 5 riskiest files")
    assert not keep_bullet("You can inspect the 46993 cached commits")
    print("  ok: insights bullet filter (digits required, advice rejected)")


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
