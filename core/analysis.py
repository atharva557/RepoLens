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


def _clone_hint(exc: Exception | None) -> str:
    """Explain *why* the repository could not be opened, actionably.

    The common cause is an interpreter that lacks GitPython — the server then
    starts happily (FastAPI is installed), serves already-cached repos, and
    fails only on new ones, which is a maddening way to learn about it.
    """
    if exc is None:
        return ""
    if isinstance(exc, ModuleNotFoundError) and getattr(exc, "name", "") == "git":
        import sys as _sys

        return (" GitPython is not installed in the interpreter running this "
                f"server ({_sys.executable}) - install it with "
                f"'{_sys.executable} -m pip install GitPython', or start the "
                "server with the interpreter that has the project's requirements.")
    return f" Reason: {type(exc).__name__}: {exc}"


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
    clone_error: Exception | None = None
    try:
        # an explicit refresh also pulls the cached clone, so "refresh" truly
        # means "go back to GitHub", not "re-read the same stale history"
        local_path, key = ensure_local_clone(target, settings.cache_dir,
                                             update=refresh, progress=progress)
    except Exception as exc:
        # No local clone available — fall back to whatever is cached under the
        # derived key. Complexity metrics will be unavailable in this mode.
        from core.github_client import repo_key as _rk

        clone_error = exc
        key = _rk(target)
        print(f"  [warn] {exc}; using cached data only for '{key}'")

    # 1. commit history (from cache unless refreshing / empty)
    commits = [] if refresh else store.load_commits(key)
    if not commits:
        if local_path is None:
            # Carry the real reason. Swallowing it here turned "GitPython isn't
            # installed" / "clone failed" into a baffling "no cached commits",
            # which is only ever hit on a repo we have never analyzed.
            raise SystemExit(
                f"Cannot analyze '{key}': it has no cached commits and the "
                f"repository could not be opened.{_clone_hint(clone_error)}"
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

    # 7. an explicit refresh means "go back to GitHub" for everything about
    # this repo, not just its commits — otherwise the dashboard header keeps
    # showing the stars/forks/description captured on the very first analysis.
    # Best-effort: metadata needs a token, and a public repo analyzes fine
    # without one.
    if refresh and "/" in key and settings.github_token:
        try:
            from core.github_client import get_recent_pulls, get_repo_meta

            report("refreshing repo metadata (GitHub)")
            get_repo_meta(key, settings, store, refresh=True)
            get_recent_pulls(key, settings, store, refresh=True)
        except Exception as exc:
            print(f"  [warn] repo metadata refresh skipped: {type(exc).__name__}: {exc}")

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
