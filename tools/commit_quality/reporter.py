"""Aggregate per-commit quality scores into a repo-wide report (Tool 4).

Produces: overall stats, per-contributor health, repo-wide trend over time, the
most common bad patterns, and the worst N commits (for optional LLM rewrites).

Pure stdlib.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from tools.commit_quality.scorer import score_message


def build_report(commits: list[dict]) -> dict:
    """Score every commit and aggregate. `commits` are v0.1 commit dicts."""
    scored: list[dict] = []
    by_author: dict[str, list[int]] = defaultdict(list)
    by_month: dict[str, list[int]] = defaultdict(list)
    issue_counts: Counter = Counter()

    for c in commits:
        res = score_message(c.get("message", ""))
        author = c.get("author") or c.get("email") or "unknown"
        subject = (c.get("message", "").strip().split("\n", 1)[0]).strip()
        month = c["date"].strftime("%Y-%m") if c.get("date") else "?"
        scored.append({
            "sha": c.get("sha", "")[:8],
            "author": author,
            "month": month,
            "subject": subject,
            "score": res["score"],
            "issues": res["issues"],
        })
        by_author[author].append(res["score"])
        by_month[month].append(res["score"])
        for issue in res["issues"]:
            issue_counts[issue] += 1

    n = len(scored) or 1
    avg = sum(s["score"] for s in scored) / n

    contributors = sorted(
        ({"author": a, "commits": len(v), "avg_score": round(sum(v) / len(v), 2)}
         for a, v in by_author.items()),
        key=lambda d: d["avg_score"],
    )
    trend = [
        {"month": m, "commits": len(v), "avg_score": round(sum(v) / len(v), 2)}
        for m, v in sorted(by_month.items())
    ]
    worst = sorted(scored, key=lambda s: (s["score"], s["subject"]))

    return {
        "commits": len(scored),
        "avg_score": round(avg, 2),
        "good": sum(1 for s in scored if s["score"] >= 7),
        "weak": sum(1 for s in scored if s["score"] < 4),
        # dashboard quality-card aggregates (issue labels come from the scorer)
        "avg_subject_len": round(sum(len(s["subject"]) for s in scored) / n, 1),
        "pct_imperative": round(100 * sum(
            1 for s in scored
            if "does not start with an imperative verb" not in s["issues"]) / n),
        "pct_referenced": round(100 * sum(
            1 for s in scored
            if "no issue/ticket reference" not in s["issues"]) / n),
        "contributors": contributors,
        "trend": trend,
        "common_issues": issue_counts.most_common(6),
        "worst": worst,
        "scored": scored,
    }
