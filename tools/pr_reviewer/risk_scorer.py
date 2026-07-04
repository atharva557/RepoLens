"""Mechanical risk checks for a pull request (Tool 3).

Everything here is deterministic and detectable without an LLM (guide §3.3):
file risk (hotspot membership), missing tests, unfocused change, large change.
Pure stdlib — takes the PR's changed files and the repo's hotspot paths.
"""
from __future__ import annotations

from core.paths import is_source_file, is_test_file


def assess_risk(pr_files: list[dict], hotspot_paths: set[str], *,
                large_added: int = 400, many_files: int = 12,
                many_areas: int = 4) -> dict:
    changed = [f["path"] for f in pr_files]
    tests_changed = [p for p in changed if is_test_file(p)]
    source_changed = [p for p in changed if is_source_file(p)]
    risky = [p for p in changed if p in (hotspot_paths or set())]
    top_dirs = {p.split("/")[0] for p in changed if "/" in p}
    lines_added = sum(int(f.get("additions", 0)) for f in pr_files)

    warnings: list[tuple[str, str]] = []
    oks: list[str] = []

    if risky:
        shown = ", ".join(risky[:3]) + ("..." if len(risky) > 3 else "")
        warnings.append(("file_risk", f"touches high-risk file(s): {shown}"))

    if source_changed and not tests_changed:
        warnings.append(("missing_tests",
                         f"{len(source_changed)} source file(s) changed, but no tests"))
    elif tests_changed:
        oks.append(f"tests updated ({len(tests_changed)} file(s))")

    if len(changed) > many_files and len(top_dirs) >= many_areas:
        warnings.append(("unfocused",
                         f"{len(changed)} files across {len(top_dirs)} areas (broad change)"))
    elif len(changed) <= 6:
        oks.append(f"focused change ({len(changed)} files)")

    if lines_added > large_added:
        warnings.append(("large_change", f"large diff (+{lines_added} lines)"))

    return {
        "warnings": warnings,
        "oks": oks,
        "risky_files": risky,
        "source_changed": source_changed,
        "tests_changed": tests_changed,
        "files_changed": len(changed),
        "lines_added": lines_added,
    }
