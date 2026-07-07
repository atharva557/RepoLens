"""Auth & account routes (spec §7.4 / §8) — enabled by MULTIUSER=true.

Sign-in is GitHub OAuth: login and token-acquisition are the same step, so
nobody pastes a token (spec §8.1). The web-flow code exchange is two HTTPS
calls, done with stdlib urllib to keep the auth slice dependency-light (the
spec sketched authlib; the flow is small enough that a library adds more
surface than it removes — the endpoints and semantics are unchanged).

Session cookie: httpOnly, SameSite=Lax, value = secrets.token_urlsafe(32);
Postgres stores only its SHA-256 hash. CSRF: SameSite=Lax plus a required
custom header (X-GitPulse-Client) on every mutating route — cross-site forms
cannot set custom headers.

Route pattern follows api/webhook.py precedent: routes always exist and return
503 when the feature is disabled.
"""
from __future__ import annotations

import json
import secrets
import time
import urllib.parse
import urllib.request

from fastapi import HTTPException, Request

SESSION_COOKIE = "gitpulse_session"
CSRF_HEADER = "x-gitpulse-client"       # required value: "dashboard"
OAUTH_SCOPES = "read:user"              # minimal at login (spec §7.4)
_STATE_TTL_SECS = 600

# in-process OAuth state nonces (single-process uvicorn, like api/jobs.py)
_pending_states: dict[str, float] = {}


def _issue_state() -> str:
    now = time.time()
    for s, t in list(_pending_states.items()):  # opportunistic prune
        if now - t > _STATE_TTL_SECS:
            del _pending_states[s]
    state = secrets.token_urlsafe(16)
    _pending_states[state] = now
    return state


def _consume_state(state: str) -> bool:
    t = _pending_states.pop(state or "", None)
    return t is not None and time.time() - t <= _STATE_TTL_SECS


# --------------------------------------------------------------------------- #
# GitHub OAuth web flow (stubbed in tests)
# --------------------------------------------------------------------------- #
def exchange_code(client_id: str, client_secret: str, code: str) -> str:
    """code -> access token (POST github.com/login/oauth/access_token)."""
    body = urllib.parse.urlencode({
        "client_id": client_id, "client_secret": client_secret, "code": code,
    }).encode()
    req = urllib.request.Request(
        "https://github.com/login/oauth/access_token", body,
        {"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.load(resp)
    token = data.get("access_token")
    if not token:
        raise ValueError(f"GitHub OAuth exchange failed: {data.get('error', '?')}")
    return token


def fetch_github_user(token: str) -> dict:
    """token -> {id, login, email} (GET api.github.com/user)."""
    req = urllib.request.Request(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        u = json.load(resp)
    return {"id": u["id"], "login": u.get("login", ""), "email": u.get("email")}


# --------------------------------------------------------------------------- #
# request helpers used by api/main.py as well
# --------------------------------------------------------------------------- #
def _identity(request: Request):
    identity = getattr(request.app.state, "identity", None)
    if identity is None:
        raise HTTPException(503, "multiuser mode is disabled (MULTIUSER=false)")
    return identity


def current_user(request: Request) -> dict | None:
    """Resolve the session cookie to a user dict, or None."""
    identity = getattr(request.app.state, "identity", None)
    token = request.cookies.get(SESSION_COOKIE, "")
    if identity is None or not token:
        return None
    return identity.user_for_session(token)


def require_user(request: Request) -> dict:
    user = current_user(request)
    if user is None:
        raise HTTPException(401, "not signed in")
    return user


def require_csrf(request: Request) -> None:
    if request.headers.get(CSRF_HEADER, "").lower() != "dashboard":
        raise HTTPException(403, f"missing {CSRF_HEADER} header")


def add_auth_routes(app) -> None:
    """Register the §7.4 endpoints on the app (called from create_app)."""
    from fastapi.responses import RedirectResponse

    @app.get("/api/v1/auth/github/login")
    def github_login(request: Request):
        identity = _identity(request)  # 503 when multiuser is off
        s = request.app.state.settings
        if not s.github_oauth_client_id:
            raise HTTPException(503, "GITHUB_OAUTH_CLIENT_ID is not configured")
        params = urllib.parse.urlencode({
            "client_id": s.github_oauth_client_id,
            "scope": OAUTH_SCOPES,
            "state": _issue_state(),
        })
        return RedirectResponse(
            f"https://github.com/login/oauth/authorize?{params}", status_code=302)

    @app.get("/api/v1/auth/github/callback")
    def github_callback(request: Request, code: str = "", state: str = ""):
        identity = _identity(request)
        s = request.app.state.settings
        if not _consume_state(state):
            raise HTTPException(400, "invalid or expired OAuth state")
        if not code:
            raise HTTPException(400, "missing OAuth code")
        try:
            gh_token = exchange_code(
                s.github_oauth_client_id, s.github_oauth_client_secret, code)
            gh_user = fetch_github_user(gh_token)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(502, f"GitHub OAuth failed: {exc}")

        user = identity.upsert_github_user(
            gh_user["id"], gh_user["login"], gh_user.get("email"))
        identity.save_github_token(user["id"], gh_token, OAUTH_SCOPES)
        session = identity.create_session(user["id"])

        resp = RedirectResponse(s.dashboard_origin, status_code=302)
        resp.set_cookie(
            SESSION_COOKIE, session,
            httponly=True, samesite="lax",
            secure=request.url.scheme == "https",  # Secure breaks plain-http dev
            max_age=30 * 24 * 3600,
        )
        return resp

    @app.post("/api/v1/auth/logout")
    def logout(request: Request):
        identity = _identity(request)
        require_csrf(request)
        user = current_user(request)
        token = request.cookies.get(SESSION_COOKIE, "")
        if token:
            identity.delete_session(token)
        if user:
            identity.audit(user["id"], "logout")
        from fastapi.responses import JSONResponse

        resp = JSONResponse({"ok": True})
        resp.delete_cookie(SESSION_COOKIE)
        return resp

    @app.get("/api/v1/me")
    def me(request: Request):
        _identity(request)
        user = require_user(request)
        identity = request.app.state.identity
        llm = identity.get_llm_config(user["id"])  # never includes the key
        return {
            "user": {k: user[k] for k in ("id", "github_id", "github_login", "email")},
            "has_github_token": identity.get_github_token(user["id"]) is not None,
            "llm": {"provider": llm["provider"], "model": llm["model"]} if llm else None,
            "repos": identity.user_repo_keys(user["id"]),
        }

    @app.put("/api/v1/me/llm")
    def save_llm(request: Request, body: dict):
        identity = _identity(request)
        require_csrf(request)
        user = require_user(request)
        provider = (body.get("provider") or "").lower()
        api_key = body.get("api_key") or ""
        if provider not in ("openai", "claude", "gemini") or not api_key:
            raise HTTPException(400, "body needs provider (openai|claude|gemini) and api_key")
        identity.save_llm_config(user["id"], provider, api_key,
                                 model=body.get("model", ""),
                                 base_url=body.get("base_url", ""))
        return {"ok": True, "provider": provider}

    @app.delete("/api/v1/me/llm")
    def delete_llm(request: Request):
        identity = _identity(request)
        require_csrf(request)
        user = require_user(request)
        identity.delete_llm_config(user["id"])
        return {"ok": True}

    @app.delete("/api/v1/me/github-token")
    def revoke_token(request: Request):
        identity = _identity(request)
        require_csrf(request)
        user = require_user(request)
        identity.revoke_github_token(user["id"])
        return {"ok": True}
