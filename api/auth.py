"""Auth & account routes (spec §7.4 / §8) — enabled by MULTIUSER=true.

Two sign-in paths share one session plane:

- **Email + password** (`/signup` -> `/signup/verify`, `/login`): salted-scrypt
  hashes via core.identity.hash_password; login answers a single "invalid email
  or password" so it never confirms which half was wrong. Signup is two steps —
  `/signup` emails a code and creates nothing, `/signup/verify` exchanges the
  code for the account and a session. Nothing is written to `users` until the
  address is proven, so an unverified signup can't squat the UNIQUE(email) that
  the GitHub path also depends on.
- **GitHub OAuth**: login and token-acquisition in one step, so nobody
  pastes a token (spec §8.1). The web-flow code exchange is two HTTPS
  calls, done with stdlib urllib to keep the auth slice dependency-light
  (the spec sketched authlib; the flow is small enough that a library adds
  more surface than it removes — the endpoints and semantics are unchanged).

Session cookie: httpOnly, SameSite=Lax, value = secrets.token_urlsafe(32);
Postgres stores only its SHA-256 hash. CSRF: SameSite=Lax plus a required
custom header (X-GitPulse-Client) on every mutating route — cross-site forms
cannot set custom headers.

Route pattern follows api/webhook.py precedent: routes always exist and return
503 when the feature is disabled.
"""
from __future__ import annotations

import json
import re
import secrets
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from fastapi import BackgroundTasks, HTTPException, Request

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LEN = 8

SESSION_COOKIE = "gitpulse_session"
CSRF_HEADER = "x-gitpulse-client"       # required value: "dashboard"
OAUTH_SCOPES = "read:user"              # minimal at login (spec §7.4)
_STATE_TTL_SECS = 600

# Per-IP cap on code requests. The per-address cooldown lives in Postgres
# (email_otps.sent_at); this one stops a single caller cycling through
# addresses to use the signup route as an email cannon. In-process, like the
# OAuth nonces above and api/jobs.py — single-process uvicorn.
OTP_IP_WINDOW_SECS = 3600
OTP_IP_MAX_REQUESTS = 20

# in-process OAuth state nonces (single-process uvicorn, like api/jobs.py)
_pending_states: dict[str, float] = {}
_otp_ip_hits: dict[str, list[float]] = {}


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


def _rate_limit_ip(request: Request) -> None:
    """429 once one client has asked for too many codes in the window."""
    ip = getattr(request.client, "host", "") or "unknown"
    now = time.time()
    hits = [t for t in _otp_ip_hits.get(ip, []) if now - t < OTP_IP_WINDOW_SECS]
    if len(hits) >= OTP_IP_MAX_REQUESTS:
        _otp_ip_hits[ip] = hits
        raise HTTPException(429, "too many verification codes requested; "
                                 "try again later")
    hits.append(now)
    _otp_ip_hits[ip] = hits
    if len(_otp_ip_hits) > 4096:  # opportunistic prune, like _issue_state
        for k in [k for k, v in _otp_ip_hits.items()
                  if not v or now - v[-1] > OTP_IP_WINDOW_SECS]:
            del _otp_ip_hits[k]


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


def _set_session_cookie(resp, request: Request, token: str) -> None:
    resp.set_cookie(
        SESSION_COOKIE, token,
        httponly=True, samesite="lax",
        secure=request.url.scheme == "https",  # Secure breaks plain-http dev
        max_age=30 * 24 * 3600,
    )


def _safe_user(user: dict) -> dict:
    return {k: user.get(k) for k in ("id", "github_id", "github_login", "email")}


