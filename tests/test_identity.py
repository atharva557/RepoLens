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
    hash_session,
    new_session_token,
    open_identity,
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
    assert ident.user_repo_keys(u["id"]) == ["pallets/flask", "psf/requests"]
    ident.untrack_repo(u["id"], "pallets/flask")
    assert ident.user_repo_keys(u["id"]) == ["psf/requests"]

    ident.save_llm_config(u["id"], "openai", "sk-xyz", model="gpt-4o-mini")
    cfg = ident.get_llm_config(u["id"])
    assert cfg == {"provider": "openai", "model": "gpt-4o-mini", "base_url": ""}
    assert "api_key" not in cfg  # key only with explicit with_key=True
    assert ident.get_llm_config(u["id"], with_key=True)["api_key"] == "sk-xyz"
    ident.delete_llm_config(u["id"])
    assert ident.get_llm_config(u["id"]) is None
    print("  ok: repo tracking + encrypted LLM config")


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
        # reads stay open in this slice (per-repo ACLs are the next step)
        assert client.get("/health").status_code == 200
    print("  ok: multiuser triggers demand a session; reads unaffected")


def _run_all():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    print(f"running {len(fns)} test(s)...")
    for fn in fns:
        fn()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    _run_all()
