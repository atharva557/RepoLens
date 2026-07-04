"""Assemble the PR pre-review report (Tool 3).

Produces the markdown that matches the guide's §3.3 example (Risk level,
Warnings, AI summary, OK) plus a structured dict for storage. Pure stdlib.
"""
from __future__ import annotations


def _risk_level(risk: dict, similarity: dict) -> str:
    if risk["risky_files"] or similarity.get("warn"):
        return "HIGH"
    if risk["warnings"]:
        return "MEDIUM"
    return "LOW"


def build_report(pr: dict, risk: dict, similarity: dict, summary: str | None) -> dict:
    level = _risk_level(risk, similarity)
    lines: list[str] = ["## 🤖 RepoLens Pre-Review Report", "",
                        f"**Risk Level: {level}**"]

    warn_msgs = [msg for _, msg in risk["warnings"]]
    if similarity.get("warn") and similarity.get("matches"):
        top = similarity["matches"][0]
        warn_msgs.append(
            f"diff resembles a past bug-fix "
            f"({top['meta'].get('sha', top['id'])}, similarity {similarity['max_score']})"
        )
    if warn_msgs:
        lines += ["", "### ⚠️ Warnings"] + [f"- {m}" for m in warn_msgs]

    if summary:
        lines += ["", "### 📋 Change Summary (AI-generated)", summary]

    ok_msgs = list(risk["oks"])
    ok_msgs.append(f"diff similarity to past bugs: {similarity.get('max_score', 0.0)}")
    lines += ["", "### ✅ OK"] + [f"- {m}" for m in ok_msgs]

    markdown = "\n".join(lines)
    return {
        "level": level,
        "markdown": markdown,
        "warnings": warn_msgs,
        "oks": ok_msgs,
        "similarity": similarity.get("max_score", 0.0),
        "files_changed": risk["files_changed"],
        "lines_added": risk["lines_added"],
        "has_summary": bool(summary),
    }
