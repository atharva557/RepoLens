"""Lightweight phase/percent progress reporting for long-running jobs.

A progress reporter is just a callable:

    report(phase, pct=None, detail="")

- `phase`  : human-readable stage, worded so users can tell *where* time goes
             ("cloning repository (GitHub)" vs "scoring files (ML)").
- `pct`    : 0-100 when the stage has a measurable total, None = indeterminate.
- `detail` : small free-text addendum (repo name, commit count, ...).

The engine's long operations accept `progress=None` and fall back to
`print_progress`, so the CLI shows the same phases the API records. The API
passes `JobRegistry.reporter(job_id)` instead, which stores the latest phase
on the job — `GET /jobs/{id}` then exposes it and the dashboard renders a
progress bar. Pure stdlib.
"""
from __future__ import annotations


def print_progress(phase: str, pct: int | None = None, detail: str = "") -> None:
    """Default CLI sink: one line per phase update."""
    bar = f"{pct:3d}%" if pct is not None else "...."
    tail = f" - {detail}" if detail else ""
    print(f"  [{bar}] {phase}{tail}")


def reporter_or_print(progress):
    """Normalize an optional progress callback to something always callable."""
    return progress if progress is not None else print_progress
