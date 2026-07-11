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

# Small local models happily parrot the digest back ("the total number of
# commits cached is 46993") or drift into tool advice ("use git log"), so the
# prompt bans both and demands that every bullet RELATE facts, not restate one.
_PROMPT = """From this repository analytics digest, write exactly 3 short insight
bullets (one sentence each) for the repository's maintainer.

Rules:
- Each bullet must COMBINE at least two facts from the digest into an
  observation (a comparison, a share, a concentration, or a mismatch) —
  never restate a single number on its own.
- Observations only: no advice, no instructions, no tool suggestions,
  no questions.
- Every number you mention must appear in the digest.
- Start each line with "- ". No preamble, no headings.

Example of a good bullet (for a different repo):
- Nearly half of recent changes (44 of 96 commits) were bug fixes, and three
  of the five riskiest files sit in the same auth/ directory.

{digest}
"""


def keep_bullet(line: str) -> bool:
    """Cheap guard against the two failure modes the prompt bans.

    A real insight derived from a *statistics digest* always carries at least
    one number; advice starts with or contains an instruction verb. This
    cannot catch digest-parroting (those bullets contain numbers too) — the
    prompt handles that — but it reliably drops "use git log to ..." bullets.
    """
    text = (line or "").strip().lower()
    if not any(ch.isdigit() for ch in text):
        return False
    advice_markers = ("you can", "you should", "maintainers can", "consider ",
                      "use the ", "try ", "we recommend", "should be")
    return not any(m in text for m in advice_markers)


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
    lines = [ln.lstrip("-•* ").strip() for ln in text.splitlines()
             if ln.strip().lstrip("-•* ").strip()]
    bullets = [ln for ln in lines if keep_bullet(ln)]
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
