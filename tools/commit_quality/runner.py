"""End-to-end Commit Message Quality analysis (Tool 4).

Wires the v0.1 commit pipeline -> rule-based scoring -> aggregation, and
optionally adds LLM rewrites for the worst messages. Shared by the CLI.
"""
from __future__ import annotations

from core.github_client import ensure_local_clone, repo_key as _repo_key
from pipeline.fetch_commits import fetch_and_store_commits
from tools.commit_quality.reporter import build_report
from tools.commit_quality.suggester import suggest as suggest_message


def run_commit_quality_report(target: str, settings, store, *,
                              max_commits: int | None = None,
                              suggest_count: int | None = None,
                              suggest: bool = False, top: int = 15,
                              progress=None) -> dict:
    from core.progress import reporter_or_print

    report_progress = reporter_or_print(progress)
    local_path = None
    try:
        local_path, key = ensure_local_clone(target, settings.cache_dir,
                                             progress=progress)
    except Exception as exc:
        key = _repo_key(target)
        print(f"  [warn] {exc}; using cached data only for '{key}'")

    commits = store.load_commits(key)
    if not commits:
        if local_path is None:
            raise SystemExit(f"No cached commits for '{key}' and no local repo to pull.")
        commits = fetch_and_store_commits(
            local_path, key, store,
            keywords=settings.bug_keywords, max_commits=max_commits,
            progress=progress,
        )
    else:
        report_progress("loading cached commits (database)",
                        detail=f"{len(commits)} commits from {store.backend}")

    report_progress("scoring commit messages (processing)",
                    detail=f"{len(commits)} messages")
    report = build_report(commits)
    report["repo"] = key

    # optional LLM rewrites for the worst N messages
    if suggest:
        from core.git_client import GitClient
        from core.llm import get_llm

        llm = get_llm(settings)
        if not llm.available():
            print(f"  [warn] LLM ({llm.describe()}) unavailable - skipping rewrites")
        elif local_path is None:
            print("  [warn] no local clone - cannot read diffs for rewrites")
        else:
            print(f"  generating rewrites via {llm.describe()} ...")
            gc = GitClient(local_path)
            n = suggest_count or top
            for i, row in enumerate(report["worst"][:n]):
                report_progress("rewriting worst messages (LLM)",
                                pct=int(i * 100 / max(n, 1)),
                                detail=f"{i + 1}/{n}")
                diff = gc.commit_diff(row["sha"])
                full = next((c.get("message", "") for c in commits
                             if c.get("sha", "").startswith(row["sha"])), row["subject"])
                row["suggestion"] = suggest_message(llm, full, diff)
            report["suggested"] = True

    report_progress("saving report (database)", pct=100)
    store.save_report("commit_quality", key, _slim(report, top))
    return report


def _slim(report: dict, top: int) -> dict:
    """Persist a bounded version (don't store every commit)."""
    out = dict(report)
    out["worst"] = report["worst"][: max(top, 50)]
    out.pop("scored", None)
    return out
