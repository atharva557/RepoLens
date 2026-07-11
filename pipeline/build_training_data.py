"""Build a pooled, multi-repo training set and train the XGBoost second opinion.

Reads a repo list (default `train_repos.txt`), pulls each repo's history, builds
temporal-snapshot labeled rows, pools them, and trains. Designed to mix several
repos across several languages so the model learns language-agnostic signal.
"""
from __future__ import annotations

import os

from core.git_client import GitClient
from core.github_client import ensure_local_clone
from pipeline.classify_commits import classify_commits
from tools.bug_hotspot.dataset import dataset_summary, make_dataset


def parse_repo_list(path: str) -> list[tuple[str, str | None]]:
    """Parse `train_repos.txt`. Each non-comment line: <repo>[,<language>]."""
    entries: list[tuple[str, str | None]] = []
    if not os.path.isfile(path):
        return entries
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            repo, _, lang = line.partition(",")
            entries.append((repo.strip(), lang.strip().lower() or None))
    return entries


def build_dataset(entries, settings, *, max_commits: int | None = None) -> list[dict]:
    """Clone/read each repo, classify commits, and accumulate snapshot rows."""
    rows: list[dict] = []
    for target, language in entries:
        try:
            local_path, key = ensure_local_clone(target, settings.cache_dir)
        except Exception as exc:
            print(f"  [skip] {target}: {type(exc).__name__}: {exc}")
            continue
        gc = GitClient(local_path)
        commits = list(gc.iter_commits(max_count=max_commits))
        classify_commits(commits, settings.bug_keywords)
        repo_rows = make_dataset(
            commits, key,
            language=language,
            n_snapshots=settings.ml_snapshots,
            label_window_days=settings.ml_label_window_days,
            churn_window_days=settings.churn_window_days,
            halflife_days=settings.hotspot_recency_halflife_days,
        )
        pos = sum(r["label"] for r in repo_rows)
        print(f"  {key} [{language or 'unknown'}]: {len(commits)} commits "
              f"-> {len(repo_rows)} rows ({pos} positive)")
        rows.extend(repo_rows)
    return rows


def train_from_list(settings, repo_list_path: str = "train_repos.txt",
                    max_commits: int | None = None) -> dict:
    """Full training run. Returns a report dict (and writes the model file)."""
    from tools.bug_hotspot.ml_scorer import (
        NotEnoughData,
        evaluate_by_language,
        save_model,
        train,
    )

    entries = parse_repo_list(repo_list_path)
    if not entries:
        raise SystemExit(
            f"No repos listed in '{repo_list_path}'. Add one repo per line "
            f"(e.g. 'https://github.com/pallets/flask,python')."
        )

    print(f"Building training set from {len(entries)} repo(s)...")
    rows = build_dataset(entries, settings, max_commits=max_commits)
    summary = dataset_summary(rows)
    print(f"\nDataset: {summary}")

    try:
        model, report = train(rows, min_positives=settings.ml_min_positives)
    except NotEnoughData as exc:
        raise SystemExit(f"Cannot train: {exc}")

    report["by_language_auc"] = evaluate_by_language(rows)
    save_model(model, settings.ml_model_path)
    report["model_path"] = settings.ml_model_path
    return report
