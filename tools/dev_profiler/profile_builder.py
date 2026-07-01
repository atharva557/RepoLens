"""Assemble the final developer profile card (Tool 2).

Combines the rule-based classification, language mix, review participation, and
the commit-message quality (reusing Tool 4's scorer) into one document, plus an
optional LLM summary. Pure stdlib aside from the optional LLM call.
"""
from __future__ import annotations

from collections import Counter

from tools.commit_quality.scorer import score_message
from tools.dev_profiler.classifier import classify
from tools.dev_profiler.llm_analyzer import analyze


def _commit_quality(commits: list[dict]) -> float:
    scores = [score_message(c.get("message", ""))["score"] for c in commits]
    return round(sum(scores) / len(scores), 1) if scores else 0.0


def build_profile(activity: dict, settings, llm=None) -> dict:
    username = activity.get("username", "?")
    commits = activity.get("commits", [])
    classification = classify(activity)

    languages = Counter(activity.get("languages", {}))
    top_languages = [lang for lang, _ in languages.most_common(5)]

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
        "commit_message_quality": _commit_quality(commits),
        "authored_prs": activity.get("authored_prs", 0),
        "reviews": reviews,
        "review_participation": participation,
        "llm_summary": analyze(llm, username, activity.get("pr_samples", [])),
    }
    return profile
