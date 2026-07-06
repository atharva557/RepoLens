"""Mechanical risk checks for a pull request (Tool 3).

Everything here is deterministic and detectable without an LLM (guide §3.3):
file risk (hotspot membership, source files only), recently-bug-fixed files
("bug echo"), missing tests, unfocused change, large change, PR description
quality (reusing Tool 4's message scorer), and a hotspot-blind-spot note for
large brand-new files. Pure stdlib.
"""
from __future__ import annotations

from core.paths import is_source_file, is_test_file
from tools.commit_quality.scorer import score_message


def assess_risk(pr_files: list[dict], hotspot_paths: set[str], *,
                recently_fixed: dict[str, float] | None = None,
                title: str = "", body: str = "",
                large_added: int = 400, many_files: int = 12,
                many_areas: int = 4, new_file_lines: int = 150) -> dict:
    changed = [f["path"] for f in pr_files]
    tests_changed = [p for p in changed if is_test_file(p)]
    source_changed = [p for p in changed if is_source_file(p)]
    # Hotspot membership only counts for real source files. The hotspot list
    # legitimately contains churn-heavy docs/tests (CHANGES.rst, big test
    # files), but a PR touching those is not "editing risky code" — counting
    # them made nearly every real-world PR come out HIGH.
    risky = [p for p in changed
             if p in (hotspot_paths or set()) and is_source_file(p)]
    top_dirs = {p.split("/")[0] for p in changed if "/" in p}
    lines_added = sum(int(f.get("additions", 0)) for f in pr_files)

    warnings: list[tuple[str, str]] = []
    oks: list[str] = []
    notes: list[str] = []

    if risky:
        shown = ", ".join(risky[:3]) + ("..." if len(risky) > 3 else "")
        warnings.append(("file_risk", f"touches high-risk file(s): {shown}"))

    # "bug echo": a source file whose *latest* change was a recent bug fix —
    # fixes attract follow-up fixes, so fresh-from-a-fix files deserve care
    echoes = [(p, recently_fixed[p]) for p in source_changed
              if p in (recently_fixed or {})]
    if echoes:
        shown = ", ".join(f"{p} (fixed {d:.0f}d ago)" for p, d in echoes[:3])
        warnings.append(("bug_echo", f"recently bug-fixed file(s) touched: {shown}"))

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

    # PR description quality — Tool 4's scorer on "title\n\nbody"
    if not (body or "").strip():
        warnings.append(("weak_description", "PR has no description"))
    else:
        desc = score_message(f"{title}\n\n{body}".strip())
        if desc["score"] < 4:
            issues = "; ".join(desc["issues"][:2])
            warnings.append(("weak_description",
                             f"weak PR description ({desc['score']}/10: {issues})"))
        else:
            oks.append(f"PR description present ({desc['score']}/10)")

    # hotspot analysis is history-based, so brand-new large files are a blind
    # spot — say so instead of letting them read as implicitly safe
    fresh = [f["path"] for f in pr_files
             if f.get("status") == "added" and is_source_file(f["path"])
             and int(f.get("additions", 0)) >= new_file_lines]
    if fresh:
        shown = ", ".join(fresh[:3]) + ("..." if len(fresh) > 3 else "")
        notes.append(f"{len(fresh)} large new file(s) have no history — "
                     f"hotspot analysis cannot assess them: {shown}")

    return {
        "warnings": warnings,
        "oks": oks,
        "notes": notes,
        "risky_files": risky,
        "bug_echo_files": [p for p, _ in echoes],
        "source_changed": source_changed,
        "tests_changed": tests_changed,
        "files_changed": len(changed),
        "lines_added": lines_added,
    }
