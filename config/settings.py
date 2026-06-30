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
            val = val.strip().strip('"').strip("'")
            # allow inline comments after the value
            if " #" in val:
                val = val.split(" #", 1)[0].strip()
            values[key] = val
    return values


@dataclass
class Settings:
    # GitHub
    github_token: str = ""
    github_webhook_secret: str = ""

    # LLM (unused until v0.2 — kept for forward compatibility)
    ollama_model: str = "qwen2.5-coder:7b"
    ollama_base_url: str = "http://localhost:11434"

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
            ollama_model=get("OLLAMA_MODEL", "qwen2.5-coder:7b"),
            ollama_base_url=get("OLLAMA_BASE_URL", "http://localhost:11434"),
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
            store_backend=get("GITPULSE_STORE", "auto").lower(),
        )

    def summary(self) -> str:
        masked = {f.name: getattr(self, f.name) for f in fields(self)}
        masked["github_token"] = "***" if self.github_token else "(unset)"
        masked["github_webhook_secret"] = "***" if self.github_webhook_secret else "(unset)"
        return "\n".join(f"  {k} = {v}" for k, v in masked.items())
