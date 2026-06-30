"""Plain-English explanations for hotspot scores.

Every prediction comes with a reason (guide §2, principle #1). This turns the
raw features + normalized components behind a FileScore into a short list of
human-readable reasons, ordered by importance.

Pure stdlib.
"""
from __future__ import annotations

from tools.bug_hotspot.scorer import FileScore


def explain(fs: FileScore, *, churn_window_days: int = 30, limit: int = 3) -> list[str]:
    """Return up to `limit` reasons explaining why a file scored as it did."""
    r = fs.raw
    c = fs.components
    candidates: list[tuple[float, str]] = []

    if r.get("bugfix_count"):
        candidates.append(
            (
                c.get("bug", 0),
                f"{r['bugfix_count']} bug-fix commit(s) "
                f"(recency-weighted {r.get('bug_score', 0)})",
            )
        )
    if r.get("last_was_bugfix"):
        candidates.append(
            (0.9, f"latest change ({r.get('last_change_days')}d ago) was a bug fix")
        )
    if r.get("churn_window"):
        candidates.append(
            (
                c.get("churn", 0),
                f"{r['churn_window']} change(s) in last {churn_window_days}d",
            )
        )
    if (r.get("authors") or 0) >= 3:
        candidates.append((c.get("authors", 0), f"{r['authors']} distinct authors"))
    if r.get("cyclomatic"):
        candidates.append((c.get("complexity", 0), f"cyclomatic complexity {r['cyclomatic']}"))
    elif r.get("loc"):
        candidates.append((c.get("complexity", 0) * 0.5, f"{r['loc']} LOC"))

    candidates.sort(key=lambda t: t[0], reverse=True)
    reasons = [text for _, text in candidates[:limit]]
    return reasons or ["low activity"]


def explain_all(scores: list[FileScore], *, churn_window_days: int = 30) -> list[FileScore]:
    """Attach `.reasons` to each FileScore in-place and return the list."""
    for fs in scores:
        fs.reasons = explain(fs, churn_window_days=churn_window_days)
    return scores
