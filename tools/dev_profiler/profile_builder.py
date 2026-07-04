"""Assemble the final developer profile card (Tool 2).

Combines the rule-based classification, language mix, review participation, and
the commit-message quality (reusing Tool 4's scorer) into one document, plus an
optional LLM summary. Pure stdlib aside from the optional LLM call.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from tools.commit_quality.scorer import score_message
from tools.dev_profiler.classifier import classify
from tools.dev_profiler.llm_analyzer import analyze


def _commit_quality(commits: list[dict]) -> float:
    scores = [score_message(c.get("message", ""))["score"] for c in commits]
    return round(sum(scores) / len(scores), 1) if scores else 0.0


def _daily_heatmap(commits: list[dict], days: int = 365) -> list[dict]:
    """Per-day commit counts over the last `days` — the profile heatmap."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    daily: Counter = Counter()
    for c in commits:
        dt = c.get("date")
        if not isinstance(dt, datetime):
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt >= cutoff:
            daily[dt.date().isoformat()] += 1
    return [{"date": d, "count": n} for d, n in sorted(daily.items())]


def build_profile(activity: dict, settings, llm=None) -> dict:
    username = activity.get("username", "?")
    commits = activity.get("commits", [])
    classification = classify(activity)

    languages = Counter(activity.get("languages", {}))
    top_languages = [lang for lang, _ in languages.most_common(5)]
    lang_total = sum(languages.values()) or 1
    language_shares = [{"name": lang, "pct": round(100 * n / lang_total, 1)}
                       for lang, n in languages.most_common()]

    reviews = activity.get("reviews_count", 0)
    # review participation, judged relative to how much the user commits
    if reviews == 0:
        participation = "Low"
    elif reviews >= max(1, len(commits)) * 0.2:
        participation = f"Active ({reviews} PRs reviewed)"
    else:
        participation = f"Occasional ({reviews} PRs reviewed)"

    profile = {
        "username": username,
        "primary_type": classification["primary_type"],
        "label": classification["label"],
        "activity_split": classification["distribution"],
        "commits_analyzed": len(commits),
        "repos_analyzed": len(activity.get("repos", [])),
        "top_languages": top_languages,
        "languages": language_shares,
        "commit_message_quality": _commit_quality(commits),
        "authored_prs": activity.get("authored_prs", 0),
        "prs_merged": activity.get("merged_prs", 0),
        "issues_resolved": activity.get("issues_resolved", 0),
        "reviews": reviews,
        "review_participation": participation,
        "user": activity.get("user") or {},
        "heatmap": _daily_heatmap(commits),
        "llm_summary": analyze(llm, username, activity.get("pr_samples", [])),
    }
    return profile
