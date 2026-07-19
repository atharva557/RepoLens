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
    progress=None,
) -> list[dict]:
    """Read commits from `local_path`, classify them, persist, and return them."""
    from core.progress import reporter_or_print

    report = reporter_or_print(progress)
    gc = GitClient(local_path)
    report("reading commit history (git)", detail=repo_key)
    commits: list[dict] = []
    for c in gc.iter_commits(max_count=max_commits):
        commits.append(c)
        if len(commits) % 200 == 0:  # no known total — tick, don't fake a pct
            report("reading commit history (git)", detail=f"{len(commits)} commits")
    classify_commits(commits, keywords)
    store.save_commits(repo_key, commits)
    # cache the window-independent activity aggregate alongside the history —
    # the dashboard's activity endpoint reads THIS, never the full commit list
    from core.activity import build_activity_base

    store.save_report("activity_base", repo_key, build_activity_base(commits))
    report("reading commit history (git)", pct=100,
           detail=f"{len(commits)} commits cached")
    return commits
