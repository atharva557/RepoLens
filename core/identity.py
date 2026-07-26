"""PostgreSQL identity plane (spec §6.4 / §8) — the v2 multi-user slice.

Only identity moves to Postgres: accounts, sessions, repo ownership, per-user
LLM configs, and the audit trail — relational, transactional, security-
sensitive. All analysis data stays in MongoDB, unchanged. The join key between
the planes is the repo key ("owner/repo").

Secret discipline (spec §2.5): a secret that is only *checked* is hashed
(session tokens -> SHA-256); a secret that must be *used* later is encrypted
(GitHub tokens, LLM API keys -> Fernet with FERNET_KEY from the environment).
Plaintext is decrypted only at call time and never logged.

Two implementations behind one interface (same pattern as MongoStore/JsonStore
and the LLM FakeProvider):

  - PgIdentity      : real Postgres via psycopg (lazy import).
  - MemoryIdentity  : in-process dict twin for tests — no DB, no network.

`open_identity(settings)` returns None when MULTIUSER=false. When it is true,
Postgres is a hard requirement (spec §2.6) — failures raise, never fall back.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

SESSION_DAYS = 30  # sliding expiry (spec §8.1)


# --------------------------------------------------------------------------- #
# crypto helpers (spec §2.5)
# --------------------------------------------------------------------------- #
def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


def hash_password(password: str) -> str:
    """Salted scrypt (stdlib, memory-hard) — format: scrypt$n$r$p$salt$hash.

    Parameters ride in the stored string so they can be raised later without
    invalidating existing accounts (old hashes verify with their own params).
    """
    n, r, p = 2 ** 14, 8, 1
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_hex, hash_hex = (stored or "").split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex),
                            n=int(n), r=int(r), p=int(p), dklen=32)
        return secrets.compare_digest(dk.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


def encrypt_secret(fernet_key: str, plaintext: str) -> bytes:
    from cryptography.fernet import Fernet  # lazy import

    return Fernet(fernet_key.encode()).encrypt(plaintext.encode())


def decrypt_secret(fernet_key: str, ciphertext: bytes) -> str:
    from cryptography.fernet import Fernet  # lazy import

    return Fernet(fernet_key.encode()).decrypt(bytes(ciphertext)).decode()


# --------------------------------------------------------------------------- #
# schema (spec §6.4, five tables; IF NOT EXISTS so bootstrap is idempotent)
# --------------------------------------------------------------------------- #
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
  id              SERIAL PRIMARY KEY,
  github_id       BIGINT UNIQUE,
  github_login    TEXT,
  email           TEXT UNIQUE,
  password_hash   TEXT,
  gh_token_enc    BYTEA,
  gh_token_scopes TEXT,
  created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sessions (
  token_hash   TEXT PRIMARY KEY,
  user_id      INT NOT NULL REFERENCES users ON DELETE CASCADE,
  created_at   TIMESTAMPTZ DEFAULT now(),
  last_seen_at TIMESTAMPTZ DEFAULT now(),
  expires_at   TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user_id_idx ON sessions (user_id);
CREATE INDEX IF NOT EXISTS sessions_expires_at_idx ON sessions (expires_at);

CREATE TABLE IF NOT EXISTS user_repos (
  user_id   INT  NOT NULL REFERENCES users ON DELETE CASCADE,
  repo_key  TEXT NOT NULL,
  role      TEXT NOT NULL DEFAULT 'tracker',
  added_at  TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (user_id, repo_key)
);
CREATE INDEX IF NOT EXISTS user_repos_repo_key_idx ON user_repos (repo_key);

CREATE TABLE IF NOT EXISTS user_profiles (
  user_id   INT  NOT NULL REFERENCES users ON DELETE CASCADE,
  username  TEXT NOT NULL,
  added_at  TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (user_id, username)
);

CREATE TABLE IF NOT EXISTS llm_configs (
  user_id     INT PRIMARY KEY REFERENCES users ON DELETE CASCADE,
  provider    TEXT NOT NULL,
  model       TEXT,
  api_key_enc BYTEA NOT NULL,
  base_url    TEXT,
  updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_log (
  id       BIGSERIAL PRIMARY KEY,
  user_id  INT REFERENCES users,
  action   TEXT NOT NULL,
  target   TEXT,
  meta     JSONB,
  at       TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS audit_log_user_at_idx ON audit_log (user_id, at DESC);
"""

