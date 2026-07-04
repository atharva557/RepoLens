"""LLM plain-English summary of what a PR actually does (Tool 3).

Independent of the PR's own description — reads the diff. Provider-agnostic and
optional (returns None when no LLM is configured).
"""
from __future__ import annotations

_SYSTEM = "You are a senior engineer writing a concise, factual PR summary for reviewers."

_PROMPT = """\
Summarize what this pull request does in 2-4 sentences, based on the diff (not
just the title). Focus on behavior changes. Output only the summary.

Title: {title}

Diff (truncated):
{diff}
"""


def summarize(llm, pr: dict, *, max_diff_chars: int = 6000) -> str | None:
    if llm is None or not llm.available():
        return None
    from core.llm import LLMUnavailable

    diff = "\n".join(f.get("patch", "") for f in pr.get("files", []))[:max_diff_chars]
    if not diff.strip():
        return None
    try:
        return llm.generate(
            _PROMPT.format(title=pr.get("title", ""), diff=diff), system=_SYSTEM
        ).strip()
    except LLMUnavailable:
        return None
