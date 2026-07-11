"""LLM read of a developer's PR descriptions / review comments (Tool 2).

Adds a qualitative paragraph on top of the deterministic classifier. Provider-
agnostic and optional — returns None when no LLM is configured.
"""
from __future__ import annotations

_SYSTEM = "You are a concise engineering manager summarizing a developer's style."

_PROMPT = """\
Based on these pull-request descriptions written by @{username}, write 2-3 short
sentences describing their working style and strengths. Be specific and neutral.
Output only the summary.

PR descriptions:
{samples}
"""


def analyze(llm, username: str, pr_samples: list[str]) -> str | None:
    """Return a short LLM summary, or None if unavailable / no samples."""
    if llm is None or not llm.available() or not pr_samples:
        return None
    from core.llm import LLMUnavailable

    samples = "\n---\n".join(s.strip() for s in pr_samples if s and s.strip())[:4000]
    if not samples:
        return None
    try:
        return llm.generate(_PROMPT.format(username=username, samples=samples),
                            system=_SYSTEM).strip()
    except LLMUnavailable:
        return None
