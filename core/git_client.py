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


# record / field separators for the single-pass `git log` read below. Commit
# messages can contain anything printable, so we delimit with control chars.
_RS, _FS = "\x1e", "\x1f"
_LOG_FORMAT = f"{_RS}%H{_FS}%an{_FS}%ae{_FS}%ct{_FS}%B{_FS}"


def parse_numstat_log(text: str) -> list[dict]:
    """Parse `git log --numstat --format=<_LOG_FORMAT>` output into commit dicts.

    One subprocess for the whole history. The previous implementation read
    `commit.stats` per commit, which spawns one `git diff` process *per
    commit* — on Windows that made a 400-commit pull take tens of seconds.
    Binary files report "-" in numstat and count as 0.
    """
    commits: list[dict] = []
    for record in text.split(_RS):
        if not record.strip():
            continue
        try:
            sha, author, email, ts, message, tail = record.split(_FS, 5)
        except ValueError:
            continue  # malformed record — never kill the whole pull for one
        files = []
        for line in tail.splitlines():
            parts = line.split("\t")
            if len(parts) != 3 or not parts[2]:
                continue
            ins, dele, path = parts
            files.append({
                "path": path,
                "insertions": int(ins) if ins.isdigit() else 0,
                "deletions": int(dele) if dele.isdigit() else 0,
            })
        commits.append({
            "sha": sha,
            "author": author,
            "email": email.lower(),
            "date": datetime.fromtimestamp(int(ts), tz=timezone.utc),
            "message": message,
            "files": files,
        })
    return commits


class GitClient:
    def __init__(self, repo_path: str):
        from git import Repo  # lazy import

        self.path = os.path.abspath(repo_path)
        self.repo = Repo(self.path)

    def iter_commits(self, *, max_count: int | None = None, include_merges: bool = False):
        """Yield commit dicts (newest first) with per-file insertion/deletion stats.

        Merge commits are skipped by default — their diffs are noisy and would
        over-count churn for the hotspot score. Implemented as ONE
        `git log --numstat` invocation (see parse_numstat_log); merges, when
        included, carry no file stats (numstat omits merge diffs).
        """
        args = ["--numstat", "--no-color", f"--format={_LOG_FORMAT}"]
        if not include_merges:
            args.append("--no-merges")
        if max_count:
            args.append(f"-n{max_count}")
        out = self.repo.git.log(*args)
        yield from parse_numstat_log(out)

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
