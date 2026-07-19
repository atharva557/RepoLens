# 12 — Multi-user identity plane (PostgreSQL)

The first slice of the spec's v2 multi-user design (`GitPulse_SPEC.md` §6.4,
§7.4, §8): accounts, sessions, encrypted tokens, repo tracking, and an audit
trail — in **PostgreSQL**, while all analysis data stays in MongoDB unchanged.

## Two modes, one codebase (spec §2.6)

| | `MULTIUSER=false` (default) | `MULTIUSER=true` |
|---|---|---|
| Behavior | exactly the single-user app — `.env` token, no login | `/auth` enabled; analysis triggers require a session |
| Postgres | not touched, not required | **hard requirement** — startup fails without it (no file fallback for identity data) |
| CORS | `GITPULSE_CORS_ORIGINS` (default `*`) | pinned to `DASHBOARD_ORIGIN`, credentials allowed |

Unlike Mongo→JSON, there is deliberately **no fallback** for the identity
plane: falling back would silently drop authentication.

## Why Postgres here and Mongo everywhere else (spec §2.3)

Identity data is relational (FKs, cascading deletes, uniqueness),
transactional (session create/delete), and security-sensitive (encrypted
secrets, audit trail). Analysis output is document-shaped. Each store does
what it's best at; the join key between the planes is the repo key
(`owner/repo`).

## The five tables (`core/identity.py::SCHEMA_SQL`, spec §6.4)

| Table | Holds |
|---|---|
| `users` | GitHub identity (`github_id` unique), optional `password_hash` (unused — OAuth-only for now), Fernet-encrypted GitHub token + scopes |
| `sessions` | **SHA-256 hash** of the cookie value (never the raw token), sliding 30-day expiry, `last_seen_at` |
| `user_repos` | who tracks which repo (`role`: tracker/owner) — joins Mongo's reports by repo key |
| `llm_configs` | per-user BYO LLM key (Fernet-encrypted), provider/model/base_url |
| `audit_log` | login/logout, token save/revoke, repo track/untrack, LLM key save/delete |

Schema bootstrap is idempotent (`CREATE TABLE IF NOT EXISTS`), run
automatically by `open_identity()` at startup.

## Secret discipline (spec §2.5) — *hash what you check, encrypt what you use*

- **Session tokens** are only ever *checked* → stored as SHA-256 hashes.
  The raw value exists only in the user's httpOnly cookie.
- **GitHub tokens / LLM API keys** must be *used* later → **Fernet-encrypted**
  (`cryptography`) with `FERNET_KEY` from the environment. Decrypted only at
  call time (`get_github_token`, `get_llm_config(with_key=True)`), never
  logged, and every save/revoke is audited.
- `FERNET_KEY` is generated once and never committed:
  `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

## Auth flow (`api/auth.py`, spec §7.4/§8.1)

Two sign-in paths share one session plane (cookie, `/me`, logout, CSRF):

**Email + password** — the dashboard's Login wall (`frontend/src/pages/Login.jsx`):

```
POST /api/v1/auth/signup   {email, password}  validate (email shape, ≥8 chars)
                           → salted-scrypt hash (core.identity.hash_password)
                           → users row (github_id NULL) → session + cookie (201)
POST /api/v1/auth/login    {email, password}  verify_password (constant-time)
                           → session + cookie. Wrong email and wrong password
                           are ONE generic 401 — never confirm an email exists
```

Hash format `scrypt$n$r$p$salt$hash` — parameters ride in the string so they
can be raised later without invalidating existing accounts. The hash is
selected only by `get_password_user` (the login check); every other user read
strips it.

**GitHub OAuth** — login and token-acquisition in one step; nobody pastes a token:

```
GET /api/v1/auth/github/login      302 → github.com/oauth/authorize
                                   (client id, scope read:user, state nonce)
GET /api/v1/auth/github/callback   verify state → exchange code for token
                                   → upsert users row (github_id is identity)
                                   → encrypt+store token → create session
                                   → Set-Cookie (httpOnly, SameSite=Lax)
                                   → 302 to DASHBOARD_ORIGIN
