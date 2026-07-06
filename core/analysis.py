"""End-to-end Bug Hotspot analysis orchestration.

Wires the v0.1 pieces together:

    GitHub/git clone  ->  commit history (cached in MongoDB / JSON)
                      ->  bug-fix classification
                      ->  per-file feature extraction (+ size/complexity at HEAD)
                      ->  recency-weighted risk score
                      ->  plain-English explanations

Shared by the CLI and the scripts/ entry points.
"""
from __future__ import annotations

from datetime import datetime, timezone

from core.git_client import GitClient
from core.github_client import ensure_local_clone
from pipeline.classify_commits import classify_commits
from pipeline.extract_features import build_file_features
from pipeline.fetch_commits import fetch_and_store_commits
from tools.bug_hotspot.explainer import explain_all
from tools.bug_hotspot.ml_scorer import load_model
from tools.bug_hotspot.scorer import score_files


def run_hotspot_analysis(
    target: str,
    settings,
    store,
    *,
    refresh: bool = False,
    max_commits: int | None = None,
    top: int = 15,
    progress=None,
) -> dict:
    """Run the full pipeline for `target` and return a result dict.

    Returns:
        {
            "repo": str, "local_path": str | None,
            "commits": int, "bugfix_commits": int, "files_scored": int,
            "scores": [FileScore, ...]  # ranked, with reasons attached
        }
    """
    from core.progress import reporter_or_print

    report = reporter_or_print(progress)

    local_path = None
    try:
        # an explicit refresh also pulls the cached clone, so "refresh" truly
        # means "go back to GitHub", not "re-read the same stale history"
        local_path, key = ensure_local_clone(target, settings.cache_dir,
                                             update=refresh, progress=progress)
    except Exception as exc:
        # No local clone available — fall back to whatever is cached under the
        # derived key. Complexity metrics will be unavailable in this mode.
        from core.github_client import repo_key as _rk

        key = _rk(target)
        print(f"  [warn] {exc}; using cached data only for '{key}'")

    # 1. commit history (from cache unless refreshing / empty)
    commits = [] if refresh else store.load_commits(key)
    if not commits:
        if local_path is None:
            raise SystemExit(
                f"No cached commits for '{key}' and no local repo to pull from."
            )
        commits = fetch_and_store_commits(
            local_path, key, store,
            keywords=settings.bug_keywords, max_commits=max_commits,
            progress=progress,
        )
    else:
        # ensure classification flag is present (older caches / safety)
        classify_commits(commits, settings.bug_keywords)
        report("loading cached commits (database)",
               detail=f"{len(commits)} commits from {store.backend}")

    bugfix_commits = sum(1 for c in commits if c.get("is_bugfix"))

    # 2. size/complexity metrics for files still present at HEAD
    metrics_by_file: dict[str, dict] = {}
    existing_files = None
    if local_path is not None:
        gc = GitClient(local_path)
        existing_files = set(gc.head_files())
        touched = {f["path"] for c in commits for f in c.get("files", [])}
        report("computing file metrics (processing)",
               detail=f"{len(existing_files & touched)} files")
        metrics_by_file = gc.metrics_for(existing_files & touched)

    # 3. features
    report("scoring files (weighted formula)")
    features = build_file_features(
        commits,
        as_of=datetime.now(timezone.utc),
        churn_window_days=settings.churn_window_days,
        halflife_days=settings.hotspot_recency_halflife_days,
        metrics_by_file=metrics_by_file,
        existing_files=existing_files,
    )

    # 4. score + 5. explain
    scores = score_files(features)
    explain_all(scores, churn_window_days=settings.churn_window_days)

    # 6. optional XGBoost "second opinion" — only if a trained model exists
    ml_used = False
    model = load_model(settings.ml_model_path)
    if model is not None:
        try:
            report("scoring files (ML second opinion)")
            from tools.bug_hotspot.ml_scorer import predict_scores

            probs = predict_scores(model, features)
            for s in scores:
                s.ml_prob = probs.get(s.path)
            ml_used = True
        except Exception as exc:
            print(f"  [warn] ML second opinion skipped: {type(exc).__name__}: {exc}")

    # persist the report
    report("saving report (database)", pct=100)
    store.save_hotspots(key, [s.to_dict() for s in scores[: max(top, 50)]])

    return {
        "repo": key,
        "local_path": local_path,
        "commits": len(commits),
        "bugfix_commits": bugfix_commits,
        "files_scored": len(scores),
        "scores": scores,
        "ml_used": ml_used,
    }
