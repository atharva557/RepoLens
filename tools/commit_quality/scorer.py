"""Rule-based commit-message quality scoring (Tool 4).

Scores a commit message 0-10 across the dimensions from guide §3.4:

    length     subject neither too short nor too long
    vagueness  not just meaningless keywords ("fix", "update", "wip", ...)
    verb       starts with an imperative verb (Add, Fix, Refactor, ...)
    context    explains the *why* (a body, or a descriptive subject)
    reference  links an issue / ticket (#142, ABC-123, "closes #...")

Pure stdlib — no LLM and no third-party deps — so it is fully unit-testable.
The LLM only enters later, in `suggester.py`, to propose better messages.
"""
from __future__ import annotations

import re

# imperative verbs commonly used to open a good commit subject
VERBS = {
    "add", "fix", "remove", "refactor", "update", "implement", "improve",
    "rename", "move", "delete", "bump", "document", "test", "revert", "merge",
    "drop", "replace", "introduce", "support", "handle", "ensure", "prevent",
    "optimize", "simplify", "clean", "format", "correct", "resolve", "patch",
    "hotfix", "create", "build", "configure", "upgrade", "downgrade",
    "deprecate", "restore", "split", "extract", "expose", "disable", "enable",
    "allow", "avoid", "make", "use", "set", "wire", "tidy", "harden",
}

# tokens that, when they make up the *entire* message, signal a vague commit
VAGUE = {
    "fix", "fixes", "fixed", "update", "updates", "updated", "wip", "stuff",
    "change", "changes", "changed", "misc", "cleanup", "minor", "tweak",
    "tweaks", "things", "temp", "various", "small", "bug", "bugfix", "edit",
    "edits", "patch", "stuff", "asdf", "test", "commit", "work", "more",
}

_STOPWORDS = {"a", "an", "the", "to", "of", "in", "and", "for", "on", "it", "is"}
_REF_RE = re.compile(r"(#\d+)|(\b[A-Z][A-Z0-9]+-\d+\b)")


def _subject_body(message: str) -> tuple[str, str]:
    parts = (message or "").strip().split("\n", 1)
    subject = parts[0].strip()
    body = parts[1].strip() if len(parts) > 1 else ""
    return subject, body


def _is_vague(subject: str) -> bool:
    tokens = re.findall(r"[a-z0-9]+", subject.lower())
    meaningful = [t for t in tokens if t not in _STOPWORDS]
    if not meaningful:
        return True
    return all(t in VAGUE for t in meaningful)


def _starts_with_verb(subject: str) -> bool:
    m = re.match(r"\s*([A-Za-z]+)", subject)
    return bool(m) and m.group(1).lower() in VERBS


def score_message(message: str) -> dict:
    """Return {score, issues, ...features} for a single commit message."""
    subject, body = _subject_body(message)
    subj_len = len(subject)
    vague = _is_vague(subject)
    imperative = _starts_with_verb(subject)
    has_ref = bool(_REF_RE.search(message or ""))
    has_context = bool(body) or (subj_len >= 35 and not vague)

    score = 0
    issues: list[str] = []

    # length (max 2)
    if subj_len < 15:
        issues.append(f"subject too short ({subj_len} chars)")
    elif subj_len > 72:
        score += 1
        issues.append(f"subject too long ({subj_len} chars)")
    else:
        score += 2

    # vagueness (max 3)
    if vague:
        issues.append("vague / meaningless message")
    else:
        score += 3

    # imperative verb (max 2)
    if imperative:
        score += 2
    else:
        issues.append("does not start with an imperative verb")

    # context / why (max 2)
    if has_context:
        score += 2
    else:
        issues.append("no body explaining why")

    # issue reference (max 1)
    if has_ref:
        score += 1
    else:
        issues.append("no issue/ticket reference")

    return {
        "score": score,
        "issues": issues,
        "subject_len": subj_len,
        "vague": vague,
        "imperative": imperative,
        "has_context": has_context,
        "has_reference": has_ref,
    }
