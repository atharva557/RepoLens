"""Temporal hold-out evaluation of the hotspot score (v0.5).

The question a grader (or a maintainer) should ask about Tool 1: *does the
ranking actually predict anything?* This answers it honestly:

  1. Pick several past cutoff dates (the same `choose_cutoffs` used by the
     ML dataset builder — no leakage by construction).
  2. Score every file exactly as the live scorer would have AT that cutoff
     (same extractor, same weights, features from commits <= cutoff only).
  3. The truth set is the files that actually received a *code* bug fix in
     the window after the cutoff (docs-only "fixes" are gated out, matching
     the scorer's own bug-credit rule).
  4. Report precision@k / recall@k, next to honest baselines: each single
     component alone, equal weights, and the random expectation. If the
     weighted formula doesn't beat its own ingredients, the weights are
     decoration — this is how we find out.

Only files already seen before the cutoff count as truth: a file born after
the cutoff is unpredictable by any history-based ranking, so including it
would punish every method equally and say nothing.

Pure stdlib; the runner at the bottom wires in git/store like core/analysis.
"""
from __future__ import annotations

from datetime import timedelta

from core.paths import is_code_file
from pipeline.extract_features import build_file_features
from tools.bug_hotspot.dataset import choose_cutoffs
from tools.bug_hotspot.scorer import DEFAULT_WEIGHTS, score_files

# ranking methods compared side by side. None = the live default weights.
WEIGHT_SETS: dict[str, dict[str, float] | None] = {
    "weighted": None,
    "equal weights": {"bug": 0.25, "churn": 0.25, "authors": 0.25, "complexity": 0.25},
    "bug history only": {"bug": 1.0, "churn": 0.0, "authors": 0.0, "complexity": 0.0},
    "churn only": {"bug": 0.0, "churn": 1.0, "authors": 0.0, "complexity": 0.0},
    "size only": {"bug": 0.0, "churn": 0.0, "authors": 0.0, "complexity": 1.0},
}

DEFAULT_KS = (5, 10, 20)


def evaluate_snapshot(commits: list[dict], cutoff, *, label_window_days: int = 90,
                      churn_window_days: int = 30, halflife_days: int = 30,
                      ks=DEFAULT_KS) -> dict | None:
    """Precision/recall@k for every ranking method at one cutoff.

    Returns None when the snapshot can't be evaluated (no history before the
    cutoff, or nothing bug-fixed after it — a metric over zero positives
    would be noise, not signal).
    """
    before = [c for c in commits if c["date"] <= cutoff]
    horizon = cutoff + timedelta(days=label_window_days)
    after = [c for c in commits if cutoff < c["date"] <= horizon]
    if not before or not after:
        return None

    existing = {f["path"] for c in before for f in c.get("files", [])}
    truth = {
        f["path"]
        for c in after if c.get("is_bugfix")
        for f in c.get("files", [])
        if is_code_file(f["path"]) and f["path"] in existing
    }
    if not truth:
        return None

    feats = build_file_features(
        before, as_of=cutoff,
        churn_window_days=churn_window_days, halflife_days=halflife_days,
        existing_files=existing,
    )
    if not feats:
        return None

    n = len(feats)
    methods: dict[str, dict] = {}
    for name, weights in WEIGHT_SETS.items():
        ranked = [s.path for s in score_files(feats, weights or DEFAULT_WEIGHTS)]
        m: dict[str, float] = {}
        for k in ks:
            hits = len(set(ranked[:k]) & truth)
            m[f"precision@{k}"] = round(hits / min(k, n), 3)
            m[f"recall@{k}"] = round(hits / len(truth), 3)
        methods[name] = m

    return {
        "cutoff": cutoff.date().isoformat(),
        "files_scored": n,
        "positives": len(truth),
        "base_rate": round(len(truth) / n, 4),  # random-ranking precision
        "methods": methods,
    }


