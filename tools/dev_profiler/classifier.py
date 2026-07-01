"""Threshold/rule-based developer-type classification (Tool 2).

Aggregates a user's activity into per-type signals and produces a percentage
distribution over the six developer types from guide §3.2:

    Bug Fixer          - high share of bug-fix commits, edits existing files
    Feature Builder    - creates new files / new functionality
    Refactorer         - removes more than it adds; restructures
    Reviewer           - high PR-review participation relative to commits
    Documentation Writer - consistent docs / markdown contributions
    Architect          - touches many files at once, adds dependencies/modules

This is the "basic classification" of v0.2 — pure stdlib, no LLM — so it is
deterministic and unit-testable. The LLM adds a qualitative read separately
(`llm_analyzer.py`).

Expected `activity` shape (produced by pipeline/fetch_user_activity.py):
    {
      "username": str,
      "commits": [
        {"additions": int, "deletions": int, "message": str, "is_bugfix": bool,
         "files": [{"path": str, "status": "added|modified|removed|renamed"}], ...},
      ],
      "reviews_count": int,        # PRs the user reviewed
      "review_comments": int,      # review comments authored
      ...
    }
"""
from __future__ import annotations

DEV_TYPES = [
    "Bug Fixer", "Feature Builder", "Refactorer",
    "Reviewer", "Documentation Writer", "Architect",
]

_DOC_EXT = (".md", ".rst", ".txt", ".adoc")
_DOC_HINT = ("readme", "docs/", "doc/", "changelog", "license")
_DEP_FILES = (
    "requirements.txt", "pyproject.toml", "setup.py", "pipfile", "package.json",
    "go.mod", "cargo.toml", "pom.xml", "build.gradle", "gemfile", "composer.json",
)


def _is_doc(path: str) -> bool:
    p = path.lower()
    return p.endswith(_DOC_EXT) or any(h in p for h in _DOC_HINT)


def _is_dep(path: str) -> bool:
    return path.lower().rsplit("/", 1)[-1] in _DEP_FILES


def extract_signals(activity: dict) -> dict:
    """Compute the raw per-type signals from a user's activity (0..1 each)."""
    commits = activity.get("commits", [])
    n = len(commits)
    reviews = activity.get("reviews_count", 0)

    if n == 0:
        return {t: 0.0 for t in DEV_TYPES} | {"commits": 0}

    bugfix = sum(1 for c in commits if c.get("is_bugfix"))
    created = sum(1 for c in commits
                  if any(f.get("status") == "added" for f in c.get("files", [])))
    delete_heavy = sum(1 for c in commits
                       if c.get("deletions", 0) > c.get("additions", 0))
    files_touched = 0
    doc_files = 0
    dep_commits = 0
    big_commits = 0
    for c in commits:
        files = c.get("files", [])
        files_touched += len(files)
        doc_files += sum(1 for f in files if _is_doc(f.get("path", "")))
        if any(_is_dep(f.get("path", "")) for f in files):
            dep_commits += 1
        if len(files) >= 8:
            big_commits += 1

    doc_ratio = doc_files / files_touched if files_touched else 0.0
    # reviewer share = proportion of total activity that is reviewing
    reviewer = reviews / (n + reviews) if (n + reviews) else 0.0

    return {
        "Bug Fixer": bugfix / n,
        "Feature Builder": created / n,
        "Refactorer": delete_heavy / n,
        "Reviewer": reviewer,
        "Documentation Writer": doc_ratio,
        "Architect": (big_commits / n) * 0.6 + (dep_commits / n) * 0.4,
        "commits": n,
    }


def classify(activity: dict) -> dict:
    """Return {primary_type, distribution(pct), signals}."""
    signals = extract_signals(activity)
    raw = {t: max(0.0, signals.get(t, 0.0)) for t in DEV_TYPES}
    total = sum(raw.values())
    if total <= 0:
        distribution = {t: 0 for t in DEV_TYPES}
        primary = "Unknown"
    else:
        distribution = {t: round(100 * v / total) for t, v in raw.items()}
        primary = max(raw, key=raw.get)
    # secondary type for a "hybrid" label when close
    ordered = sorted(raw, key=raw.get, reverse=True)
    hybrid = (primary if total <= 0 else
              (f"{ordered[0]} / {ordered[1]}"
               if raw[ordered[1]] >= 0.66 * raw[ordered[0]] and raw[ordered[1]] > 0
               else primary))

    return {
        "primary_type": primary,
        "label": hybrid,
        "distribution": dict(sorted(distribution.items(), key=lambda kv: kv[1], reverse=True)),
        "signals": signals,
    }
