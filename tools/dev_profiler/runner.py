"""End-to-end Developer Skill Profiler (Tool 2).

Fetches a GitHub user's public activity, classifies their developer type, builds
the profile (reusing Tool 4's commit-message scorer + the optional LLM), and
caches it in the store. Database-first: any cached profile is served without
touching GitHub (PROFILE_CACHE_HOURS only marks it stale in the message);
`refresh=True` — the UI's re-fetch button — forces a rebuild. Shared by the
CLI and the API.
"""
from __future__ import annotations

from core.db import report_age_hours


def run_developer_profile(username: str, settings, store, *,
                          refresh: bool = False, progress=None) -> dict | None:
    cached = store.load_report("developer_profile", username)

    if not settings.github_token:
        if cached:
            print("  [cache] no GITHUB_TOKEN - showing cached profile")
            return cached
        raise SystemExit(
            "GITHUB_TOKEN required to build a developer profile. Set it in .env "
            "(needs a token with public read access)."
        )

    # Database-first: any cached profile is served as-is; GitHub is only hit
    # on the first build or an explicit refresh (the UI's re-fetch button).
    # PROFILE_CACHE_HOURS now just marks the profile as stale in the message.
    if cached and not refresh:
        age = report_age_hours(cached)
        max_age = getattr(settings, "profile_cache_hours", 24)
        note = f"built {age:.1f}h ago" if age is not None else "age unknown"
        if age is not None and age > max_age:
            note += " - stale; re-fetch to rebuild"
        print(f"  [cache] using cached profile for @{username} ({note})")
        return cached
    if cached and refresh:
        print(f"  [cache] ignoring cached profile for @{username} (re-fetch requested)")

    from core.github_client import GitHubAPI
    from core.llm import get_llm
    from pipeline.fetch_user_activity import fetch_user_activity
    from tools.dev_profiler.profile_builder import build_profile

    from core.progress import reporter_or_print

    report = reporter_or_print(progress)
    print(f"  fetching @{username} activity via GitHub API (this can take a minute) ...")
    api = GitHubAPI(settings.github_token)
    activity = fetch_user_activity(api, username, settings, progress=progress)
    if not activity["commits"]:
        # Refuse to persist an all-zeros "Unknown" profile: it would be cached
        # and listed as if it were real analysis. The usual cause is profiling
        # an *organization* (orgs never author commits) or an empty account.
        raise SystemExit(
            f"@{username} has no authored commits in their recent public "
            f"repositories, so a developer profile cannot be built. If this is "
            f"an organization account, profile one of its members instead."
        )

    report("building profile (processing + LLM summary)")
    profile = build_profile(activity, settings, llm=get_llm(settings))
    report("saving profile (database)", pct=100)
    store.save_report("developer_profile", username, profile)
    print(f"  [cache] profile for @{username} saved to the {store.backend} store")
    return profile
