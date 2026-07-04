"""Post the pre-review report as a GitHub PR comment (Tool 3).

Outward-facing and opt-in — the runner only calls this when the user explicitly
confirms. Needs a write-scoped token.
"""
from __future__ import annotations


def post_comment(api, pr: dict, markdown: str) -> str:
    return api.post_pr_comment(pr["owner"], pr["repo"], pr["number"], markdown)
