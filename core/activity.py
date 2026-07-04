"""Read-side activity aggregation for the dashboard (v0.4).

Turns the cached commit history into the shapes the dashboard's Repo Overview
needs — contributor leaderboard, daily heatmap buckets, recent commits and a
transparent 0-10 health score — without touching the repository again.

Pure stdlib; consumed by `GET /repos/{key}/activity` and the insights digest.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone


def _aware(dt) -> datetime | None:
    if not isinstance(dt, datetime):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def build_activity(commits: list[dict], *, days: int = 365, recent: int = 15,
                   quality: dict | None = None) -> dict:
    """Aggregate cached commit dicts (v0.1 shape) into dashboard widgets.

    `quality` is the stored commit_quality report, if any — its avg_score
    feeds the health composite.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    by_author: Counter = Counter()
    daily: Counter = Counter()
    window_total = 0
    window_bugfix = 0
    dated: list[tuple[datetime, dict]] = []

    for c in commits:
        by_author[c.get("author") or c.get("email") or "unknown"] += 1
        dt = _aware(c.get("date"))
        if dt is None:
            continue
        dated.append((dt, c))
        if dt >= cutoff:
            window_total += 1
            window_bugfix += 1 if c.get("is_bugfix") else 0
            daily[dt.date().isoformat()] += 1

    dated.sort(key=lambda t: t[0], reverse=True)
    recent_commits = [{
        "sha": (c.get("sha") or "")[:7],
        "subject": (c.get("message") or "").strip().split("\n", 1)[0][:120],
        "author": c.get("author") or "unknown",
        "date": dt.isoformat(),
        "is_bugfix": bool(c.get("is_bugfix")),
    } for dt, c in dated[:recent]]

    total = len(commits) or 1
    contributors = [{"author": a, "commits": n, "share": round(n / total, 3)}
                    for a, n in by_author.most_common(10)]

    bugfix_ratio = round(window_bugfix / window_total, 3) if window_total else 0.0

    # Transparent 0-10 health score: message quality + recent stability.
    # Formula is returned alongside the number so the UI can explain it.
    stability = round((1 - bugfix_ratio) * 10, 1)
    q = (quality or {}).get("avg_score")
    if q is not None:
        health_score = round(0.6 * q + 0.4 * stability, 1)
        formula = "0.6 * commit_quality + 0.4 * (1 - recent_bugfix_ratio) * 10"
    else:
        health_score = stability
        formula = "(1 - recent_bugfix_ratio) * 10  — run commit-quality for the full composite"

    return {
        "total_commits": len(commits),
        "window_days": days,
        "window_commits": window_total,
        "window_bugfix_ratio": bugfix_ratio,
        "contributors_total": len(by_author),
        "contributors": contributors,
        "recent_commits": recent_commits,
        "heatmap": [{"date": d, "count": n} for d, n in sorted(daily.items())],
        "health": {"score": health_score, "commit_quality": q,
                   "stability": stability, "formula": formula},
    }