_USER_COLS = "id, github_id, github_login, email, gh_token_scopes, created_at"
# same tuple qualified for joins (see PgIdentity.user_for_session)
_USER_COLS_U = ", ".join(f"u.{c}" for c in _USER_COLS.split(", "))


def _user_row(row) -> dict | None:
    if row is None:
        return None
    return {"id": row[0], "github_id": row[1], "github_login": row[2],
            "email": row[3], "gh_token_scopes": row[4], "created_at": row[5]}


class PgIdentity:
    """Postgres-backed identity store (primary; required when MULTIUSER=true)."""

    backend = "postgres"

    def __init__(self, database_url: str, fernet_key: str):
        import psycopg  # lazy import

        self.fernet_key = fernet_key
        self.database_url = database_url
        self._psycopg = psycopg
        self.conn = self._connect()

    def _connect(self):
        return self._psycopg.connect(self.database_url, autocommit=True)

    @contextmanager
    def _cursor(self):
        """A cursor on a *live* connection.

        One connection opened at startup served every request forever. When
        Postgres restarted — or an idle link was dropped by the OS/a proxy —
        every later call raised on the dead handle, so sign-in stayed broken
        until someone restarted the API process. Reconnect when the handle is
        known-dead, and discard one that dies mid-statement so the next call
        heals itself.

        The failed statement is deliberately NOT replayed: these run with
        autocommit, so an INSERT may well have committed before the link
        dropped, and a blind retry would duplicate it. The caller sees one
        error and the connection is healthy again for the retry.
        """
        if self.conn.closed:
            self.conn = self._connect()
        try:
            with self.conn.cursor() as cur:   # the one raw use — do not recurse
                yield cur
        except self._psycopg.OperationalError:
            try:
                self.conn.close()
            except Exception:
                pass
            raise

    def ensure_schema(self) -> None:
        with self._cursor() as cur:
            cur.execute(SCHEMA_SQL)

    # ------------------------------------------------------------- users
    def upsert_github_user(self, github_id: int, login: str, email: str | None) -> dict:
        """Resolve a GitHub identity to an account, linking by email.

        An account created with email+password has github_id NULL, so it never
        conflicts on github_id — the old plain INSERT ... ON CONFLICT
        (github_id) therefore tried a fresh INSERT and hit the UNIQUE on
        email, raising a violation the OAuth callback reported as a 502.
        Anyone who signed up with a password and later clicked "Sign in with
        GitHub" was locked out. MemoryIdentity enforces no constraints, which
        is exactly why every test passed.
        """
        linked = False
        with self._cursor() as cur:
            # 1. GitHub id already known -> refresh login/email and return
            cur.execute(
                f"""UPDATE users SET github_login = %s, email = COALESCE(%s, email)
                    WHERE github_id = %s RETURNING {_USER_COLS}""",
                (login, email, github_id),
            )
            row = cur.fetchone()
            # 2. same email, not linked to GitHub yet -> adopt it (same person)
            if row is None and email:
                cur.execute(
                    f"""UPDATE users SET github_id = %s, github_login = %s
                        WHERE lower(email) = lower(%s) AND github_id IS NULL
                        RETURNING {_USER_COLS}""",
                    (github_id, login, email),
                )
                row = cur.fetchone()
                linked = row is not None
            # 3. genuinely new account
            if row is None:
                cur.execute(
                    f"""INSERT INTO users (github_id, github_login, email)
                        VALUES (%s, %s, %s) RETURNING {_USER_COLS}""",
                    (github_id, login, email),
                )
                row = cur.fetchone()
        user = _user_row(row)
        if linked:
            self.audit(user["id"], "github_linked", target=login)
        return user

    def get_user(self, user_id: int) -> dict | None:
        with self._cursor() as cur:
            cur.execute(f"SELECT {_USER_COLS} FROM users WHERE id = %s", (user_id,))
            return _user_row(cur.fetchone())

    # -------------------------------------------------- email/password users
    def create_password_user(self, email: str, password_hash: str) -> dict:
        with self._cursor() as cur:
            cur.execute(
                f"INSERT INTO users (email, password_hash) VALUES (%s, %s) "
                f"RETURNING {_USER_COLS}",
                (email, password_hash),
            )
            user = _user_row(cur.fetchone())
        self.audit(user["id"], "signup")
        return user

    def get_password_user(self, email: str) -> dict | None:
        """User row INCLUDING password_hash — for the login check only;
        every other read path strips the hash (_USER_COLS)."""
        with self._cursor() as cur:
            cur.execute(
                f"SELECT {_USER_COLS}, password_hash FROM users "
                f"WHERE lower(email) = lower(%s) AND password_hash IS NOT NULL",
                (email,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        user = _user_row(row[:6])
        user["password_hash"] = row[6]
        return user

    # ------------------------------------------------- GitHub token (Fernet)
    def save_github_token(self, user_id: int, token: str, scopes: str = "") -> None:
        enc = encrypt_secret(self.fernet_key, token)
        with self._cursor() as cur:
            cur.execute(
                "UPDATE users SET gh_token_enc = %s, gh_token_scopes = %s WHERE id = %s",
                (enc, scopes, user_id),
            )
        self.audit(user_id, "gh_token_saved", meta={"scopes": scopes})

    def get_github_token(self, user_id: int) -> str | None:
        with self._cursor() as cur:
            cur.execute("SELECT gh_token_enc FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
        if not row or row[0] is None:
            return None
        return decrypt_secret(self.fernet_key, row[0])

    def revoke_github_token(self, user_id: int) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE users SET gh_token_enc = NULL, gh_token_scopes = NULL "
                "WHERE id = %s", (user_id,),
            )
        self.audit(user_id, "gh_token_revoked")

    # ------------------------------------------------ sessions (SHA-256 hash)
    def create_session(self, user_id: int) -> str:
        token = new_session_token()
        expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO sessions (token_hash, user_id, expires_at) "
                "VALUES (%s, %s, %s)",
                (hash_session(token), user_id, expires),
            )
        self.audit(user_id, "login")
        return token  # raw value goes to the cookie; only the hash is stored

    def user_for_session(self, token: str) -> dict | None:
        """Resolve a session cookie to a user; slides the 30-day expiry.

        One statement, because this runs on EVERY authenticated request: the
        previous SELECT -> UPDATE -> SELECT user was three round trips, and
        the expiry was checked in Python between two of them, so a session
        expiring in that gap could still be slid back to life.
        """
        now = datetime.now(timezone.utc)
        token_hash = hash_session(token)
        with self._cursor() as cur:
            cur.execute(
                f"""
                WITH slid AS (
                    UPDATE sessions SET last_seen_at = %s, expires_at = %s
                    WHERE token_hash = %s AND expires_at > %s
                    RETURNING user_id
                )
                SELECT {_USER_COLS_U} FROM users u JOIN slid ON u.id = slid.user_id
                """,
                (now, now + timedelta(days=SESSION_DAYS), token_hash, now),
            )
            row = cur.fetchone()
            if row is None:
                # unknown, or present but expired — clear the dead row out
                cur.execute(
                    "DELETE FROM sessions WHERE token_hash = %s AND expires_at <= %s",
                    (token_hash, now),
                )
                return None
        return _user_row(row)

    def delete_session(self, token: str) -> None:
        with self._cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE token_hash = %s",
                        (hash_session(token),))

    # ------------------------------------------------------------ user_repos
    def track_repo(self, user_id: int, repo_key: str, role: str = "tracker") -> None:
        # re-tracking refreshes added_at — the list is "most recently searched"
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO user_repos (user_id, repo_key, role) VALUES (%s, %s, %s) "
                "ON CONFLICT (user_id, repo_key) "
                "DO UPDATE SET role = EXCLUDED.role, added_at = now()",
                (user_id, repo_key, role),
            )
        self.audit(user_id, "repo_track", target=repo_key)

    def untrack_repo(self, user_id: int, repo_key: str) -> None:
        with self._cursor() as cur:
            cur.execute("DELETE FROM user_repos WHERE user_id = %s AND repo_key = %s",
                        (user_id, repo_key))
        self.audit(user_id, "repo_untrack", target=repo_key)

    def user_repo_keys(self, user_id: int) -> list[str]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT repo_key FROM user_repos WHERE user_id = %s "
                "ORDER BY added_at DESC, repo_key",
                (user_id,),
            )
            return [r[0] for r in cur.fetchall()]

    # --------------------------------------------------------- user_profiles
    def track_profile(self, user_id: int, username: str) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO user_profiles (user_id, username) VALUES (%s, %s) "
                "ON CONFLICT (user_id, username) DO UPDATE SET added_at = now()",
                (user_id, username),
            )
        self.audit(user_id, "profile_track", target=username)

    def user_profile_names(self, user_id: int) -> list[str]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT username FROM user_profiles WHERE user_id = %s "
                "ORDER BY added_at DESC, username",
                (user_id,),
            )
            return [r[0] for r in cur.fetchall()]

    # ------------------------------------------------------- llm_configs
    def save_llm_config(self, user_id: int, provider: str, api_key: str,
                        model: str = "", base_url: str = "") -> None:
        enc = encrypt_secret(self.fernet_key, api_key)
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO llm_configs (user_id, provider, model, api_key_enc, base_url)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id)
                DO UPDATE SET provider = EXCLUDED.provider, model = EXCLUDED.model,
                              api_key_enc = EXCLUDED.api_key_enc,
                              base_url = EXCLUDED.base_url, updated_at = now()
                """,
                (user_id, provider, model, enc, base_url),
            )
        self.audit(user_id, "llm_key_saved", meta={"provider": provider})

    def get_llm_config(self, user_id: int, *, with_key: bool = False) -> dict | None:
        with self._cursor() as cur:
            cur.execute(
                "SELECT provider, model, base_url, api_key_enc FROM llm_configs "
                "WHERE user_id = %s", (user_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        cfg = {"provider": row[0], "model": row[1] or "", "base_url": row[2] or ""}
        if with_key:  # decrypt only when the caller is about to use it
            cfg["api_key"] = decrypt_secret(self.fernet_key, row[3])
        return cfg

    def delete_llm_config(self, user_id: int) -> None:
        with self._cursor() as cur:
            cur.execute("DELETE FROM llm_configs WHERE user_id = %s", (user_id,))
        self.audit(user_id, "llm_key_deleted")

    # ------------------------------------------------------------- audit
    def audit(self, user_id: int | None, action: str, target: str = "",
              meta: dict | None = None) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO audit_log (user_id, action, target, meta) "
                "VALUES (%s, %s, %s, %s)",
                (user_id, action, target or None,
                 json.dumps(meta) if meta else None),
            )


class MemoryIdentity:
    """In-process identity store for tests — same interface, no DB, no network.

    Secrets still round-trip through the real Fernet/SHA-256 helpers so tests
    exercise the actual crypto discipline.
    """

    backend = "memory"

    def __init__(self, fernet_key: str):
        self.fernet_key = fernet_key
        self.users: dict[int, dict] = {}
        self.sessions: dict[str, dict] = {}   # token_hash -> row
        self.repos: dict[tuple[int, str], dict] = {}     # -> {role, seq}
        self.profiles: dict[tuple[int, str], int] = {}   # -> seq
        self.llm: dict[int, dict] = {}
        self.audit_log: list[dict] = []
        self._next_id = 1
        self._seq = 0  # monotonic recency (wall clocks can tie within a test)

    def ensure_schema(self) -> None:
        pass

    def upsert_github_user(self, github_id, login, email) -> dict:
        for u in self.users.values():
            if u["github_id"] == github_id:
                u["github_login"] = login
                u["email"] = email or u["email"]
                return self.get_user(u["id"])
        # mirror PgIdentity: adopt an existing password account with the same
        # email instead of creating a second one. Postgres enforces this with
        # a UNIQUE(email); this twin has no constraints, so without the same
        # branch here the suite would keep passing while OAuth 502'd for real.
        if email:
            for u in self.users.values():
                if u["github_id"] is None \
                        and (u.get("email") or "").lower() == email.lower():
                    u["github_id"] = github_id
                    u["github_login"] = login
                    self.audit(u["id"], "github_linked", target=login)
                    return self.get_user(u["id"])
        u = {"id": self._next_id, "github_id": github_id, "github_login": login,
             "email": email, "gh_token_scopes": None, "gh_token_enc": None,
             "created_at": datetime.now(timezone.utc)}
        self.users[self._next_id] = u
        self._next_id += 1
        return self.get_user(u["id"])

    def get_user(self, user_id) -> dict | None:
        u = self.users.get(user_id)
        if u is None:
            return None
        # same discipline as Pg's _USER_COLS: the hash never leaves login
        return {k: v for k, v in u.items() if k != "password_hash"}

    def create_password_user(self, email, password_hash) -> dict:
        u = {"id": self._next_id, "github_id": None, "github_login": None,
             "email": email, "gh_token_scopes": None, "gh_token_enc": None,
             "password_hash": password_hash,
             "created_at": datetime.now(timezone.utc)}
        self.users[self._next_id] = u
        self._next_id += 1
        self.audit(u["id"], "signup")
        return self.get_user(u["id"])

    def get_password_user(self, email) -> dict | None:
        for u in self.users.values():
            if (u.get("email") or "").lower() == (email or "").lower() \
                    and u.get("password_hash"):
                return dict(u)
        return None

    def save_github_token(self, user_id, token, scopes="") -> None:
        self.users[user_id]["gh_token_enc"] = encrypt_secret(self.fernet_key, token)
        self.users[user_id]["gh_token_scopes"] = scopes
        self.audit(user_id, "gh_token_saved", meta={"scopes": scopes})

    def get_github_token(self, user_id) -> str | None:
        enc = (self.users.get(user_id) or {}).get("gh_token_enc")
        return decrypt_secret(self.fernet_key, enc) if enc else None

    def revoke_github_token(self, user_id) -> None:
        self.users[user_id]["gh_token_enc"] = None
        self.users[user_id]["gh_token_scopes"] = None
        self.audit(user_id, "gh_token_revoked")

    def create_session(self, user_id) -> str:
        token = new_session_token()
        self.sessions[hash_session(token)] = {
            "user_id": user_id,
            "expires_at": datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS),
        }
        self.audit(user_id, "login")
        return token

    def user_for_session(self, token) -> dict | None:
        row = self.sessions.get(hash_session(token))
        if row is None:
            return None
        now = datetime.now(timezone.utc)
        if row["expires_at"] <= now:
            del self.sessions[hash_session(token)]
            return None
        row["expires_at"] = now + timedelta(days=SESSION_DAYS)
        return self.get_user(row["user_id"])

    def delete_session(self, token) -> None:
        self.sessions.pop(hash_session(token), None)

    def track_repo(self, user_id, repo_key, role="tracker") -> None:
        self._seq += 1
        self.repos[(user_id, repo_key)] = {"role": role, "seq": self._seq}
        self.audit(user_id, "repo_track", target=repo_key)

    def untrack_repo(self, user_id, repo_key) -> None:
        self.repos.pop((user_id, repo_key), None)
        self.audit(user_id, "repo_untrack", target=repo_key)

    def user_repo_keys(self, user_id) -> list[str]:
        rows = [(v["seq"], k) for (uid, k), v in self.repos.items()
                if uid == user_id]
        return [k for _, k in sorted(rows, reverse=True)]

    def track_profile(self, user_id, username) -> None:
        self._seq += 1
        self.profiles[(user_id, username)] = self._seq
        self.audit(user_id, "profile_track", target=username)

    def user_profile_names(self, user_id) -> list[str]:
        rows = [(seq, name) for (uid, name), seq in self.profiles.items()
                if uid == user_id]
        return [name for _, name in sorted(rows, reverse=True)]

    def save_llm_config(self, user_id, provider, api_key, model="", base_url="") -> None:
        self.llm[user_id] = {"provider": provider, "model": model,
                             "base_url": base_url,
                             "api_key_enc": encrypt_secret(self.fernet_key, api_key)}
        self.audit(user_id, "llm_key_saved", meta={"provider": provider})

    def get_llm_config(self, user_id, *, with_key=False) -> dict | None:
        row = self.llm.get(user_id)
        if row is None:
            return None
        cfg = {"provider": row["provider"], "model": row["model"],
               "base_url": row["base_url"]}
        if with_key:
            cfg["api_key"] = decrypt_secret(self.fernet_key, row["api_key_enc"])
        return cfg

    def delete_llm_config(self, user_id) -> None:
        self.llm.pop(user_id, None)
        self.audit(user_id, "llm_key_deleted")

    def audit(self, user_id, action, target="", meta=None) -> None:
        self.audit_log.append({"user_id": user_id, "action": action,
                               "target": target, "meta": meta,
                               "at": datetime.now(timezone.utc)})


# --------------------------------------------------------------------------- #
# per-user credentials -> per-request Settings (spec §2.5 / §8.2)
# --------------------------------------------------------------------------- #
# which Settings field each provider's key lives in (core/llm.py reads these)
_LLM_KEY_FIELD = {
    "openai": "openai_api_key",
    "claude": "anthropic_api_key",
    "gemini": "gemini_api_key",
}


def user_settings(settings, identity, user_id):
    """Overlay a user's OWN stored credentials onto the global settings.

    This is where the encrypted per-user secrets are finally *used*. Without
    it a multiuser deployment stored every user's OAuth token and BYO LLM key
    and then ran every analysis on the server's global credentials — so
    `PUT /config` was (correctly) refused with "manage keys per-user via
    /api/v1/me" while /api/v1/me led nowhere.

    Returns a *copy*: the app-wide Settings object is shared by every request
    and mutating it would leak one user's key into another user's job. Any
    field the user hasn't configured falls back to the global value, so a
    server-level GITHUB_TOKEN still works for accounts without their own.
    """
    from dataclasses import replace

    if identity is None or user_id is None:
        return settings

    overrides: dict = {}
    try:
        token = identity.get_github_token(user_id)
    except Exception as exc:  # unreadable ciphertext must not 500 the request
        token = None
        print(f"  [warn] could not read stored GitHub token: {type(exc).__name__}")
    if token:
        overrides["github_token"] = token

    try:
        cfg = identity.get_llm_config(user_id, with_key=True)
    except Exception as exc:
        cfg = None
        print(f"  [warn] could not read stored LLM config: {type(exc).__name__}")
    if cfg and cfg.get("api_key"):
        provider = (cfg.get("provider") or "").lower()
        key_field = _LLM_KEY_FIELD.get(provider)
        if key_field:
            overrides["llm_provider"] = provider
            overrides[key_field] = cfg["api_key"]
            # the global LLM_MODEL belongs to the global provider; carrying it
            # across would hand e.g. a local model id to Anthropic. Empty lets
            # core.llm pick that provider's default.
            overrides["llm_model"] = cfg.get("model") or ""
            if cfg.get("base_url"):
                overrides["local_llm_base_url"] = cfg["base_url"]

    return replace(settings, **overrides) if overrides else settings


def _mask_dsn(url: str) -> str:
    """postgresql://user:pass@host/db -> postgresql://***@host/db."""
    import re

    return re.sub(r"//[^/@]+@", "//***@", url or "")


