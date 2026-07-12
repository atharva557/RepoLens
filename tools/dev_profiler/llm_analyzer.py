"""LLM read of a developer's activity (Tool 2).

Adds a qualitative paragraph on top of the deterministic classifier. Provider-
agnostic and optional — returns None when no LLM is configured.

It summarizes from the WHOLE picture we already compute — the developer type
distribution, language mix, commit/PR/review counts, commit-message quality,
and a few real commit subjects — not just PR descriptions. Summarizing PR
bodies alone meant anyone without authored PRs (or with empty PR bodies) got
no summary at all, which is most users.
"""
from __future__ import annotations

_SYSTEM = ("You are a concise engineering manager describing a developer's "
           "style from their GitHub activity. Be specific and neutral; every "
           "claim must follow from the data given.")

_PROMPT = """\
Write 2-3 short sentences describing @{username}'s working style and strengths.
Ground every statement in the data below — do not invent projects or facts.
Output only the summary, no preamble.

{digest}
"""


def _build_digest(username: str, context: dict) -> str:
    lines = [f"developer: @{username}"]
    dist = context.get("distribution") or {}
    if dist:
        ranked = sorted(dist.items(), key=lambda kv: -kv[1])
        top = ", ".join(f"{k} {round(v)}%" for k, v in ranked[:4] if v)
        lines.append(f"developer-type mix: {top}")
    if context.get("primary_type"):
        lines.append(f"primary type: {context['primary_type']}")
    if context.get("top_languages"):
        lines.append(f"top languages: {', '.join(context['top_languages'][:5])}")
    lines.append(
        f"activity: {context.get('commits_analyzed', 0)} commits across "
        f"{context.get('repos_analyzed', 0)} repos; "
        f"{context.get('authored_prs', 0)} PRs authored, "
        f"{context.get('prs_merged', 0)} merged; "
        f"{context.get('reviews', 0)} PRs reviewed"
    )
    q = context.get("commit_message_quality")
    if q is not None:
        lines.append(f"commit-message quality: {q}/10")
    subjects = context.get("commit_subjects") or []
    if subjects:
        lines.append("recent commit subjects:")
        lines += [f"  - {s}" for s in subjects[:8]]
    pr_samples = context.get("pr_samples") or []
    if pr_samples:
        joined = " | ".join(s.strip().replace("\n", " ")[:120]
                            for s in pr_samples[:4] if s and s.strip())
        if joined:
            lines.append(f"PR descriptions: {joined}")
    return "\n".join(lines)


def analyze(llm, username: str, context: dict | None = None) -> str | None:
    """Return a short LLM summary, or None if unavailable / no activity.

    `context` carries the computed profile fields (distribution, languages,
    counts, commit subjects, pr_samples). For backwards compatibility a plain
    list is still accepted and treated as `pr_samples`.
    """
    if isinstance(context, list):        # legacy call shape: just pr_samples
        context = {"pr_samples": context}
    context = context or {}
    if llm is None or not llm.available():
        return None
    # nothing to say about an account with no commits and no PR text
    if not context.get("commits_analyzed") and not context.get("pr_samples"):
        return None

    from core.llm import LLMUnavailable

    try:
        text = llm.generate(
            _PROMPT.format(username=username, digest=_build_digest(username, context)),
            system=_SYSTEM,
        ).strip()
    except LLMUnavailable:
        return None
    return text or None
