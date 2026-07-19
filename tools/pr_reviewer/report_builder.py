"""Assemble the PR pre-review report (Tool 3).

Produces the markdown that matches the guide's §3.3 example (Risk level,
Warnings, AI summary, OK) plus a structured dict for storage. Pure stdlib.

The risk level comes from a weighted signal score — same brand as Tool 1's
hotspot formula: each fired check contributes a weight, the sum (clamped to
1.0) is the PR risk score, and the level is a band over it. The arithmetic
is printed in the report, so the level is always explainable.
"""
from __future__ import annotations

# Signal weights, strongest evidence first (mirrors the defect-prediction
# reasoning behind Tool 1's weights). Band thresholds live in settings
# (PR_RISK_HIGH / PR_RISK_MEDIUM) so they can be tuned against data.
RISK_WEIGHTS: dict[str, float] = {
    "file_risk": 0.30,        # hotspot source files touched
    "similarity": 0.25,       # diff resembles a past bug fix
    "missing_tests": 0.20,    # source changed, no tests
    "bug_echo": 0.15,         # recently bug-fixed files touched
    "unfocused": 0.10,        # broad, scattered change
    "large_change": 0.10,     # big diff
    "weak_description": 0.05, # missing/vague PR description
}
_LABELS = {
    "file_risk": "hotspot files", "similarity": "similar to past bug",
    "missing_tests": "missing tests", "bug_echo": "recently fixed files",
    "unfocused": "unfocused", "large_change": "large diff",
    "weak_description": "weak description",
}


def _risk_level(risk: dict, similarity: dict, *,
                high: float = 0.5, medium: float = 0.2):
    """Return (level, score, breakdown). One weak signal alone stays LOW;
    corroborated or strong evidence climbs the bands — an always-HIGH level
    is one reviewers learn to ignore."""
    fired = [kind for kind, _ in risk["warnings"]]
    if similarity.get("warn"):
        fired.append("similarity")
    breakdown = [(k, RISK_WEIGHTS.get(k, 0.10)) for k in fired]
    score = round(min(1.0, sum(w for _, w in breakdown)), 2)
    level = "HIGH" if score >= high else "MEDIUM" if score >= medium else "LOW"
    return level, score, breakdown


def build_report(pr: dict, risk: dict, similarity: dict, summary: str | None,
                 *, coverage: dict | None = None,
                 high: float = 0.5, medium: float = 0.2) -> dict:
    level, score, breakdown = _risk_level(risk, similarity, high=high, medium=medium)
    lines: list[str] = ["## 🤖 RepoLens Pre-Review Report", "",
                        f"**Risk Level: {level}** (score {score:.2f})"]
    if breakdown:
        lines.append("Score = " + " + ".join(
            f"{w:.2f} ({_LABELS.get(k, k)})" for k, w in breakdown))

    warn_msgs = [msg for _, msg in risk["warnings"]]
    if similarity.get("warn") and similarity.get("matches"):
        top = similarity["matches"][0]
        warn_msgs.append(
            f"diff resembles a past bug-fix "
            f"({top['meta'].get('sha', top['id'])}, similarity {similarity['max_score']})"
        )
    if warn_msgs:
        lines += ["", "### ⚠️ Warnings"] + [f"- {m}" for m in warn_msgs]

    # honesty notes: blind spots + which checks could not run
    notes = list(risk.get("notes") or [])
    cov = coverage or {}  # {"hotspots": bool, "similarity": bool}
    unavailable = []
    if not cov.get("hotspots", True):
        unavailable += ["hotspot file risk", "bug echo"]
    if not cov.get("similarity", True):
        unavailable += ["similarity to past bugs"]
    if unavailable:
        total = len(RISK_WEIGHTS)
        notes.append(f"risk computed from {total - len(unavailable)} of {total} "
                     f"checks — unavailable: {', '.join(unavailable)} "
                     f"(run analyze on this repo for full coverage)")
    if notes:
        lines += ["", "### ℹ️ Notes"] + [f"- {m}" for m in notes]

    if summary:
        lines += ["", "### 📋 Change Summary (AI-generated)", summary]

    ok_msgs = list(risk["oks"])
    ok_msgs.append(f"diff similarity to past bugs: {similarity.get('max_score', 0.0)}")
    lines += ["", "### ✅ OK"] + [f"- {m}" for m in ok_msgs]

    markdown = "\n".join(lines)
    return {
        "level": level,
        "risk_score": score,
        "breakdown": [{"signal": k, "weight": w} for k, w in breakdown],
        "markdown": markdown,
        "warnings": warn_msgs,
        "notes": notes,
        "oks": ok_msgs,
        "similarity": similarity.get("max_score", 0.0),
        "files_changed": risk["files_changed"],
        "lines_added": risk["lines_added"],
        "summary": summary,
        "has_summary": bool(summary),
    }