def evaluate_repo(commits: list[dict], *, n_snapshots: int = 4,
                  label_window_days: int = 90, churn_window_days: int = 30,
                  halflife_days: int = 30, ks=DEFAULT_KS) -> dict:
    """Aggregate snapshot metrics into one honest per-repo report."""
    cutoffs = choose_cutoffs(
        commits, n_snapshots=n_snapshots, label_window_days=label_window_days
    )
    snapshots = []
    for cutoff in cutoffs:
        snap = evaluate_snapshot(
            commits, cutoff, label_window_days=label_window_days,
            churn_window_days=churn_window_days, halflife_days=halflife_days, ks=ks,
        )
        if snap:
            snapshots.append(snap)

    summary: dict[str, dict] = {}
    if snapshots:
        for name in WEIGHT_SETS:
            summary[name] = {
                metric: round(
                    sum(s["methods"][name][metric] for s in snapshots) / len(snapshots), 3
                )
                for metric in snapshots[0]["methods"][name]
            }

    total_pos = sum(s["positives"] for s in snapshots)
    return {
        "snapshots": snapshots,
        "summary": summary,
        "random_baseline": round(
            sum(s["base_rate"] for s in snapshots) / len(snapshots), 4
        ) if snapshots else None,
        "label_window_days": label_window_days,
        "usable_snapshots": len(snapshots),
        "total_positives": total_pos,
        # a handful of positives can't support conclusions — say so up front
        "reliable": len(snapshots) >= 2 and total_pos >= 10,
    }


def format_report(report: dict, repo_key: str, ks=DEFAULT_KS) -> str:
    """Plain-text table for the CLI (and log files)."""
    lines = [
        f"Hotspot evaluation - {repo_key} "
        f"({report['usable_snapshots']} snapshot(s), "
        f"{report['total_positives']} future bug-fixed files, "
        f"{report['label_window_days']}d label window)",
        "=" * 78,
    ]
    if not report["summary"]:
        lines.append("Not enough history to evaluate: need commits before a cutoff "
                     "AND code bug-fixes after it. Pull more history and retry.")
        return "\n".join(lines)

    header = f"{'method':<20}" + "".join(f"  P@{k:<4} R@{k:<4}" for k in ks)
    lines.append(header)
    lines.append("-" * len(header))
    for name, m in report["summary"].items():
        row = f"{name:<20}"
        for k in ks:
            row += f"  {m[f'precision@{k}']:<6.3f}{m[f'recall@{k}']:<6.3f}"
        lines.append(row)
    lines.append("-" * len(header))
    lines.append(f"random-ranking precision (base rate): {report['random_baseline']:.4f}")
    if not report["reliable"]:
        lines.append("NOTE: thin data (few snapshots/positives) - treat these "
                     "numbers as indicative, not conclusive.")
    return "\n".join(lines)


def run_hotspot_evaluation(target: str, settings, store, *,
                           max_commits: int | None = None) -> dict:
    """Clone/load history, evaluate, persist as a 'hotspot_eval' report."""
    from core.analysis import _clone_hint  # reuse the actionable error message
    from core.github_client import ensure_local_clone, repo_key as _rk
    from pipeline.classify_commits import classify_commits
    from pipeline.fetch_commits import fetch_and_store_commits

    local_path, clone_error = None, None
    try:
        local_path, key = ensure_local_clone(target, settings.cache_dir)
    except Exception as exc:
        clone_error, key = exc, _rk(target)

    commits = store.load_commits(key)
    if not commits:
        if local_path is None:
            raise SystemExit(
                f"Cannot evaluate '{key}': no cached commits and the repository "
                f"could not be opened.{_clone_hint(clone_error)}"
            )
        commits = fetch_and_store_commits(
            local_path, key, store,
            keywords=settings.bug_keywords, max_commits=max_commits,
        )
    else:
        classify_commits(commits, settings.bug_keywords)
        print(f"  evaluating over {len(commits)} cached commits ({store.backend})")

    report = evaluate_repo(
        commits,
        n_snapshots=getattr(settings, "ml_snapshots", 4),
        label_window_days=getattr(settings, "ml_label_window_days", 90),
        churn_window_days=settings.churn_window_days,
        halflife_days=settings.hotspot_recency_halflife_days,
    )
    report["repo"] = key
    report["commits"] = len(commits)
    store.save_report("hotspot_eval", key, report)
    print(format_report(report, key))
    return report