POST /api/v1/auth/logout           delete session row, clear cookie
GET  /api/v1/me                    {user, has_github_token, llm, repos}
PUT/DELETE /api/v1/me/llm          save / remove BYO LLM key (write-only)
DELETE /api/v1/me/github-token     revoke the stored token
```

- **CSRF**: SameSite=Lax cookies plus a required `X-GitPulse-Client: dashboard`
  header on every mutating route — cross-site forms can't set custom headers.
- The OAuth code exchange is two HTTPS calls, implemented with stdlib urllib
  (the spec sketched authlib; the flow is small enough that the endpoints and
  semantics are identical without the extra dependency).
- Routes always exist and answer **503** while `MULTIUSER=false` — the same
  pattern as the webhook without its secret.

## Enforcement in this slice

With multiuser on, every **analysis trigger** (`POST /analyze`,
`/commit-quality`, `/profiles/{u}`, pr-reviews, insights) requires a session,
and the job records `created_by`. Each trigger also **tracks what the user
searched**: repos into `user_repos` (canonical key via `repo_key()`), profile
usernames into the `user_profiles` table — re-searching refreshes `added_at`,
so both lists are most-recently-searched-first (`user_repo_keys` /
`user_profile_names`, also returned by `/me`).

**Discovery is scoped per user**: `GET /repos` and `GET /profiles` show a
signed-in user only what they themselves analyzed/searched (a new account
sees empty lists — Home renders its empty states), and anonymous requesters
get empty lists. Single-user mode stays global.

Deep reads (`/repos/{key}/...`, `/profiles/{u}`) and the HMAC-verified
webhook are unchanged — a user who knows a key can still open it directly.
**Deferred to the next slice** (per spec §7.12/§8.3): hard per-repo access
rules on those reads (`require_repo_access`), private-repo ownership, quotas,
the per-request LLM resolution that consumes `llm_configs`, and OAuth scope
escalation for comment posting.

## Testing (`tests/test_identity.py`)

`MemoryIdentity` is an in-process twin of `PgIdentity` (same interface, real
Fernet/SHA-256 helpers), so the whole slice tests network- and DB-free:
crypto discipline, upsert idempotency, session expiry, encrypted LLM configs,
the 503 gate, the full OAuth→cookie→`/me`→CSRF→logout flow (exchange stubbed),
and trigger enforcement. Suite 9 of 9; skips cleanly without `cryptography`
or `fastapi`.

## The dashboard side

`frontend/src/lib/auth.jsx` probes `GET /api/v1/me` once on load and exposes
three states: **503 → single-user** (no wall, exactly the old app), **401 →
anonymous** (App renders the Login wall on every URL; after sign-in the user
lands on the URL they originally asked for), **200 → signed in** (navbar shows
the account chip + sign-out). `postJSON`/`putJSON` always send the
`X-GitPulse-Client` CSRF header — harmless in single-user mode, required in
multiuser.

## Turning it on

```bash
# Quick DEV mode (no Postgres): accounts/sessions live in process memory and
# RESET on every server restart — for developing/demoing login only.
MULTIUSER=true
IDENTITY_BACKEND=memory
FERNET_KEY=<generated once — see above>

# Real mode (Postgres):
# 1. create the database (once)                # psql/pgAdmin, as your PG user
CREATE DATABASE gitpulse;

# 2. .env
MULTIUSER=true
IDENTITY_BACKEND=postgres        # (or just omit — postgres is the default)
DATABASE_URL=postgresql://<user>:<password>@localhost:5432/gitpulse
FERNET_KEY=<generated once — see above>
SESSION_SECRET=<any long random string>
# optional, only for "Sign in with GitHub":
GITHUB_OAUTH_CLIENT_ID=<from github.com/settings/developers>
GITHUB_OAUTH_CLIENT_SECRET=...
# OAuth App callback URL: http://127.0.0.1:8000/api/v1/auth/github/callback

# 3. run — tables are created automatically
python -m uvicorn api.main:app
```
