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
