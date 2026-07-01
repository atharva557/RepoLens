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


@dataclass
class Settings:
    # GitHub
    github_token: str = ""
    github_webhook_secret: str = ""

    # LLM provider layer (v0.2). Provider: local (LM Studio) | openai | claude | gemini
    llm_provider: str = "local"
    llm_model: str = ""  # empty -> per-provider default in core/llm.py
    local_llm_base_url: str = "http://localhost:1234/v1"  # LM Studio default
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

    # Storage backend override: "auto" (try Mongo, fall back to json), "mongo", "json"
    store_backend: str = "auto"

    @classmethod
    def load(cls, env_path: str = ".env") -> "Settings":
        env = {**_parse_env_file(env_path), **os.environ}

        def get(name: str, default):
            return env.get(name, default)

        return cls(
            github_token=get("GITHUB_TOKEN", ""),
            github_webhook_secret=get("GITHUB_WEBHOOK_SECRET", ""),
            llm_provider=get("LLM_PROVIDER", "local").lower(),
            llm_model=get("LLM_MODEL", ""),
            local_llm_base_url=get("LOCAL_LLM_BASE_URL", "http://localhost:1234/v1"),
            anthropic_api_key=get("ANTHROPIC_API_KEY", ""),
            openai_api_key=get("OPENAI_API_KEY", ""),
            gemini_api_key=get("GEMINI_API_KEY", ""),
            llm_max_tokens=int(get("LLM_MAX_TOKENS", 512)),
            llm_temperature=float(get("LLM_TEMPERATURE", 0.2)),
            mongodb_uri=get("MONGODB_URI", "mongodb://localhost:27017"),
            mongodb_db=get("MONGODB_DB", "gitpulse"),
            chroma_path=get("CHROMA_PATH", "data/chroma"),
            cache_dir=get("GITPULSE_CACHE_DIR", "data/cache"),
            bug_keywords=[
                k.strip().lower()
                for k in get("BUG_KEYWORDS", "fix,bug,resolve,patch,hotfix,closes").split(",")
                if k.strip()
            ],
            hotspot_lookback_days=int(get("HOTSPOT_LOOKBACK_DAYS", 90)),
            churn_window_days=int(get("CHURN_WINDOW_DAYS", 30)),
            hotspot_recency_halflife_days=int(get("HOTSPOT_RECENCY_HALFLIFE_DAYS", 30)),
            ml_model_path=get("ML_MODEL_PATH", "data/models/hotspot_xgb.json"),
            ml_label_window_days=int(get("ML_LABEL_WINDOW_DAYS", 90)),
            ml_snapshots=int(get("ML_SNAPSHOTS", 4)),
            ml_min_positives=int(get("ML_MIN_POSITIVES", 20)),
            profile_max_repos=int(get("PROFILE_MAX_REPOS", 15)),
            profile_max_commits_per_repo=int(get("PROFILE_MAX_COMMITS_PER_REPO", 100)),
            profile_pr_sample=int(get("PROFILE_PR_SAMPLE", 8)),
            store_backend=get("GITPULSE_STORE", "auto").lower(),
        )

    def summary(self) -> str:
        masked = {f.name: getattr(self, f.name) for f in fields(self)}
        for secret in ("github_token", "github_webhook_secret",
                       "anthropic_api_key", "openai_api_key", "gemini_api_key"):
            masked[secret] = "***" if getattr(self, secret) else "(unset)"
        return "\n".join(f"  {k} = {v}" for k, v in masked.items())
