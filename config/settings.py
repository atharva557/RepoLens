"""Central configuration, loaded from environment / .env.

Mirrors the revised `.env` reference in GitPulse_Revised_Sections.md §14
(MongoDB instead of SQLite, plus the recency half-life knob for the
weighted hotspot scorer).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields


def _parse_env_file(path: str) -> dict[str, str]:
    """Tiny stdlib .env parser so settings load without python-dotenv."""
    values: dict[str, str] = {}
    if not path or not os.path.isfile(path):
        return values
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            # strip inline / whole-value comments, but only when the value isn't quoted
            if val[:1] not in ("'", '"'):
                if val.startswith("#"):
                    val = ""
                elif " #" in val:
                    val = val.split(" #", 1)[0].strip()
            # strip a matching pair of surrounding quotes
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                val = val[1:-1]
            values[key] = val
    return values


# Settings fields the runtime API (PUT /config) may change, with their .env
# names. Deliberately narrow: keys + LLM choice only — analysis tuning stays a
# file-edit so a stray dashboard call can't silently reshape scoring.
RUNTIME_ENV_KEYS: dict[str, str] = {
    "github_token": "GITHUB_TOKEN",
    "llm_provider": "LLM_PROVIDER",
    "llm_model": "LLM_MODEL",
    "local_llm_base_url": "LOCAL_LLM_BASE_URL",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "openai_api_key": "OPENAI_API_KEY",
    "gemini_api_key": "GEMINI_API_KEY",
}


def persist_env(changes: dict[str, str], env_path: str = ".env",
                example_path: str = ".env.example") -> str:
    """Write `{ENV_NAME: value}` updates into `env_path`, preserving every
    other line. A missing .env is seeded from .env.example first (the same
    copy the README asks for), so comments and documented defaults survive
    the first dashboard save. Returns the path written.
    """
    import shutil

    if not os.path.isfile(env_path) and os.path.isfile(example_path):
        shutil.copyfile(example_path, env_path)
    lines: list[str] = []
    if os.path.isfile(env_path):
        with open(env_path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    remaining = dict(changes)
    out = []
    for line in lines:
        stripped = line.strip()
        name = stripped.partition("=")[0].strip() if "=" in stripped else None
        if name in remaining and not stripped.startswith("#"):
            out.append(f"{name}={remaining.pop(name)}")
        else:
            out.append(line)
    out.extend(f"{name}={value}" for name, value in remaining.items())
    with open(env_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    return env_path


@dataclass
class Settings:
    # GitHub
    github_token: str = ""
    github_webhook_secret: str = ""

    # LLM provider layer (v0.2). Provider: local (LM Studio) | openai | claude | gemini
    llm_provider: str = "local"
    llm_model: str = ""  # empty -> per-provider default in core/llm.py
    local_llm_base_url: str = "http://localhost:1234/v1"  # LM Studio default
    local_llm_autoload: bool = False  # auto-load a model in LM Studio when none is loaded
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    llm_max_tokens: int = 512
    llm_temperature: float = 0.2

    # Storage
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "gitpulse"
    chroma_path: str = "data/chroma"
    cache_dir: str = "data/cache"

    # Analysis tuning
    bug_keywords: list[str] = field(
        default_factory=lambda: ["fix", "bug", "resolve", "patch", "hotfix", "closes"]
    )
    hotspot_lookback_days: int = 90
    churn_window_days: int = 30
    hotspot_recency_halflife_days: int = 30

    # XGBoost "second opinion" (optional ML model)
    ml_model_path: str = "data/models/hotspot_xgb.json"
    ml_label_window_days: int = 90
    ml_snapshots: int = 4
    ml_min_positives: int = 20

    # Developer Skill Profiler (Tool 2) — GitHub API caps
    profile_max_repos: int = 15
    profile_max_commits_per_repo: int = 100
    profile_pr_sample: int = 8
    profile_cache_hours: int = 24  # reuse a cached profile younger than this

    # PR Review Assistant (Tool 3) — similarity + risk
    embedding_model: str = "all-MiniLM-L6-v2"
    similarity_backend: str = "auto"       # auto | chroma | lite
    pr_similarity_top_k: int = 5
    pr_similarity_warn: float = 0.6
    hotspot_top_n: int = 10                 # a file in the top-N hotspots is "high risk"
    pr_risk_high: float = 0.5               # weighted PR risk score >= this -> HIGH
    pr_risk_medium: float = 0.2             # >= this -> MEDIUM (below -> LOW)
    pulls_cache_hours: float = 1            # recent-PRs list TTL (PRs churn fast)

    # FastAPI layer (v0.4) — PR webhook behaviour + dashboard CORS
    webhook_post_comment: bool = False  # post Tool 3 reports back to the PR automatically
    cors_origins: list[str] = field(default_factory=lambda: ["*"])  # dashboard origins

    # Storage backend override: "auto" (try Mongo, fall back to json), "mongo", "json"
    store_backend: str = "auto"

    # Multi-user identity plane (v2, spec §6.4/§8/§9.2). MULTIUSER=false keeps
    # exactly the single-user behavior; true requires Postgres + enables /auth.
    multiuser: bool = False
    identity_backend: str = "postgres"  # postgres | memory (DEV: resets on restart)
    database_url: str = "postgresql://localhost:5432/gitpulse"
    fernet_key: str = ""       # token/key encryption — generate once, NEVER commit
    session_secret: str = ""   # session/CSRF signing
    github_oauth_client_id: str = ""
    github_oauth_client_secret: str = ""
    dashboard_origin: str = "http://localhost:5173"  # CORS allow-origin when multiuser

    @classmethod
    def load(cls, env_path: str = ".env") -> "Settings":
        env = {**_parse_env_file(env_path), **os.environ}

        def get(name: str, default):
            return env.get(name, default)

        def get_num(name: str, default, cast):
            # blank or malformed numeric values fall back to the default
            # instead of crashing every entry point at load time
            raw = str(env.get(name, "")).strip()
            if not raw:
                return default
            try:
                return cast(raw)
            except ValueError:
                print(f"  [warn] invalid {name}={raw!r} in environment; using {default}")
                return default

        return cls(
            github_token=get("GITHUB_TOKEN", ""),
            github_webhook_secret=get("GITHUB_WEBHOOK_SECRET", ""),
            llm_provider=get("LLM_PROVIDER", "local").lower(),
            llm_model=get("LLM_MODEL", ""),
            local_llm_base_url=get("LOCAL_LLM_BASE_URL", "http://localhost:1234/v1"),
            local_llm_autoload=str(get("LOCAL_LLM_AUTOLOAD", "")).strip().lower()
            in ("1", "true", "yes", "on"),
            anthropic_api_key=get("ANTHROPIC_API_KEY", ""),
            openai_api_key=get("OPENAI_API_KEY", ""),
            gemini_api_key=get("GEMINI_API_KEY", ""),
            llm_max_tokens=get_num("LLM_MAX_TOKENS", 512, int),
            llm_temperature=get_num("LLM_TEMPERATURE", 0.2, float),
            mongodb_uri=get("MONGODB_URI", "mongodb://localhost:27017"),
            mongodb_db=get("MONGODB_DB", "gitpulse"),
            chroma_path=get("CHROMA_PATH", "data/chroma"),
            cache_dir=get("GITPULSE_CACHE_DIR", "data/cache"),
            bug_keywords=[
                k.strip().lower()
                for k in get("BUG_KEYWORDS", "fix,bug,resolve,patch,hotfix,closes").split(",")
                if k.strip()
            ],
            hotspot_lookback_days=get_num("HOTSPOT_LOOKBACK_DAYS", 90, int),
            churn_window_days=get_num("CHURN_WINDOW_DAYS", 30, int),
            hotspot_recency_halflife_days=get_num("HOTSPOT_RECENCY_HALFLIFE_DAYS", 30, int),
            ml_model_path=get("ML_MODEL_PATH", "data/models/hotspot_xgb.json"),
            ml_label_window_days=get_num("ML_LABEL_WINDOW_DAYS", 90, int),
            ml_snapshots=get_num("ML_SNAPSHOTS", 4, int),
            ml_min_positives=get_num("ML_MIN_POSITIVES", 20, int),
            profile_max_repos=get_num("PROFILE_MAX_REPOS", 15, int),
            profile_max_commits_per_repo=get_num("PROFILE_MAX_COMMITS_PER_REPO", 100, int),
            profile_pr_sample=get_num("PROFILE_PR_SAMPLE", 8, int),
            profile_cache_hours=get_num("PROFILE_CACHE_HOURS", 24, int),
            embedding_model=get("EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
            similarity_backend=get("SIMILARITY_BACKEND", "auto").lower(),
            pr_similarity_top_k=get_num("PR_SIMILARITY_TOP_K", 5, int),
            pr_similarity_warn=get_num("PR_SIMILARITY_WARN", 0.6, float),
            hotspot_top_n=get_num("HOTSPOT_TOP_N", 10, int),
            pr_risk_high=get_num("PR_RISK_HIGH", 0.5, float),
            pr_risk_medium=get_num("PR_RISK_MEDIUM", 0.2, float),
            pulls_cache_hours=get_num("PULLS_CACHE_HOURS", 1, float),
            webhook_post_comment=str(get("GITPULSE_WEBHOOK_POST", "")).strip().lower()
            in ("1", "true", "yes", "on"),
            cors_origins=[o.strip() for o in get("GITPULSE_CORS_ORIGINS", "*").split(",")
                          if o.strip()] or ["*"],
            store_backend=get("GITPULSE_STORE", "auto").lower(),
            multiuser=str(get("MULTIUSER", "")).strip().lower()
            in ("1", "true", "yes", "on"),
            identity_backend=get("IDENTITY_BACKEND", "postgres").strip().lower(),
            database_url=get("DATABASE_URL", "postgresql://localhost:5432/gitpulse"),
            fernet_key=get("FERNET_KEY", ""),
            session_secret=get("SESSION_SECRET", ""),
            github_oauth_client_id=get("GITHUB_OAUTH_CLIENT_ID", ""),
            github_oauth_client_secret=get("GITHUB_OAUTH_CLIENT_SECRET", ""),
            dashboard_origin=get("DASHBOARD_ORIGIN", "http://localhost:5173"),
        )

    def summary(self) -> str:
        masked = {f.name: getattr(self, f.name) for f in fields(self)}
        for secret in ("github_token", "github_webhook_secret",
                       "anthropic_api_key", "openai_api_key", "gemini_api_key",
                       "fernet_key", "session_secret", "github_oauth_client_secret"):
            masked[secret] = "***" if getattr(self, secret) else "(unset)"
        return "\n".join(f"  {k} = {v}" for k, v in masked.items())
