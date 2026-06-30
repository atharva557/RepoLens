"""Per-file feature engineering for the Bug Hotspot Predictor (Tool 1).

Consumes classified commit dicts and produces one feature row per file. The
headline feature is the **recency-weighted bug score**: every bug-fix commit
that touched a file contributes a weight that decays exponentially with age
(half-life = `halflife_days`). Recent bugs dominate; ancient ones fade.

Pure stdlib so it is fully unit-testable without git, MongoDB, or a network.

Commit dict shape (see core/git_client.py):
    {
        "sha": str, "author": str, "email": str,
        "date": datetime (tz-aware, UTC), "message": str,
        "is_bugfix": bool,
        "files": [{"path": str, "insertions": int, "deletions": int}, ...],
    }
"""
from __future__ import annotations

from datetime import datetime, timezone

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _age_days(as_of: datetime, when: datetime) -> float:
    return (as_of - when).total_seconds() / 86400.0


def build_file_features(
    commits: list[dict],
    *,
    as_of: datetime | None = None,
    churn_window_days: int = 30,
    halflife_days: int = 30,
    metrics_by_file: dict[str, dict] | None = None,
    existing_files: set[str] | list[str] | None = None,
) -> list[dict]:
    """Aggregate commit history into per-file feature rows.

    Args:
        commits: classified commit dicts (must include `is_bugfix`).
        as_of: reference "now" for recency/age (defaults to current UTC).
        churn_window_days: window for the short-term churn feature.
        halflife_days: exponential decay half-life for the bug score.
        metrics_by_file: optional {path: {"loc": int, "cyclomatic": int|None}}.
        existing_files: if given, only score files still present at HEAD.
    """
    as_of = as_of or datetime.now(timezone.utc)
    metrics_by_file = metrics_by_file or {}
    existing = set(existing_files) if existing_files is not None else None

    acc: dict[str, dict] = {}
    for c in commits:
        when = c["date"]
        age = _age_days(as_of, when)
        decay = 0.5 ** (age / halflife_days) if halflife_days > 0 else 1.0
        is_bug = bool(c.get("is_bugfix"))
        who = c.get("email") or c.get("author") or "unknown"
        for f in c.get("files", []):
            path = f["path"]
            if existing is not None and path not in existing:
                continue
            a = acc.get(path)
            if a is None:
                a = acc[path] = {
                    "commits": 0,
                    "churn_window": 0,
                    "churn_lines": 0,
                    "authors": set(),
                    "bugfix_count": 0,
                    "bug_score": 0.0,
                    "last_date": _EPOCH,
                    "last_was_bugfix": False,
                }
            a["commits"] += 1
            a["churn_lines"] += int(f.get("insertions", 0)) + int(f.get("deletions", 0))
            a["authors"].add(who)
            if age <= churn_window_days:
                a["churn_window"] += 1
            if is_bug:
                a["bugfix_count"] += 1
                a["bug_score"] += decay
            if when > a["last_date"]:
                a["last_date"] = when
                a["last_was_bugfix"] = is_bug

    rows: list[dict] = []
    for path, a in acc.items():
        m = metrics_by_file.get(path, {})
        rows.append(
            {
                "path": path,
                "commits": a["commits"],
                "churn_window": a["churn_window"],
                "churn_lines": a["churn_lines"],
                "authors": len(a["authors"]),
                "bugfix_count": a["bugfix_count"],
                "bug_score": round(a["bug_score"], 4),
                "last_change_days": round(_age_days(as_of, a["last_date"]), 1),
                "last_was_bugfix": a["last_was_bugfix"],
                "loc": int(m.get("loc", 0) or 0),
                "cyclomatic": m.get("cyclomatic"),
            }
        )
    rows.sort(key=lambda r: r["path"])
    return rows
