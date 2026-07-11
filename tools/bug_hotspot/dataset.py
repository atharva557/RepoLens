"""Temporal-snapshot dataset builder for the XGBoost "second opinion".

This is what makes a *trained* model legitimate here. The original XGBoost design
was cut for two reasons (see GitPulse_Revised_Sections.md): label leakage and tiny
data. Temporal labeling fixes the leakage; multiple snapshots across multiple repos
fixes the data volume.

For each repo we pick several **cutoff dates**. At each cutoff:
  - FEATURES are computed only from commits *before* the cutoff (the repo as it
    looked then) — reusing the exact same extractor as the live scorer.
  - The LABEL is whether the file received a bug-fix commit in the window
    *after* the cutoff (cutoff, cutoff + label_window].

Because the label (future bugs) comes from different commits than the features
(past activity), there is no leakage between them.

Pure stdlib.
"""
from __future__ import annotations

from datetime import timedelta

from pipeline.extract_features import build_file_features


def _date_range(commits):
    dates = [c["date"] for c in commits]
    return (min(dates), max(dates)) if dates else (None, None)


def choose_cutoffs(commits, *, n_snapshots: int, label_window_days: int):
    """Pick up to `n_snapshots` cutoff dates that leave room for a label window.

    Cutoffs are spread over the middle/late history: early enough to have feature
    history before them, late enough to still have a full label window after.
    """
    t_min, t_max = _date_range(commits)
    if t_min is None:
        return []
    latest_cutoff = t_max - timedelta(days=label_window_days)
    earliest_cutoff = t_min + 0.3 * (t_max - t_min)
    if latest_cutoff <= earliest_cutoff:
        return []
    if n_snapshots <= 1:
        return [latest_cutoff]
    span = (latest_cutoff - earliest_cutoff).total_seconds()
    return [
        earliest_cutoff + timedelta(seconds=span * i / (n_snapshots - 1))
        for i in range(n_snapshots)
    ]


def make_dataset(
    commits: list[dict],
    repo_key: str,
    *,
    language: str | None = None,
    n_snapshots: int = 4,
    label_window_days: int = 90,
    churn_window_days: int = 30,
    halflife_days: int = 30,
) -> list[dict]:
    """Build labeled training rows for one repo via temporal snapshots."""
    rows: list[dict] = []
    cutoffs = choose_cutoffs(
        commits, n_snapshots=n_snapshots, label_window_days=label_window_days
    )
    for cutoff in cutoffs:
        before = [c for c in commits if c["date"] <= cutoff]
        after = [
            c for c in commits
            if cutoff < c["date"] <= cutoff + timedelta(days=label_window_days)
        ]
        if not before:
            continue

        # files that existed (were touched) by the cutoff
        existing = {f["path"] for c in before for f in c.get("files", [])}
        # files that received a bug fix in the label window -> positive label
        buggy_future = {
            f["path"]
            for c in after if c.get("is_bugfix")
            for f in c.get("files", [])
        }

        feats = build_file_features(
            before,
            as_of=cutoff,
            churn_window_days=churn_window_days,
            halflife_days=halflife_days,
            existing_files=existing,
        )
        snapshot_id = f"{repo_key}@{cutoff.date().isoformat()}"
        for row in feats:
            row["repo"] = repo_key
            row["language"] = language or "unknown"
            row["snapshot_id"] = snapshot_id
            row["label"] = 1 if row["path"] in buggy_future else 0
            rows.append(row)
    return rows


def dataset_summary(rows: list[dict]) -> dict:
    pos = sum(r["label"] for r in rows)
    repos = {r["repo"] for r in rows}
    langs = {r["language"] for r in rows}
    snaps = {r["snapshot_id"] for r in rows}
    return {
        "rows": len(rows),
        "positives": pos,
        "negatives": len(rows) - pos,
        "repos": len(repos),
        "languages": sorted(langs),
        "snapshots": len(snaps),
    }
