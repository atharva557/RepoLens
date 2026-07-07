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
from datetime import datetime, timedelta, timezone

SESSION_DAYS = 30  # sliding expiry (spec §8.1)


# --------------------------------------------------------------------------- #
# crypto helpers (spec §2.5)
# --------------------------------------------------------------------------- #
def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


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
        self.conn = psycopg.connect(database_url, autocommit=True)

    def ensure_schema(self) -> None:
        with self.conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)

    # ------------------------------------------------------------- users
    def upsert_github_user(self, github_id: int, login: str, email: str | None) -> dict:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO users (github_id, github_login, email)
                VALUES (%s, %s, %s)
                ON CONFLICT (github_id)
                DO UPDATE SET github_login = EXCLUDED.github_login,
                              email = COALESCE(EXCLUDED.email, users.email)
                RETURNING {_USER_COLS}
                """,
                (github_id, login, email),
            )
            return _user_row(cur.fetchone())

    def get_user(self, user_id: int) -> dict | None:
        with self.conn.cursor() as cur:
            cur.execute(f"SELECT {_USER_COLS} FROM users WHERE id = %s", (user_id,))
            return _user_row(cur.fetchone())

    # ------------------------------------------------- GitHub token (Fernet)
    def save_github_token(self, user_id: int, token: str, scopes: str = "") -> None:
        enc = encrypt_secret(self.fernet_key, token)
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET gh_token_enc = %s, gh_token_scopes = %s WHERE id = %s",
                (enc, scopes, user_id),
            )
        self.audit(user_id, "gh_token_saved", meta={"scopes": scopes})

    def get_github_token(self, user_id: int) -> str | None:
        with self.conn.cursor() as cur:
            cur.execute("SELECT gh_token_enc FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
        if not row or row[0] is None:
            return None
        return decrypt_secret(self.fernet_key, row[0])

    def revoke_github_token(self, user_id: int) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET gh_token_enc = NULL, gh_token_scopes = NULL "
                "WHERE id = %s", (user_id,),
            )
        self.audit(user_id, "gh_token_revoked")

    # ------------------------------------------------ sessions (SHA-256 hash)
    def create_session(self, user_id: int) -> str:
        token = new_session_token()
        expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sessions (token_hash, user_id, expires_at) "
                "VALUES (%s, %s, %s)",
                (hash_session(token), user_id, expires),
            )
        self.audit(user_id, "login")
        return token  # raw value goes to the cookie; only the hash is stored

    def user_for_session(self, token: str) -> dict | None:
        """Resolve a session cookie to a user; slides the 30-day expiry."""
        now = datetime.now(timezone.utc)
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT user_id, expires_at FROM sessions WHERE token_hash = %s",
                (hash_session(token),),
            )
            row = cur.fetchone()
            if row is None:
                return None
            user_id, expires_at = row
            if expires_at <= now:
                cur.execute("DELETE FROM sessions WHERE token_hash = %s",
                            (hash_session(token),))
                return None
            cur.execute(
                "UPDATE sessions SET last_seen_at = %s, expires_at = %s "
                "WHERE token_hash = %s",
                (now, now + timedelta(days=SESSION_DAYS), hash_session(token)),
            )
        return self.get_user(user_id)

    def delete_session(self, token: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE token_hash = %s",
                        (hash_session(token),))

    # ------------------------------------------------------------ user_repos
    def track_repo(self, user_id: int, repo_key: str, role: str = "tracker") -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO user_repos (user_id, repo_key, role) VALUES (%s, %s, %s) "
                "ON CONFLICT (user_id, repo_key) DO UPDATE SET role = EXCLUDED.role",
                (user_id, repo_key, role),
            )
        self.audit(user_id, "repo_track", target=repo_key)

    def untrack_repo(self, user_id: int, repo_key: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM user_repos WHERE user_id = %s AND repo_key = %s",
                        (user_id, repo_key))
        self.audit(user_id, "repo_untrack", target=repo_key)

    def user_repo_keys(self, user_id: int) -> list[str]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT repo_key FROM user_repos WHERE user_id = %s ORDER BY repo_key",
                (user_id,),
            )
            return [r[0] for r in cur.fetchall()]

    # ------------------------------------------------------- llm_configs
    def save_llm_config(self, user_id: int, provider: str, api_key: str,
                        model: str = "", base_url: str = "") -> None:
        enc = encrypt_secret(self.fernet_key, api_key)
        with self.conn.cursor() as cur:
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
        with self.conn.cursor() as cur:
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
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM llm_configs WHERE user_id = %s", (user_id,))
        self.audit(user_id, "llm_key_deleted")

    # ------------------------------------------------------------- audit
    def audit(self, user_id: int | None, action: str, target: str = "",
              meta: dict | None = None) -> None:
        with self.conn.cursor() as cur:
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
        self.repos: dict[tuple[int, str], str] = {}
        self.llm: dict[int, dict] = {}
        self.audit_log: list[dict] = []
        self._next_id = 1

    def ensure_schema(self) -> None:
        pass

    def upsert_github_user(self, github_id, login, email) -> dict:
        for u in self.users.values():
            if u["github_id"] == github_id:
                u["github_login"] = login
                u["email"] = email or u["email"]
                return dict(u)
        u = {"id": self._next_id, "github_id": github_id, "github_login": login,
             "email": email, "gh_token_scopes": None, "gh_token_enc": None,
             "created_at": datetime.now(timezone.utc)}
        self.users[self._next_id] = u
        self._next_id += 1
        return dict(u)

    def get_user(self, user_id) -> dict | None:
        u = self.users.get(user_id)
        return dict(u) if u else None

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
        self.repos[(user_id, repo_key)] = role
        self.audit(user_id, "repo_track", target=repo_key)

    def untrack_repo(self, user_id, repo_key) -> None:
        self.repos.pop((user_id, repo_key), None)
        self.audit(user_id, "repo_untrack", target=repo_key)

    def user_repo_keys(self, user_id) -> list[str]:
        return sorted(k for (uid, k) in self.repos if uid == user_id)

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


def open_identity(settings):
    """None when MULTIUSER=false; a schema-ensured PgIdentity when true.

    Unlike the Mongo->JSON fallback, Postgres is a *hard* requirement in
    multi-user mode (spec §2.6): identity data has no safe file fallback.
    """
    if not getattr(settings, "multiuser", False):
        return None
    if not settings.fernet_key:
        raise RuntimeError(
            "MULTIUSER=true requires FERNET_KEY (generate one: python -c "
            "\"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\")"
        )
    identity = PgIdentity(settings.database_url, settings.fernet_key)
    identity.ensure_schema()
    print("  [backend] identity: postgres (multiuser)")
    return identity
