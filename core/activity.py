"""Read-side activity aggregation for the dashboard (v0.4).

Turns the cached commit history into the shapes the dashboard's Repo Overview
needs — contributor leaderboard, daily heatmap buckets, recent commits and a
transparent 0-10 health score — without touching the repository again.

Split in two for performance: `build_activity_base` is the expensive pass over
every commit, computed ONCE when a history is saved (pipeline/fetch_commits)
and cached as an `activity_base` report; `window_activity` is the cheap
per-request step (time-window totals + health composite) over that base.
Serving `GET /repos/{key}/activity` used to re-read and re-scan the entire
commit list (~47k docs for nodejs/node) on every dashboard view.

Pure stdlib; consumed by `GET /repos/{key}/activity` and the insights digest.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from core.paths import is_code_file

# recent commits kept in the base; requests slice this (API caps recent<=50)
_RECENT_MAX = 50


def _aware(dt) -> datetime | None:
    if not isinstance(dt, datetime):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _is_display_bugfix(c: dict) -> bool:
    """The hotspot scorer's code-files-only gate, applied at the display
    layer: a keyword "fix" that only touched docs/config (a changelog typo)
    must not wear a BUGFIX badge or count toward the health score's bug-fix
    ratio. Commits cached without per-file info can't be checked — trust
    their flag."""
    if not c.get("is_bugfix"):
        return False
    files = c.get("files")
    if not files:
        return True
    return any(is_code_file(f.get("path", "")) for f in files)


def build_activity_base(commits: list[dict]) -> dict:
    """One expensive pass over the full history — everything window-independent.

    Daily buckets carry per-day bugfix counts so any time window can later be
    summed from ≤ a few thousand day rows instead of rescanned from commits.
    """
    by_author: Counter = Counter()
    daily: dict[str, list[int]] = {}  # date -> [count, bugfix_count]
    dated: list[tuple[datetime, dict]] = []

    for c in commits:
        by_author[c.get("author") or c.get("email") or "unknown"] += 1
        dt = _aware(c.get("date"))
        if dt is None:
            continue
        dated.append((dt, c))
        bucket = daily.setdefault(dt.date().isoformat(), [0, 0])
        bucket[0] += 1
        if _is_display_bugfix(c):
            bucket[1] += 1

    dated.sort(key=lambda t: t[0], reverse=True)
    recent_commits = [{
        "sha": (c.get("sha") or "")[:7],
        "subject": (c.get("message") or "").strip().split("\n", 1)[0][:120],
        "author": c.get("author") or "unknown",
        "date": dt.isoformat(),
        "is_bugfix": _is_display_bugfix(c),
    } for dt, c in dated[:_RECENT_MAX]]

    total = len(commits) or 1
    contributors = [{"author": a, "commits": n, "share": round(n / total, 3)}
                    for a, n in by_author.most_common(10)]

    return {
        "total_commits": len(commits),
        "contributors_total": len(by_author),
        "contributors": contributors,
        "recent_commits": recent_commits,
        "daily": [{"date": d, "count": n, "bugfix": b}
                  for d, (n, b) in sorted(daily.items())],
    }


def window_activity(base: dict, *, days: int = 365, recent: int = 15,
                    quality: dict | None = None) -> dict:
    """Cheap per-request step: window totals + health over a cached base.

    `quality` is the stored commit_quality report, if any — its avg_score
    feeds the health composite. Windowing is day-granular (ISO date strings
    compare lexicographically), matching the heatmap's own resolution.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    window_total = window_bugfix = 0
    for row in base.get("daily") or []:
        if row.get("date", "") >= cutoff:
            window_total += row.get("count", 0)
            window_bugfix += row.get("bugfix", 0)

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
        "total_commits": base.get("total_commits", 0),
        "window_days": days,
        "window_commits": window_total,
        "window_bugfix_ratio": bugfix_ratio,
        "contributors_total": base.get("contributors_total", 0),
        "contributors": base.get("contributors") or [],
        "recent_commits": (base.get("recent_commits") or [])[:recent],
        "heatmap": [{"date": r.get("date"), "count": r.get("count", 0)}
                    for r in base.get("daily") or []],
        "health": {"score": health_score, "commit_quality": q,
                   "stability": stability, "formula": formula},
    }


def build_activity(commits: list[dict], *, days: int = 365, recent: int = 15,
                   quality: dict | None = None) -> dict:
    """One-shot compose of base + window, for callers holding raw commits."""
    return window_activity(build_activity_base(commits),
                           days=days, recent=recent, quality=quality)