def _pg_hint(database_url: str, exc: Exception) -> str:
    """Turn a psycopg connection failure into something actionable.

    A raw OperationalError here is a wall of libpq text, and it arrives at
    server startup where it reads as "the app is broken" rather than
    "Postgres needs one more setup step".
    """
    dsn = _mask_dsn(database_url)
    text = str(exc).lower()
    if isinstance(exc, ModuleNotFoundError):
        import sys as _sys

        return (f"MULTIUSER=true needs the Postgres driver, which is not "
                f"installed in {_sys.executable}. Install it with: "
                f"{_sys.executable} -m pip install \"psycopg[binary]\"")
    if "does not exist" in text:
        name = (database_url or "").rstrip("/").rsplit("/", 1)[-1] or "gitpulse"
        return (f"Postgres is reachable but the database in DATABASE_URL "
                f"({dsn}) does not exist. Create it once with: "
                f"createdb -U postgres {name}   (or in psql: CREATE DATABASE {name};)")
    if "password" in text or "authentication" in text or "role" in text:
        return (f"Postgres refused the credentials in DATABASE_URL ({dsn}). "
                f"Set the full connection string in .env, e.g. "
                f"DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/gitpulse")
    if "could not connect" in text or "refused" in text or "timeout" in text:
        return (f"Cannot reach Postgres at {dsn}. Check the server is running "
                f"and the host/port in DATABASE_URL are right "
                f"(Windows: services.msc -> postgresql-x64-NN).")
    return (f"Could not open the identity database at {dsn}: "
            f"{type(exc).__name__}: {exc}")


