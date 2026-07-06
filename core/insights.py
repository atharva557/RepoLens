"""Repo-level AI insight bullets (the dashboard's "AI INSIGHTS" card, v0.4).

Builds a compact statistical digest from everything already in the store for a
repo — activity aggregates, top hotspots, commit quality — and asks the
configured LLM (core/llm.py) for a few plain-English observations. The result
is cached as a 'repo_insights' report so the dashboard reads it instantly.
"""
from __future__ import annotations

from core.activity import build_activity
from core.llm import LLMUnavailable, get_llm

_SYSTEM = ("You are a senior engineer summarizing repository analytics. "
           "Be concrete and neutral; every claim must come from the digest.")

_PROMPT = """From this repository analytics digest, write exactly 3 short insight
bullets (one sentence each) a maintainer would find useful. Start each line
with "- ". No preamble, no headings.

{digest}
"""


def _digest(repo_key: str, activity: dict, quality: dict | None,
            hotspots: dict | None) -> str:
    lines = [f"repo: {repo_key}",
             f"total commits cached: {activity['total_commits']}",
             f"commits in last {activity['window_days']} days: "
             f"{activity['window_commits']} "
             f"(bug-fix ratio {activity['window_bugfix_ratio']})",
             f"contributors: {activity['contributors_total']}"]
    if activity["contributors"]:
        top = ", ".join(f"{c['author']} ({c['commits']})"
                        for c in activity["contributors"][:3])
        lines.append(f"top contributors: {top}")
    if quality:
        lines.append(f"commit-message quality: avg {quality.get('avg_score')}/10, "
                     f"{quality.get('good')} good / {quality.get('weak')} weak")
        issues = quality.get("common_issues") or []
        if issues:
            lines.append("common message issues: "
                         + ", ".join(f"{i} ({n})" for i, n in issues[:3]))
    rows = (hotspots or {}).get("rows") or []
    if rows:
        lines.append("top bug-hotspot files: "
                     + ", ".join(r.get("path", "?") for r in rows[:5]))
    return "\n".join(lines)


def run_repo_insights(repo_key: str, settings, store, progress=None) -> dict:
    """Generate + cache insight bullets. Raises LLMUnavailable without an LLM."""
    from core.progress import reporter_or_print

    report_progress = reporter_or_print(progress)
    report_progress("building analytics digest (database)")
    commits = store.load_commits(repo_key)
    if not commits:
        raise SystemExit(f"no cached commits for '{repo_key}' — run an analysis first")

    quality = store.load_report("commit_quality", repo_key)
    hotspots = store.load_hotspots(repo_key)
    activity = build_activity(commits, quality=quality)

    llm = get_llm(settings)
    if not llm.available():
        raise LLMUnavailable(
            f"LLM provider '{llm.describe()}' is not available — insights need one")

    report_progress("generating insights (LLM)", detail=llm.describe())
    # reasoning models (e.g. local gemma) spend tokens thinking before any
    # visible output — a 512-token budget can truncate to empty content
    text = llm.generate(_PROMPT.format(digest=_digest(repo_key, activity, quality,
                                                      hotspots)),
                        system=_SYSTEM,
                        max_tokens=max(1536, getattr(settings, "llm_max_tokens", 512)))
    bullets = [ln.lstrip("-•* ").strip() for ln in text.splitlines()
               if ln.strip().lstrip("-•* ").strip()]
    if not bullets:
        raise LLMUnavailable("LLM returned no usable insight text "
                             "(if this persists, raise LLM_MAX_TOKENS)")

    report = {
        "repo": repo_key,
        "bullets": bullets[:4],
        "provider": llm.describe(),
        "based_on": {
            "commits": activity["total_commits"],
            "has_commit_quality": quality is not None,
            "has_hotspots": bool((hotspots or {}).get("rows")),
        },
    }
    store.save_report("repo_insights", repo_key, report)
    return report
