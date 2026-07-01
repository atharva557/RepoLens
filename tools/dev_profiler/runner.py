"""End-to-end Developer Skill Profiler (Tool 2).

Fetches a GitHub user's public activity, classifies their developer type, builds
the profile (reusing Tool 4's commit-message scorer + the optional LLM), and
caches it. Shared by the CLI.
"""
from __future__ import annotations


def run_developer_profile(username: str, settings, store) -> dict | None:
    if not settings.github_token:
        cached = store.load_report("developer_profile", username)
        if cached:
            print("  [warn] no GITHUB_TOKEN - showing cached profile")
            return cached
        raise SystemExit(
            "GITHUB_TOKEN required to build a developer profile. Set it in .env "
            "(needs a token with public read access)."
        )

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
    return profile
