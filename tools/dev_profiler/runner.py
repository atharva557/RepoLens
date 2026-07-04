"""End-to-end Developer Skill Profiler (Tool 2).

Fetches a GitHub user's public activity, classifies their developer type, builds
the profile (reusing Tool 4's commit-message scorer + the optional LLM), and
caches it in the store. A fresh cached profile (younger than
PROFILE_CACHE_HOURS) is reused instead of re-hitting the GitHub API; pass
`refresh=True` to force a rebuild. Shared by the CLI and the API.
"""
from __future__ import annotations

from core.db import report_age_hours


def run_developer_profile(username: str, settings, store, *,
                          refresh: bool = False) -> dict | None:
    cached = store.load_report("developer_profile", username)

    if not settings.github_token:
        if cached:
            print("  [cache] no GITHUB_TOKEN - showing cached profile")
            return cached
        raise SystemExit(
            "GITHUB_TOKEN required to build a developer profile. Set it in .env "
            "(needs a token with public read access)."
        )

    max_age = getattr(settings, "profile_cache_hours", 24)
    if cached and not refresh:
        age = report_age_hours(cached)
        if age is not None and age <= max_age:
            print(f"  [cache] using cached profile for @{username} "
                  f"(built {age:.1f}h ago; re-fetch to rebuild)")
            return cached
    if cached and refresh:
        print(f"  [cache] ignoring cached profile for @{username} (re-fetch requested)")

    from core.github_client import GitHubAPI
    from core.llm import get_llm
    from pipeline.fetch_user_activity import fetch_user_activity
    from tools.dev_profiler.profile_builder import build_profile

    print(f"  fetching @{username} activity via GitHub API (this can take a minute) ...")
    api = GitHubAPI(settings.github_token)
    activity = fetch_user_activity(api, username, settings)
    if not activity["commits"]:
        print(f"  [warn] no public commits found for @{username}")

    profile = build_profile(activity, settings, llm=get_llm(settings))
    store.save_report("developer_profile", username, profile)
    print(f"  [cache] profile for @{username} saved to the {store.backend} store")
    return profile
