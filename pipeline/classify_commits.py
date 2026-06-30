"""Bug-fix commit classification via commit-message keyword detection.

This is the foundation of the SZZ approach referenced in §3.1 of the guide:
a commit is treated as a *bug-fix* if its message contains a fix-related
keyword. Pure stdlib — no third-party dependencies — so it is trivially
unit-testable.

Matching uses a left word-boundary so that:
  - "fix"   matches "fix", "fixes", "fixed", "fixing"
  - "fix"   does NOT match "prefix" / "postfix" (no boundary before "fix")
  - "patch" does NOT match "dispatch"
Multi-word / symbol keywords (e.g. "closes #") fall back to substring search.
"""
from __future__ import annotations

import re
from functools import lru_cache

DEFAULT_KEYWORDS = ["fix", "bug", "resolve", "patch", "hotfix", "closes"]


@lru_cache(maxsize=64)
def _compile(keywords: tuple[str, ...]) -> list[tuple[str, re.Pattern | None]]:
    compiled: list[tuple[str, re.Pattern | None]] = []
    for kw in keywords:
        kw = kw.strip().lower()
        if not kw:
            continue
        if kw.isalnum():
            compiled.append((kw, re.compile(r"\b" + re.escape(kw), re.IGNORECASE)))
        else:
            # contains a space or symbol (e.g. "closes #") -> plain substring
            compiled.append((kw, None))
    return compiled


def is_bugfix(message: str, keywords: list[str] | None = None) -> bool:
    """Return True if `message` looks like a bug-fix commit."""
    if not message:
        return False
    text = message.lower()
    for kw, pat in _compile(tuple(keywords or DEFAULT_KEYWORDS)):
        if pat is not None:
            if pat.search(text):
                return True
        elif kw in text:
            return True
    return False


def classify_commits(commits: list[dict], keywords: list[str] | None = None) -> list[dict]:
    """Annotate each commit dict in-place with an `is_bugfix` flag."""
    kw = keywords or DEFAULT_KEYWORDS
    for c in commits:
        c["is_bugfix"] = is_bugfix(c.get("message", ""), kw)
    return commits
