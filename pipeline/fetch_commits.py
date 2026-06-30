"""Pull commit history from a local clone and persist it to the store.

Thin wrapper that wires GitClient -> classify_commits -> store. Kept separate
from the scoring step so the cache can be reused across all four tools later.
"""
from __future__ import annotations

from core.git_client import GitClient
from pipeline.classify_commits import classify_commits


def fetch_and_store_commits(
    local_path: str,
    repo_key: str,
    store,
    *,
    keywords=None,
    max_commits: int | None = None,
) -> list[dict]:
    """Read commits from `local_path`, classify them, persist, and return them."""
    gc = GitClient(local_path)
    commits = list(gc.iter_commits(max_count=max_commits))
    classify_commits(commits, keywords)
    store.save_commits(repo_key, commits)
    return commits
