"""Recency-weighted bug-hotspot risk scorer (Tool 1).

This *replaces* the trained XGBoost classifier from the original design. As
argued in GitPulse_Revised_Sections.md ("What changed and why", #2), training a
classifier on a single repo's history suffers from tiny/imbalanced data and
label leakage. A transparent weighted score needs no training, works on small
repos, and is fully explainable — honouring the project's "explainability over
black-box accuracy" principle.

The final risk score is a weighted sum of four per-repo normalized components:

    score = w_bug*bug + w_churn*churn + w_authors*authors + w_complexity*complexity

Each component is min-max normalized to [0, 1] across all files in the repo, so
the score is a *relative* ranking within a repository (which is exactly what a
hotspot list is).

Pure stdlib — no third-party dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Component weights. Bug history is the strongest signal in the defect-prediction
# literature, followed by churn; size/complexity and author spread refine it.
DEFAULT_WEIGHTS: dict[str, float] = {
    "bug": 0.40,
    "churn": 0.25,
    "authors": 0.15,
    "complexity": 0.20,
}

# raw feature key backing each normalized component
_COMPONENT_SOURCE = {
    "bug": "bug_score",
    "churn": "churn_window",
    "authors": "authors",
    "complexity": "loc",
}


@dataclass
class FileScore:
    path: str
    score: float
    components: dict[str, float]  # normalized 0..1 contributions
    raw: dict                     # the underlying feature row
    reasons: list[str] = field(default_factory=list)
    ml_prob: float | None = None  # XGBoost "second opinion" probability, if available

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "score": self.score,
            "components": self.components,
            "raw": self.raw,
            "reasons": self.reasons,
            "ml_prob": self.ml_prob,
        }


def score_files(
    features: list[dict],
    weights: dict[str, float] | None = None,
) -> list[FileScore]:
    """Score and rank file feature rows, highest risk first."""
    weights = weights or DEFAULT_WEIGHTS
    if not features:
        return []

    maxes = {
        comp: max((float(f.get(src) or 0) for f in features), default=0.0) or 1.0
        for comp, src in _COMPONENT_SOURCE.items()
    }

    results: list[FileScore] = []
    for f in features:
        comp = {
            c: (float(f.get(src) or 0) / maxes[c])
            for c, src in _COMPONENT_SOURCE.items()
        }
        score = sum(weights.get(c, 0.0) * v for c, v in comp.items())
        results.append(
            FileScore(
                path=f["path"],
                score=round(score, 4),
                components={c: round(v, 4) for c, v in comp.items()},
                raw=f,
            )
        )

    results.sort(key=lambda r: (r.score, r.raw.get("bug_score", 0)), reverse=True)
    return results