def _send_otp_task(state, email: str, code: str) -> None:
    """Background send — the 202 is already out, so this must never raise.

    A refused address means the code can never arrive, so the pending row is
    dropped and the user can fix the typo and ask again immediately instead of
    waiting out the resend cooldown. Our own failures (bad credentials,
    unreachable server) keep it, so a resend reuses the same pending signup.
    """
    from core.mailer import MailError, send_otp

    try:
        send_otp(state.mailer, state.settings, email, code)
        return
    except MailError as exc:
        detail, bad_address = str(exc), exc.bad_address
    except Exception as exc:  # a mailer bug must not kill the worker thread
        detail, bad_address = f"{type(exc).__name__}: {exc}", False

    print(f"  [warn] verification code for {email} not sent: {detail}")
    if bad_address:
        try:
            state.identity.clear_email_otp(email)
        except Exception as exc:
            print(f"  [warn] could not clear the pending signup: {exc}")


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
        _set_session_cookie(resp, request, session)
        return resp

    # ------------------------------------------------- email/password path
    @app.post("/api/v1/auth/signup", status_code=202)
    def signup(request: Request, body: dict, tasks: BackgroundTasks):
        """Step 1: email a verification code. Creates no account.

        The chosen password is hashed here and parked on the pending row, so
        the plaintext lives only for this request and step 2 needs nothing but
        the code. POSTing again replaces the pending code — this is also the
        resend endpoint, subject to OTP_RESEND_COOLDOWN_SECS.
        """
        identity = _identity(request)
        require_csrf(request)
        _rate_limit_ip(request)
        email = (body.get("email") or "").strip().lower()
        password = body.get("password") or ""
        if not _EMAIL_RE.match(email):
            raise HTTPException(422, "a valid email address is required")
        if len(password) < MIN_PASSWORD_LEN:
            raise HTTPException(
                422, f"password must be at least {MIN_PASSWORD_LEN} characters")
        # Deliberately explicit rather than the generic answer /login gives:
        # signup has to tell you the address is taken or the form is a dead
        # end. It does mean signup confirms whether an account exists — the
        # accepted cost of a usable form, and unchanged from the one-step flow.
        if identity.get_password_user(email) is not None:
            raise HTTPException(409, "an account with this email already exists")

        from core.identity import (OTP_RESEND_COOLDOWN_SECS, hash_password,
                                   new_otp_code)

        pending = identity.peek_email_otp(email)
        if pending is not None:
            age = (datetime.now(timezone.utc) - pending["sent_at"]).total_seconds()
            if age < OTP_RESEND_COOLDOWN_SECS:
                raise HTTPException(
                    429, f"a code was just sent; wait "
                         f"{int(OTP_RESEND_COOLDOWN_SECS - age)}s before asking "
                         f"for another")

        ttl = getattr(request.app.state.settings, "otp_ttl_mins", 10)
        code = new_otp_code()
        identity.start_email_otp(email, code, hash_password(password), ttl_mins=ttl)

        # SMTP is a network round trip on a threadpool worker — hand it to a
        # background task so a slow or hanging mail server cannot stall the
        # response. The caller is told the code is on its way either way; a
        # send that fails is logged, and the user simply asks for another.
        tasks.add_task(_send_otp_task, request.app.state, email, code)
        return {"ok": True, "email": email, "expires_in_mins": ttl,
                "next": "/api/v1/auth/signup/verify"}

    @app.post("/api/v1/auth/signup/verify", status_code=201)
    def signup_verify(request: Request, body: dict):
        """Step 2: exchange a valid code for the account and a session."""
        identity = _identity(request)
        require_csrf(request)
        email = (body.get("email") or "").strip().lower()
        code = (body.get("code") or "").strip()
        if not email or not code:
            raise HTTPException(422, "email and code are required")

        status, password_hash = identity.verify_email_otp(email, code)
        if status != "ok":
            identity.audit(None, "signup_verify_failed", target=status)
            raise HTTPException(*{
                "none": (404, "no pending signup for this address — request a "
                              "code first"),
                "expired": (410, "that code has expired — request a new one"),
                "locked": (429, "too many incorrect attempts; request a new code"),
                "invalid": (401, "incorrect code"),
            }[status])

        try:
            user = identity.create_password_user(email, password_hash or "")
        except Exception:  # someone verified the same address first
            raise HTTPException(409, "an account with this email already exists")
        session = identity.create_session(user["id"])
        identity.audit(user["id"], "email_verified", target=email)

        from fastapi.responses import JSONResponse

        resp = JSONResponse({"ok": True, "user": _safe_user(user)}, status_code=201)
        _set_session_cookie(resp, request, session)
        return resp

    @app.post("/api/v1/auth/login")
    def login(request: Request, body: dict):
        identity = _identity(request)
        require_csrf(request)
        email = (body.get("email") or "").strip().lower()
        password = body.get("password") or ""

        from core.identity import verify_password

        user = identity.get_password_user(email)
        if user is None or not verify_password(password, user.get("password_hash") or ""):
            # one message for both failures — never confirm an email exists
            identity.audit(user["id"] if user else None, "login_failed")
            raise HTTPException(401, "invalid email or password")
        session = identity.create_session(user["id"])  # audits "login"

        from fastapi.responses import JSONResponse

        resp = JSONResponse({"ok": True, "user": _safe_user(user)})
        _set_session_cookie(resp, request, session)
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
            "user": _safe_user(user),
            "has_github_token": identity.get_github_token(user["id"]) is not None,
            "llm": {"provider": llm["provider"], "model": llm["model"]} if llm else None,
            "repos": identity.user_repo_keys(user["id"]),
            "profiles": identity.user_profile_names(user["id"]),
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