def open_identity(settings):
    """None when MULTIUSER=false; a schema-ensured identity store when true.

    `IDENTITY_BACKEND=memory` is an explicit DEV escape hatch: accounts and
    sessions live in process memory and vanish on restart — it exists so
    login/signup can be developed and demoed before Postgres is set up.
    Otherwise Postgres is a *hard* requirement (spec §2.6) — unlike the
    Mongo->JSON fallback, identity data has no safe file fallback, so
    failures raise, never silently degrade.
    """
    if not getattr(settings, "multiuser", False):
        return None
    if not settings.fernet_key:
        raise RuntimeError(
            "MULTIUSER=true requires FERNET_KEY (generate one: python -c "
            "\"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\")"
        )
    if getattr(settings, "identity_backend", "postgres").lower() == "memory":
        print("  [backend] identity: MEMORY (dev only — users, sessions and "
              "keys reset on every server restart)")
        return MemoryIdentity(settings.fernet_key)
    try:
        identity = PgIdentity(settings.database_url, settings.fernet_key)
        identity.ensure_schema()
    except Exception as exc:
        # still fatal (identity has no safe fallback) — just legible
        raise RuntimeError(_pg_hint(settings.database_url, exc)) from exc
    print(f"  [backend] identity: postgres (multiuser) "
          f"-> {_mask_dsn(settings.database_url)}")
    return identity
