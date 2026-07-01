"""GitHub-facing helpers.

For v0.1 the only thing we need from "GitHub" proper is the ability to turn a
remote repo reference into a local clone that core/git_client.py can read. A
local path is passed straight through. Optionally, repo metadata can be fetched
via PyGithub when a token is configured (used by later versions / the dashboard).

GitPython / PyGithub are imported lazily.
"""
from __future__ import annotations

import os
import re


def repo_key(target: str) -> str:
    """Stable cache key for a repo reference (URL or local path)."""
    t = target.rstrip("/").replace("\\", "/")
    m = re.search(r"github\.com[:/]+([^/]+)/([^/]+?)(?:\.git)?$", t)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    name = t.split("/")[-1]
    return name[:-4] if name.endswith(".git") else name


def _looks_like_url(target: str) -> bool:
    return bool(re.match(r"^(https?://|git@|ssh://|git://)", target))


def ensure_local_clone(target: str, cache_dir: str) -> tuple[str, str]:
    """Return (local_path, repo_key) for a repo reference.

    - An existing local git repo is used in place.
    - A remote URL is cloned (once) into `<cache_dir>/clones/<name>`.
    """
    key = repo_key(target)

    if os.path.isdir(target):
        if os.path.isdir(os.path.join(target, ".git")):
            return os.path.abspath(target), key
        raise ValueError(f"'{target}' is a directory but not a git repository")

    if not _looks_like_url(target):
        raise ValueError(
            f"'{target}' is neither an existing git repo nor a recognizable URL"
        )

    from git import Repo  # lazy import

    name = key.split("/")[-1]
    dest = os.path.join(cache_dir, "clones", name)
    if not os.path.isdir(os.path.join(dest, ".git")):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        print(f"  cloning {target} -> {dest} ...")
        Repo.clone_from(target, dest)
    return os.path.abspath(dest), key


class GitHubAPI:
    """Thin PyGithub wrapper for per-user activity (Tool 2 / Developer Profiler).

    PyGithub is imported lazily so the rest of GitPulse runs without it. All
    methods are best-effort and bounded by caller-supplied caps to respect the
    5,000 req/hour rate limit.
    """

    def __init__(self, token: str):
        from github import Github  # lazy import

        try:
            from github import Auth

            self.gh = Github(auth=Auth.Token(token), per_page=100)
        except Exception:  # older PyGithub
            self.gh = Github(token)

    def list_user_repos(self, username: str, max_repos: int):
        user = self.gh.get_user(username)
        out = []
        for r in user.get_repos(sort="pushed", direction="desc"):
            if getattr(r, "fork", False):
                continue
            out.append(r)
            if len(out) >= max_repos:
                break
        return out

    def iter_repo_commits(self, repo, username: str, max_commits: int) -> list[dict]:
        out: list[dict] = []
        try:
            commits = repo.get_commits(author=username)
        except Exception:
            return out
        for i, c in enumerate(commits):
            if i >= max_commits:
                break
            try:
                files = [
                    {"path": f.filename, "status": f.status,
                     "additions": f.additions, "deletions": f.deletions}
                    for f in c.files
                ]
                st = c.stats
                author = c.commit.author
                out.append({
                    "sha": c.sha,
                    "message": c.commit.message,
                    "author": author.name if author else username,
                    "date": author.date if author else None,
                    "additions": st.additions,
                    "deletions": st.deletions,
                    "files": files,
                    "repo": repo.full_name,
                })
            except Exception:
                continue
        return out

    def authored_prs(self, username: str, sample: int) -> tuple[int, list[str]]:
        try:
            res = self.gh.search_issues(f"type:pr author:{username}")
        except Exception:
            return 0, []
        samples: list[str] = []
        for i, issue in enumerate(res):
            if i >= sample:
                break
            if issue.body:
                samples.append(issue.body)
        return res.totalCount, samples

    def reviews_count(self, username: str) -> int:
        try:
            return self.gh.search_issues(f"type:pr reviewed-by:{username}").totalCount
        except Exception:
            return 0
