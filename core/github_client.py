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
from datetime import datetime, timezone


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


class _GitProgress:
    """GitPython progress adapter -> our report(phase, pct, detail).

    Git fires updates constantly and runs several 0-100% stages per clone
    (counting, receiving, resolving...). Report only decile crossings, name
    the stage in `detail`, and reset the throttle per stage so the restart
    from 0% is legible instead of confusing."""

    def __init__(self, report, phase: str):
        self.report, self.phase = report, phase
        self._stage, self._last = None, -1

    @staticmethod
    def _stage_name(op_code) -> str:
        from git import RemoteProgress as RP  # lazy import

        names = {RP.COUNTING: "counting objects", RP.COMPRESSING: "compressing",
                 RP.WRITING: "writing", RP.RECEIVING: "receiving objects",
                 RP.RESOLVING: "resolving deltas",
                 RP.FINDING_SOURCES: "finding sources",
                 RP.CHECKING_OUT: "checking out files"}
        return names.get(op_code & RP.OP_MASK, "")

    def __call__(self, op_code, cur_count, max_count=None, message=""):
        if not max_count:
            return
        stage = self._stage_name(op_code)
        if stage != self._stage:
            self._stage, self._last = stage, -1
        pct = int(cur_count * 100 / max_count)
        if pct // 10 != self._last:
            self._last = pct // 10
            self.report(self.phase, pct=pct, detail=stage)


def ensure_local_clone(target: str, cache_dir: str, *, update: bool = False,
                       progress=None) -> tuple[str, str]:
    """Return (local_path, repo_key) for a repo reference.

    - An existing local git repo is used in place (never touched).
    - A remote URL is cloned (once) into `<cache_dir>/clones/<name>`.
    - `update=True` (an explicit refresh) additionally pulls the cached clone
      so new upstream commits actually arrive; a failed pull (offline, forced
      push upstream) warns and proceeds with the existing history.
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

    from core.progress import reporter_or_print

    report = reporter_or_print(progress)
    name = key.split("/")[-1]
    dest = os.path.join(cache_dir, "clones", name)
    if not os.path.isdir(os.path.join(dest, ".git")):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        report("cloning repository (GitHub)", pct=0, detail=target)
        Repo.clone_from(target, dest,
                        progress=_GitProgress(report, "cloning repository (GitHub)"))
        report("cloning repository (GitHub)", pct=100, detail=key)
    elif update:
        try:
            report("updating clone (GitHub)", detail=key)
            Repo(dest).remotes.origin.pull(
                ff_only=True, progress=_GitProgress(report, "updating clone (GitHub)"))
        except Exception as exc:
            print(f"  [warn] clone update failed ({type(exc).__name__}); "
                  f"using existing history")
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

    def user_meta(self, username: str) -> dict:
        """Social-header metadata for the profile page (avatar, bio, counts)."""
        u = self.gh.get_user(username)
        created = getattr(u, "created_at", None)
        years = None
        if created is not None:
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            years = round((datetime.now(timezone.utc) - created).days / 365.25, 1)
        return {
            "name": u.name or username,
            "avatar_url": u.avatar_url or "",
            "bio": u.bio or "",
            "followers": u.followers,
            "following": u.following,
            "public_repos": u.public_repos,
            "created_at": created.isoformat() if created else None,
            "years_active": years,
            "url": u.html_url,
            "location": u.location or "",
            "company": u.company or "",
        }

    def merged_prs_count(self, username: str) -> int:
        try:
            return self.gh.search_issues(
                f"type:pr author:{username} is:merged").totalCount
        except Exception:
            return 0

    def issues_resolved_count(self, username: str) -> int:
        """Closed issues the user was assigned to — our 'resolved' definition."""
        try:
            return self.gh.search_issues(
                f"type:issue assignee:{username} is:closed").totalCount
        except Exception:
            return 0

    def repo_meta(self, full_name: str) -> dict:
        """Dashboard-header metadata for an 'owner/repo' (one extra call for
        the language byte counts, converted to percentages)."""
        r = self.gh.get_repo(full_name)
        try:
            # some PyGithub versions include non-count entries (e.g. 'url')
            langs = {k: v for k, v in r.get_languages().items()
                     if isinstance(v, int)}
        except Exception:
            langs = {}
        total = sum(langs.values()) or 1
        return {
            "full_name": r.full_name,
            "description": r.description or "",
            "language": r.language,
            "languages": [{"name": k, "pct": round(v * 100 / total, 1)}
                          for k, v in sorted(langs.items(), key=lambda kv: -kv[1])],
            "stars": r.stargazers_count,
            "forks": r.forks_count,
            "open_issues": r.open_issues_count,
            "visibility": "private" if r.private else "public",
            "default_branch": r.default_branch,
            "url": r.html_url,
        }

    def get_pull(self, owner: str, repo: str, number: int) -> dict:
        """Fetch a PR and its changed files as a normalized dict (Tool 3)."""
        pr = self.gh.get_repo(f"{owner}/{repo}").get_pull(number)
        files = [
            {"path": f.filename, "status": f.status,
             "additions": f.additions, "deletions": f.deletions,
             "patch": getattr(f, "patch", "") or ""}
            for f in pr.get_files()
        ]
        return {
            "owner": owner, "repo": repo, "number": number,
            "title": pr.title or "", "body": pr.body or "",
            "base_sha": pr.base.sha, "head_sha": pr.head.sha,
            "files": files, "url": pr.html_url,
        }

    def post_pr_comment(self, owner: str, repo: str, number: int, body: str) -> str:
        """Post a comment on a PR (needs a write-scoped token). Returns its URL."""
        pr = self.gh.get_repo(f"{owner}/{repo}").get_pull(number)
        comment = pr.create_issue_comment(body)
        return comment.html_url


def get_repo_meta(repo_key: str, settings, store, *, refresh: bool = False) -> dict | None:
    """Store-cached GitHub metadata for the dashboard header.

    Cache-with-TTL, not cache-forever: stars, forks, description and languages
    all drift upstream, and a refetch is two cheap API calls. A cached copy is
    served while it is younger than `PROFILE_CACHE_HOURS`; past that it
    refreshes itself, so the dashboard shows live GitHub data without the user
    having to ask. `refresh=True` forces a refetch regardless of age.

    Only 'owner/repo' keys have a GitHub side — bare local-clone keys (and runs
    without a token) get whatever is cached, or None.
    """
    from core.db import report_age_hours

    cached = store.load_report("repo_meta", repo_key)
    if "/" not in repo_key or not settings.github_token:
        return cached
    if cached and not refresh:
        age = report_age_hours(cached)
        max_age = getattr(settings, "profile_cache_hours", 24)
        if age is not None and age <= max_age:
            return cached
    try:
        meta = GitHubAPI(settings.github_token).repo_meta(repo_key)
    except Exception as exc:
        if cached:  # stale beats nothing when GitHub is unreachable
            print(f"  [warn] repo metadata refresh failed ({type(exc).__name__}); "
                  f"serving cached copy")
            return cached
        raise
    store.save_report("repo_meta", repo_key, meta)
    return store.load_report("repo_meta", repo_key)  # includes generated_at
