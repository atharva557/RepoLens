"""GitPython-backed access to a local repository.

Primary data source for v0.1: reading commit history straight from a local
clone is fast, needs no GitHub token, and is not rate-limited. The GitHub REST
API path (see core/github_client.py) is only used to obtain a local clone of a
remote URL.

GitPython is imported lazily so the pure analysis modules stay importable with
stdlib alone.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone


class GitClient:
    def __init__(self, repo_path: str):
        from git import Repo  # lazy import

        self.path = os.path.abspath(repo_path)
        self.repo = Repo(self.path)

    def iter_commits(self, *, max_count: int | None = None, include_merges: bool = False):
        """Yield commit dicts (newest first) with per-file insertion/deletion stats.

        Merge commits are skipped by default — their diffs are noisy and would
        over-count churn for the hotspot score.
        """
        for c in self.repo.iter_commits(max_count=max_count):
            if not include_merges and len(c.parents) > 1:
                continue
            files = [
                {
                    "path": path,
                    "insertions": int(st.get("insertions", 0)),
                    "deletions": int(st.get("deletions", 0)),
                }
                for path, st in c.stats.files.items()
            ]
            yield {
                "sha": c.hexsha,
                "author": c.author.name or "",
                "email": (c.author.email or "").lower(),
                "date": datetime.fromtimestamp(c.committed_date, tz=timezone.utc),
                "message": c.message if isinstance(c.message, str) else c.message.decode("utf-8", "ignore"),
                "files": files,
            }

    def head_files(self) -> list[str]:
        """All files tracked at HEAD."""
        out = self.repo.git.ls_files()
        return [line for line in out.splitlines() if line]

    def file_metrics(self, path: str) -> dict:
        """Compute size/complexity metrics for a file in the working tree.

        `loc` (non-empty line count) is the universal complexity proxy used by
        the scorer. For Python files we additionally capture radon cyclomatic
        complexity, surfaced in explanations when available.
        """
        full = os.path.join(self.path, path)
        try:
            with open(full, encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError:
            return {"loc": 0, "cyclomatic": None}

        loc = sum(1 for ln in text.splitlines() if ln.strip())
        cyclomatic = None
        if path.endswith(".py"):
            try:
                from radon.complexity import cc_visit

                blocks = cc_visit(text)
                cyclomatic = sum(b.complexity for b in blocks) if blocks else None
            except Exception:
                cyclomatic = None
        return {"loc": loc, "cyclomatic": cyclomatic}

    def metrics_for(self, paths) -> dict[str, dict]:
        return {p: self.file_metrics(p) for p in paths}

    def commit_diff(self, sha: str, max_chars: int = 4000) -> str:
        """Return the unified diff for a commit (truncated). Empty on failure."""
        try:
            out = self.repo.git.show(sha, "--no-color", "--format=", "--unified=2")
        except Exception:
            return ""
        return out[:max_chars]
