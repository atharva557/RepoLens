"""Tests for the multi-user identity plane (Postgres slice, spec §6.4/§7.4/§8).

All network/DB-free: crypto helpers run against the real cryptography lib
(suite skips if it isn't installed), the store tests use MemoryIdentity, and
the auth API tests use FastAPI's TestClient with the OAuth exchange stubbed
(skipped if fastapi isn't installed).

    python tests/test_identity.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from importlib.util import find_spec

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if find_spec("cryptography") is None:  # pragma: no cover
    print("cryptography not installed - skipping identity tests")
    sys.exit(0)

from cryptography.fernet import Fernet

from core.identity import (
    MemoryIdentity,
    decrypt_secret,
    encrypt_secret,
    hash_password,
    hash_session,
    new_session_token,
    open_identity,
    verify_password,
)

FKEY = Fernet.generate_key().decode()


def test_crypto_discipline():
    # encrypt/decrypt round-trips; ciphertext never contains the plaintext
    enc = encrypt_secret(FKEY, "ghp_secret123")
    assert b"ghp_secret123" not in enc
    assert decrypt_secret(FKEY, enc) == "ghp_secret123"

    # sessions: hashed (deterministic), tokens unique and never stored raw
    t1, t2 = new_session_token(), new_session_token()
    assert t1 != t2 and len(t1) >= 32
    assert hash_session(t1) == hash_session(t1) != hash_session(t2)
    assert t1 not in hash_session(t1)
    print("  ok: crypto discipline (encrypt tokens, hash sessions)")


def test_user_and_token_lifecycle():
    ident = MemoryIdentity(FKEY)
    u = ident.upsert_github_user(42, "octocat", "o@example.com")
    assert u["id"] == 1 and u["github_login"] == "octocat"

    # upsert by github_id is idempotent (login refresh, not a new row)
    again = ident.upsert_github_user(42, "octocat-renamed", None)
    assert again["id"] == 1 and again["github_login"] == "octocat-renamed"
    assert again["email"] == "o@example.com"  # None must not clobber

    # GitHub token: stored encrypted, recoverable, revocable
    ident.save_github_token(1, "ghp_abc", "read:user")
    assert ident.get_github_token(1) == "ghp_abc"
    assert ident.users[1]["gh_token_enc"] != b"ghp_abc"
    ident.revoke_github_token(1)
    assert ident.get_github_token(1) is None

    actions = [a["action"] for a in ident.audit_log]
    assert "gh_token_saved" in actions and "gh_token_revoked" in actions
    print("  ok: user upsert + encrypted token lifecycle (audited)")


def test_session_lifecycle():
    ident = MemoryIdentity(FKEY)
    u = ident.upsert_github_user(7, "dev", None)
    token = ident.create_session(u["id"])

    assert ident.user_for_session(token)["id"] == u["id"]
    assert ident.user_for_session("wrong-token") is None

    # expired sessions are rejected and cleaned up
    ident.sessions[hash_session(token)]["expires_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=1))
    assert ident.user_for_session(token) is None
    assert hash_session(token) not in ident.sessions

    # logout deletes
    token2 = ident.create_session(u["id"])
    ident.delete_session(token2)
    assert ident.user_for_session(token2) is None
    print("  ok: session create / resolve / expire / delete")


def test_repos_and_llm_config():
    ident = MemoryIdentity(FKEY)
    u = ident.upsert_github_user(9, "dev", None)
    ident.track_repo(u["id"], "pallets/flask")
    ident.track_repo(u["id"], "psf/requests", role="owner")
    # most-recently-searched first; re-tracking refreshes the recency
    assert ident.user_repo_keys(u["id"]) == ["psf/requests", "pallets/flask"]
    ident.track_repo(u["id"], "pallets/flask")
    assert ident.user_repo_keys(u["id"]) == ["pallets/flask", "psf/requests"]
    ident.untrack_repo(u["id"], "pallets/flask")
    assert ident.user_repo_keys(u["id"]) == ["psf/requests"]

    # searched developer profiles follow the same per-user recency list
    ident.track_profile(u["id"], "octocat")
    ident.track_profile(u["id"], "torvalds")
    assert ident.user_profile_names(u["id"]) == ["torvalds", "octocat"]
    assert ident.user_profile_names(999) == []  # other users see nothing
    assert "profile_track" in [a["action"] for a in ident.audit_log]

    ident.save_llm_config(u["id"], "openai", "sk-xyz", model="gpt-4o-mini")
    cfg = ident.get_llm_config(u["id"])
    assert cfg == {"provider": "openai", "model": "gpt-4o-mini", "base_url": ""}
    assert "api_key" not in cfg  # key only with explicit with_key=True
    assert ident.get_llm_config(u["id"], with_key=True)["api_key"] == "sk-xyz"
    ident.delete_llm_config(u["id"])
    assert ident.get_llm_config(u["id"]) is None
    print("  ok: repo tracking + encrypted LLM config")


def test_password_hashing():
    stored = hash_password("hunter22")
    # salted scrypt: self-describing format, plaintext absent, unique salts
    assert stored.startswith("scrypt$") and "hunter22" not in stored
    assert stored != hash_password("hunter22")
    assert verify_password("hunter22", stored) is True
    assert verify_password("hunter23", stored) is False
    assert verify_password("hunter22", "") is False
    assert verify_password("hunter22", "garbage$x") is False
    print("  ok: password hashing (salted scrypt, verify, tamper-safe)")


def test_password_user_lifecycle():
    ident = MemoryIdentity(FKEY)
    u = ident.create_password_user("a@b.com", hash_password("longenough"))
    assert u["email"] == "a@b.com" and u["github_id"] is None
    assert "password_hash" not in u                    # never leaves login
    assert "password_hash" not in ident.get_user(u["id"])
    # the login lookup is the one path that sees the hash (case-insensitive)
    row = ident.get_password_user("A@B.COM")
    assert row and verify_password("longenough", row["password_hash"])
    assert ident.get_password_user("nope@b.com") is None
    assert "signup" in [a["action"] for a in ident.audit_log]

    # IDENTITY_BACKEND=memory is the dev escape hatch behind open_identity
    from types import SimpleNamespace

    dev = open_identity(SimpleNamespace(multiuser=True, fernet_key=FKEY,
                                        identity_backend="memory"))
    assert isinstance(dev, MemoryIdentity)
    print("  ok: password users (hash discipline) + memory dev backend")


def test_signup_login_api_flow():
    if find_spec("fastapi") is None:  # pragma: no cover
        print("  skip: fastapi not installed (auth API tests)")
        return
    client, identity = _api_client()
    csrf = {"X-GitPulse-Client": "dashboard"}
    with client:
        # CSRF header is demanded before anything else happens
        assert client.post("/api/v1/auth/signup",
                           json={"email": "a@b.com", "password": "longenough"}
                           ).status_code == 403
        # validation: bad email / short password
        assert client.post("/api/v1/auth/signup", headers=csrf,
                           json={"email": "not-an-email", "password": "longenough"}
                           ).status_code == 422
        assert client.post("/api/v1/auth/signup", headers=csrf,
                           json={"email": "a@b.com", "password": "short"}
                           ).status_code == 422

        # signup signs the user in (cookie set) and normalizes the email
        r = client.post("/api/v1/auth/signup", headers=csrf,
                        json={"email": " A@B.com ", "password": "longenough"})
        assert r.status_code == 201
        assert import_auth().SESSION_COOKIE in r.cookies
        assert r.json()["user"]["email"] == "a@b.com"
        me = client.get("/api/v1/me").json()
        assert me["user"]["email"] == "a@b.com"
        assert me["user"]["github_login"] is None

        # duplicate email refused
        assert client.post("/api/v1/auth/signup", headers=csrf,
                           json={"email": "a@b.com", "password": "longenough2"}
                           ).status_code == 409

        # logout, then log back in; wrong password = one generic 401
        assert client.post("/api/v1/auth/logout", headers=csrf).status_code == 200
        client.cookies.clear()
        assert client.get("/api/v1/me").status_code == 401
        assert client.post("/api/v1/auth/login", headers=csrf,
                           json={"email": "a@b.com", "password": "wrongwrong"}
                           ).status_code == 401
        assert client.post("/api/v1/auth/login", headers=csrf,
                           json={"email": "nobody@b.com", "password": "longenough"}
                           ).status_code == 401
        r = client.post("/api/v1/auth/login", headers=csrf,
                        json={"email": "A@b.com", "password": "longenough"})
        assert r.status_code == 200
        assert client.get("/api/v1/me").json()["user"]["email"] == "a@b.com"
        assert "login_failed" in [a["action"] for a in identity.audit_log]
    print("  ok: signup -> session; login (generic 401) -> session; CSRF gates")


def import_auth():
    import api.auth as auth

    return auth


def test_open_identity_gates():
    from types import SimpleNamespace

    # MULTIUSER=false -> no identity plane at all
    assert open_identity(SimpleNamespace(multiuser=False)) is None
    # MULTIUSER=true without FERNET_KEY -> hard, explanatory error
    try:
        open_identity(SimpleNamespace(multiuser=True, fernet_key="",
                                      database_url="postgresql://x/y"))
    except RuntimeError as exc:
        assert "FERNET_KEY" in str(exc)
        print("  ok: open_identity gating (off -> None, no key -> error)")
        return
    raise AssertionError("expected RuntimeError without FERNET_KEY")


# --------------------------------------------------------------------------- #
# auth API surface (skipped without fastapi, like tests/test_api.py)
# --------------------------------------------------------------------------- #
def _api_client(multiuser=True):
    from fastapi.testclient import TestClient

    import api.main as api_main
    from config.settings import Settings

    settings = Settings()
    settings.multiuser = multiuser
    settings.fernet_key = FKEY
    settings.github_oauth_client_id = "cid"
    settings.github_oauth_client_secret = "csecret"
    settings.store_backend = "json"
    settings.cache_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "_identity_tmp")

    # only multiuser mode has an identity plane (create_app resolves None)
    identity = MemoryIdentity(FKEY) if multiuser else None
    app = api_main.create_app(settings=settings, identity=identity)
    return TestClient(app), identity


def test_auth_routes_disabled_without_multiuser():
    if find_spec("fastapi") is None:  # pragma: no cover
        print("  skip: fastapi not installed (auth API tests)")
        return
    client, _ = _api_client(multiuser=False)
    with client:
        assert client.get("/api/v1/me").status_code == 503
        assert client.get("/api/v1/auth/github/login",
                          follow_redirects=False).status_code == 503
        # single-user triggers stay open (no session needed)
        r = client.post("/analyze", json={"repo": "x"})
        assert r.status_code == 202
    print("  ok: auth surface answers 503 while MULTIUSER=false")


def test_oauth_login_and_session_flow():
    if find_spec("fastapi") is None:  # pragma: no cover
        print("  skip: fastapi not installed (auth API tests)")
        return
    import api.auth as auth

    client, identity = _api_client()
    auth.exchange_code = lambda cid, cs, code: "ghp_tok"
    auth.fetch_github_user = lambda tok: {"id": 42, "login": "octocat",
                                          "email": "o@example.com"}
    with client:
        # login redirects to GitHub with our client id + a state nonce
        r = client.get("/api/v1/auth/github/login", follow_redirects=False)
        assert r.status_code == 302
        loc = r.headers["location"]
        assert "github.com/login/oauth/authorize" in loc and "client_id=cid" in loc
        state = loc.split("state=")[1].split("&")[0]

        # bad state is rejected; good state signs the user in
        assert client.get("/api/v1/auth/github/callback?code=c&state=nope",
                          follow_redirects=False).status_code == 400
        r = client.get(f"/api/v1/auth/github/callback?code=c&state={state}",
                       follow_redirects=False)
        assert r.status_code == 302
        assert auth.SESSION_COOKIE in r.cookies

        # the session cookie now authenticates /me
        me = client.get("/api/v1/me").json()
        assert me["user"]["github_login"] == "octocat"
        assert me["has_github_token"] is True
        assert identity.get_github_token(me["user"]["id"]) == "ghp_tok"

        # multiuser triggers require the session + record created_by
        job = client.post("/analyze", json={"repo": "x"}).json()
        params = client.get(f"/jobs/{job['job_id']}").json()["params"]
        assert params["created_by"] == "octocat"

        # mutating account routes demand the CSRF header
        assert client.delete("/api/v1/me/github-token").status_code == 403
        r = client.delete("/api/v1/me/github-token",
                          headers={"X-GitPulse-Client": "dashboard"})
        assert r.status_code == 200
        assert client.get("/api/v1/me").json()["has_github_token"] is False

        # logout kills the session
        r = client.post("/api/v1/auth/logout",
                        headers={"X-GitPulse-Client": "dashboard"})
        assert r.status_code == 200
        client.cookies.clear()
        assert client.get("/api/v1/me").status_code == 401
    print("  ok: OAuth callback -> session cookie -> /me -> CSRF -> logout")


def test_triggers_require_session_in_multiuser():
    if find_spec("fastapi") is None:  # pragma: no cover
        print("  skip: fastapi not installed (auth API tests)")
        return
    client, _ = _api_client()
    with client:
        assert client.post("/analyze", json={"repo": "x"}).status_code == 401
        # unkeyed diagnostics stay open (no per-user data in them)
        assert client.get("/health").status_code == 200
    print("  ok: multiuser triggers demand a session; /health unaffected")


def test_keyed_reads_are_owner_only_in_multiuser():
    """Scoping only the discovery lists was not access control: repo keys are
    guessable, so a direct read must prove ownership too."""
    if find_spec("fastapi") is None:  # pragma: no cover
        print("  skip: fastapi not installed (auth API tests)")
        return
    from api.auth import SESSION_COOKIE

    client, identity = _api_client()
    with client:  # the store is opened by the lifespan, not at build time
        store = client.app.state.store
        store.save_hotspots("victim/repo", [{"path": "secret/auth.py", "score": 0.9}])
        store.save_report("developer_profile", "victim", {"primary_type": "Bug Fixer"})

        keyed = ["/repos/victim/repo/hotspots", "/repos/victim/repo/commit-quality",
                 "/repos/victim/repo/activity", "/repos/victim/repo/insights",
                 "/repos/victim/repo/pr-reviews", "/profiles/victim"]

        # anonymous: 401 (actionable — sign in), never the data
        for path in keyed:
            assert client.get(path).status_code == 401, path

        # signed in, but doesn't track these keys: 404, indistinguishable from
        # "never analyzed" so it can't enumerate other accounts' work
        mallory = identity.create_password_user("m@example.com", "hash")
        client.cookies.set(SESSION_COOKIE, identity.create_session(mallory["id"]))
        for path in keyed:
            assert client.get(path).status_code == 404, path

        # the owner still reads their own data normally
        identity.track_repo(mallory["id"], "victim/repo")
        identity.track_profile(mallory["id"], "victim")
        body = client.get("/repos/victim/repo/hotspots").json()
        assert body["rows"][0]["path"] == "secret/auth.py"
        assert client.get("/profiles/victim").json()["primary_type"] == "Bug Fixer"
    print("  ok: keyed reads are owner-only (401 anon / 404 stranger / 200 owner)")


def test_jobs_are_owner_only_in_multiuser():
    if find_spec("fastapi") is None:  # pragma: no cover
        print("  skip: fastapi not installed (auth API tests)")
        return
    import api.main as api_main
    from api.auth import SESSION_COOKIE

    client, identity = _api_client()
    orig = api_main.run_hotspot_analysis
    api_main.run_hotspot_analysis = lambda *a, **k: {
        "repo": "x", "commits": 1, "bugfix_commits": 0, "files_scored": 0,
        "ml_used": False, "scores": []}
    try:
        with client:
            alice = identity.create_password_user("a@example.com", "hash")
            client.cookies.set(SESSION_COOKIE, identity.create_session(alice["id"]))
            job_id = client.post("/analyze", json={"repo": "x"}).json()["job_id"]
            assert client.get(f"/jobs/{job_id}").status_code == 200

            client.cookies.clear()                       # anonymous
            assert client.get(f"/jobs/{job_id}").status_code == 401
            bob = identity.create_password_user("b@example.com", "hash")
            client.cookies.set(SESSION_COOKIE, identity.create_session(bob["id"]))
            assert client.get(f"/jobs/{job_id}").status_code == 404
    finally:
        api_main.run_hotspot_analysis = orig
    print("  ok: job status (params + result) is readable only by its creator")


def test_user_settings_overlays_stored_credentials():
    """The encrypted per-user token/key must actually reach the engine —
    storing them and then running every job on the server's global config
    made the whole BYO-key surface a no-op."""
    from config.settings import Settings
    from core.identity import user_settings

    identity = MemoryIdentity(FKEY)
    user = identity.create_password_user("byo@example.com", "hash")
    base = Settings(github_token="SERVER", llm_provider="local",
                    llm_model="local-model")

    # nothing stored -> the global config is used unchanged
    assert user_settings(base, identity, user["id"]) is base

    identity.save_github_token(user["id"], "ghp_user", "read:user")
    identity.save_llm_config(user["id"], "claude", "sk-ant-user")
    eff = user_settings(base, identity, user["id"])
    assert eff.github_token == "ghp_user"
    assert eff.llm_provider == "claude" and eff.anthropic_api_key == "sk-ant-user"
    # the global provider's model must not ride along to a different provider
    assert eff.llm_model == ""
    # and the shared global object is never mutated (concurrent jobs, other users)
    assert base.github_token == "SERVER" and base.llm_model == "local-model"

    # an explicit per-user model is honoured
    identity.save_llm_config(user["id"], "openai", "sk-oai", model="gpt-4o")
    eff = user_settings(base, identity, user["id"])
    assert eff.llm_provider == "openai" and eff.llm_model == "gpt-4o"
    assert eff.openai_api_key == "sk-oai"
    print("  ok: stored per-user GitHub token + LLM key overlay the global settings")


# --------------------------------------------------------------------------- #
# real Postgres (opt-in): set TEST_DATABASE_URL to a throwaway database, e.g.
#   set TEST_DATABASE_URL=postgresql://postgres:pw@localhost:5432/gitpulse_test
# Skipped otherwise, so the suite stays network-free by default. MemoryIdentity
# enforces no constraints, so these are the only tests that exercise the real
# schema — the UNIQUE(email) that broke OAuth-over-password only exists here.
# --------------------------------------------------------------------------- #
def _pg_url():
    return os.environ.get("TEST_DATABASE_URL", "").strip()


def _fresh_pg():
    """A PgIdentity on an empty schema, or None when unavailable."""
    from core.identity import PgIdentity

    url = _pg_url()
    if not url or find_spec("psycopg") is None:
        return None
    ident = PgIdentity(url, FKEY)
    ident.ensure_schema()
    with ident._cursor() as cur:  # throwaway DB: start every run clean
        cur.execute("TRUNCATE audit_log, llm_configs, user_profiles, "
                    "user_repos, sessions, users RESTART IDENTITY CASCADE")
    return ident


def test_postgres_roundtrip():
    ident = _fresh_pg()
    if ident is None:
        print("  skip: set TEST_DATABASE_URL to run the real-Postgres tests")
        return

    # password signup -> login lookup -> session -> sliding resolve
    user = ident.create_password_user("pg@example.com", hash_password("s3cret-pw"))
    assert ident.get_password_user("PG@example.com")["id"] == user["id"]
    assert verify_password("s3cret-pw", ident.get_password_user("pg@example.com")["password_hash"])
    token = ident.create_session(user["id"])
    resolved = ident.user_for_session(token)
    assert resolved["id"] == user["id"] and resolved["email"] == "pg@example.com"
    assert "password_hash" not in resolved      # never leaves the login path
    ident.delete_session(token)
    assert ident.user_for_session(token) is None
    assert ident.user_for_session("not-a-real-token") is None

    # encrypted secrets round-trip through the real BYTEA columns
    ident.save_github_token(user["id"], "ghp_pg", "read:user")
    assert ident.get_github_token(user["id"]) == "ghp_pg"
    ident.save_llm_config(user["id"], "claude", "sk-ant-pg", model="m")
    assert ident.get_llm_config(user["id"], with_key=True)["api_key"] == "sk-ant-pg"
    assert "api_key" not in ident.get_llm_config(user["id"])

    # tracking + ordering (most recently searched first)
    ident.track_repo(user["id"], "owner/one")
    ident.track_repo(user["id"], "owner/two")
    assert set(ident.user_repo_keys(user["id"])) == {"owner/one", "owner/two"}
    ident.track_profile(user["id"], "octocat")
    assert ident.user_profile_names(user["id"]) == ["octocat"]
    print("  ok: Postgres round-trip (accounts, sessions, secrets, tracking)")


def test_postgres_oauth_links_existing_password_account():
    """The bug MemoryIdentity could never show: users.email is UNIQUE, so a
    GitHub sign-in for an address that already has a password account used to
    raise a unique violation and 502 the OAuth callback."""
    ident = _fresh_pg()
    if ident is None:
        print("  skip: set TEST_DATABASE_URL to run the real-Postgres tests")
        return

    existing = ident.create_password_user("dual@example.com", hash_password("pw-12345678"))
    linked = ident.upsert_github_user(4242, "dualuser", "dual@example.com")
    assert linked["id"] == existing["id"], "must adopt the account, not duplicate it"
    assert linked["github_id"] == 4242 and linked["github_login"] == "dualuser"

    # the password path still works after linking, and re-auth is idempotent
    assert ident.get_password_user("dual@example.com")["id"] == existing["id"]
    again = ident.upsert_github_user(4242, "renamed", "dual@example.com")
    assert again["id"] == existing["id"] and again["github_login"] == "renamed"

    with ident._cursor() as cur:
        cur.execute("SELECT count(*) FROM users WHERE lower(email) = 'dual@example.com'")
        assert cur.fetchone()[0] == 1
    print("  ok: GitHub sign-in links an existing password account (no duplicate)")


def test_postgres_expired_session_is_rejected_and_cleared():
    ident = _fresh_pg()
    if ident is None:
        print("  skip: set TEST_DATABASE_URL to run the real-Postgres tests")
        return

    user = ident.create_password_user("exp@example.com", hash_password("pw-12345678"))
    token = ident.create_session(user["id"])
    with ident._cursor() as cur:  # force it into the past
        cur.execute("UPDATE sessions SET expires_at = %s WHERE token_hash = %s",
                    (datetime.now(timezone.utc) - timedelta(seconds=1),
                     hash_session(token)))
    assert ident.user_for_session(token) is None
    with ident._cursor() as cur:
        cur.execute("SELECT count(*) FROM sessions WHERE token_hash = %s",
                    (hash_session(token),))
        assert cur.fetchone()[0] == 0, "expired row should be cleared on access"
    print("  ok: expired Postgres sessions are rejected and deleted")


def test_postgres_reconnects_after_a_dropped_connection():
    """A dead handle used to break sign-in until the API process restarted."""
    ident = _fresh_pg()
    if ident is None:
        print("  skip: set TEST_DATABASE_URL to run the real-Postgres tests")
        return

    user = ident.create_password_user("rc@example.com", hash_password("pw-12345678"))
    token = ident.create_session(user["id"])
    ident.conn.close()                       # simulate a restart / dropped link
    assert ident.conn.closed
    assert ident.user_for_session(token)["id"] == user["id"]
    assert not ident.conn.closed
    print("  ok: identity store reconnects after the connection drops")


def _run_all():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    print(f"running {len(fns)} test(s)...")
    for fn in fns:
        fn()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    _run_all()
