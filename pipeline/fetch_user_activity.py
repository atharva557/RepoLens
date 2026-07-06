"""Pull a GitHub user's public activity into a normalized `activity` dict (Tool 2).

Uses the GitHubAPI wrapper, applies the configured caps, and classifies commits
as bug-fixes (reusing the v0.1 keyword classifier). The output feeds the
classifier and profile builder.
"""
from __future__ import annotations

from collections import Counter

from pipeline.classify_commits import classify_commits


def fetch_user_activity(api, username: str, settings, progress=None) -> dict:
    from core.progress import reporter_or_print

    report = reporter_or_print(progress)
    commits: list[dict] = []
    languages: Counter = Counter()
    repos: list[str] = []

    report("listing repositories (GitHub)", detail=f"@{username}")
    user_repos = api.list_user_repos(username, settings.profile_max_repos)
    for i, repo in enumerate(user_repos):
        name = getattr(repo, "full_name", "?")
        # the dominant cost: one API call per commit — show which repo and
        # how far along we are so long builds are never a black box
        report("fetching commits (GitHub)",
               pct=int(i * 100 / max(len(user_repos), 1)),
               detail=f"{name} ({i + 1}/{len(user_repos)})")
        repos.append(name)
        lang = getattr(repo, "language", None)
        if lang:
            languages[lang] += 1
        commits.extend(
            api.iter_repo_commits(repo, username, settings.profile_max_commits_per_repo)
        )

    classify_commits(commits, settings.bug_keywords)
    report("fetching PR & review stats (GitHub)", pct=100)
    authored, pr_samples = api.authored_prs(username, settings.profile_pr_sample)
    reviews = api.reviews_count(username)

    try:  # social header is decoration — never let it sink the profile
        user = api.user_meta(username)
    except Exception:
        user = {}

    return {
        "username": username,
        "commits": commits,
        "languages": dict(languages),
        "repos": repos,
        "authored_prs": authored,
        "pr_samples": pr_samples,
        "reviews_count": reviews,
        "user": user,
        "merged_prs": api.merged_prs_count(username),
        "issues_resolved": api.issues_resolved_count(username),
    }
