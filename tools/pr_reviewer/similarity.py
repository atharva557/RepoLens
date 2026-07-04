"""Compare a PR diff against the corpus of past bug-fix diffs (Tool 3).

High cosine similarity to a diff that previously introduced/fixed a bug is a
warning sign. Backed by whichever SimilarityIndex is active (Chroma or Lite).
"""
from __future__ import annotations


def assess_similarity(index, pr: dict, settings) -> dict:
    if index is None:
        return {"max_score": 0.0, "matches": [], "warn": False}
    diff_text = "\n".join(f.get("patch", "") for f in pr.get("files", []))[:8000]
    if not diff_text.strip():
        return {"max_score": 0.0, "matches": [], "warn": False}
    matches = index.query(diff_text, k=settings.pr_similarity_top_k)
    max_score = matches[0]["score"] if matches else 0.0
    return {
        "max_score": max_score,
        "matches": matches,
        "warn": max_score >= settings.pr_similarity_warn,
    }
