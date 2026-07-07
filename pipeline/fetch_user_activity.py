"""Pull a GitHub user's public activity into a normalized `activity` dict (Tool 2).

Uses the GitHubAPI wrapper, applies the configured caps, and classifies commits
as bug-fixes (reusing the v0.1 keyword classifier). The output feeds the
classifier and profile builder.
"""
from __future__ import annotations

from collections import Counter

from pipeline.classify_commits import classify_commits


def fetch_user_activity(api, username: str, settings) -> dict:
    commits: list[dict] = []
    languages: Counter = Counter()
    repos: list[str] = []

    for repo in api.list_user_repos(username, settings.profile_max_repos):
        repos.append({
            "name": getattr(repo, "name", "?"),
            "full_name": getattr(repo, "full_name", "?"),
            "stars": getattr(repo, "stargazers_count", 0),
            "forks": getattr(repo, "forks_count", 0),
            "language": getattr(repo, "language", ""),
            "updated_at": repo.updated_at.isoformat() if getattr(repo, "updated_at", None) else None,
            "url": getattr(repo, "html_url", ""),
        })
        lang = getattr(repo, "language", None)
        if lang:
            languages[lang] += 1
        commits.extend(
            api.iter_repo_commits(repo, username, settings.profile_max_commits_per_repo)
        )

    classify_commits(commits, settings.bug_keywords)
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
