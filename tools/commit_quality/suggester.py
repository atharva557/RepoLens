"""LLM-based commit-message suggestion engine (Tool 4).

The rule-based scorer detects *that* a message is weak; the suggester proposes a
better one. It needs the actual diff — you can't write a meaningful message from
the old message alone (guide §3.4) — so the caller passes the commit's diff.

Provider-agnostic: takes any `LLMProvider` (local/openai/claude/gemini) and
degrades to a clear placeholder when no LLM is configured.
"""
from __future__ import annotations

_SYSTEM = (
    "You are an expert software engineer who writes clear, conventional git "
    "commit messages."
)

_PROMPT = """\
Rewrite the following git commit message so it is clear and useful.

Rules:
- First line: an imperative subject under 72 characters (e.g. "Fix ...", "Add ...").
- Then a blank line and 1-3 short lines explaining WHAT changed and WHY.
- Base it on the actual diff, not just the old message.
- Output ONLY the commit message, no commentary or backticks.

Original message:
{message}

Diff (truncated):
{diff}
"""


def suggest(llm, message: str, diff: str, *, max_diff_chars: int = 3000) -> str:
    """Return an improved commit message, or a placeholder if no LLM is available."""
    if llm is None or not llm.available():
        return "(LLM unavailable - configure LLM_PROVIDER to enable rewrites)"
    from core.llm import LLMUnavailable

    prompt = _PROMPT.format(message=message.strip(), diff=(diff or "")[:max_diff_chars])
    try:
        return llm.generate(prompt, system=_SYSTEM).strip()
    except LLMUnavailable as exc:
        return f"(LLM error: {exc})"
