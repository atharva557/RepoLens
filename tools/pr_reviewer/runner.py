"""End-to-end PR Review Assistant (Tool 3).

For `owner/repo#number`:
  1. fetch the PR (GitHub API)
  2. build the bug-fix similarity corpus from the repo's history (local clone)
  3. gather Tool 1 hotspot scores for file risk
  4. run mechanical risk checks + diff similarity + LLM summary
  5. assemble the report; optionally post it as a PR comment.
"""
from __future__ import annotations

import re


def parse_pr_spec(spec: str) -> tuple[str, str, int]:
    spec = spec.strip()
    m = re.search(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)", spec)
    if m:
        return m.group(1), m.group(2), int(m.group(3))
    m = re.match(r"^([^/\s]+)/([^/#\s]+)[#/](\d+)$", spec)
    if m:
        return m.group(1), m.group(2), int(m.group(3))
    raise SystemExit("PR must be 'owner/repo#123' or a full pull-request URL.")


def _hotspot_context(store, key: str, settings, url: str) -> tuple[set[str], dict[str, float]]:
    """(top-N hotspot paths, {path: days} for recently-bug-fixed files).

    The recently-fixed map ("bug echo") reads the per-file features already
    stored on hotspot rows: files whose latest change was a bug fix within
    the churn window. Empty results mean the checks are skipped and the
    report says so (coverage note)."""
    hs = store.load_hotspots(key)
    rows = (hs or {}).get("rows") or []
    if not rows:
        try:  # no cached hotspots -> compute them (also caches for next time)
            from core.analysis import run_hotspot_analysis

            res = run_hotspot_analysis(url, settings, store, top=settings.hotspot_top_n)
            rows = [s.to_dict() for s in res["scores"]]
        except Exception as exc:
            print(f"  [warn] could not compute hotspots for file-risk: {exc}")
            return set(), {}
    top = {r.get("path") for r in rows[: settings.hotspot_top_n] if r.get("path")}
    recent = {}
    for r in rows:
        raw = r.get("raw") or {}
        days = raw.get("last_change_days")
        if raw.get("last_was_bugfix") and days is not None \
                and days <= settings.churn_window_days:
            recent[r["path"]] = float(days)
    return top, recent


def run_pr_review(spec: str, settings, store, *, post: bool = False,
                  progress=None) -> dict:
    if not settings.github_token:
        raise SystemExit("GITHUB_TOKEN required to review a PR. Set it in .env.")

    from core.github_client import GitHubAPI, ensure_local_clone
    from core.progress import reporter_or_print

    report_progress = reporter_or_print(progress)
    owner, repo, number = parse_pr_spec(spec)
    key = f"{owner}/{repo}"
    url = f"https://github.com/{owner}/{repo}.git"

    report_progress("fetching PR (GitHub)", detail=f"{key}#{number}")
    api = GitHubAPI(settings.github_token)
    pr = api.get_pull(owner, repo, number)

    # similarity corpus from the repo's own bug-fix history
    index, corpus_n = None, 0
    try:
        from core.git_client import GitClient
        from pipeline.build_bug_index import build_bug_diff_index
        from pipeline.fetch_commits import fetch_and_store_commits

        local_path, _ = ensure_local_clone(url, settings.cache_dir, progress=progress)
        commits = store.load_commits(key) or fetch_and_store_commits(
            local_path, key, store, keywords=settings.bug_keywords, progress=progress)
        report_progress("embedding bug-fix diffs (ML)",
                        detail=f"{sum(1 for c in commits if c.get('is_bugfix'))} diffs")
        index, corpus_n = build_bug_diff_index(commits, GitClient(local_path), settings,
                                               repo_key=key)
        print(f"  bug-diff corpus: {corpus_n} diffs [{index.backend}]")
    except Exception as exc:
        print(f"  [warn] similarity corpus unavailable: {exc}")

    report_progress("checking hotspot file risk (processing)")
    hotspots, recently_fixed = _hotspot_context(store, key, settings, url)

    from core.llm import get_llm
    from tools.pr_reviewer.llm_summarizer import summarize
    from tools.pr_reviewer.report_builder import build_report
    from tools.pr_reviewer.risk_scorer import assess_risk
    from tools.pr_reviewer.similarity import assess_similarity

    report_progress("risk checks + diff similarity (processing)")
    risk = assess_risk(pr["files"], hotspots,
                       recently_fixed=recently_fixed,
                       title=pr.get("title", ""), body=pr.get("body", ""))
    sim = assess_similarity(index, pr, settings)

    def _assemble(summary: str | None) -> dict:
        r = build_report(pr, risk, sim, summary,
                         coverage={"hotspots": bool(hotspots or recently_fixed),
                                   "similarity": corpus_n > 0},
                         high=getattr(settings, "pr_risk_high", 0.5),
                         medium=getattr(settings, "pr_risk_medium", 0.2))
        r.update({"repo": key, "pr": number, "url": pr["url"], "corpus_size": corpus_n})
        return r

    # The deterministic report is saved *before* the LLM phase so readers
    # (dashboard, GET .../pr-reviews/{n}) can render risk/warnings while the
    # summary generates; summary_pending tells them a second save is coming.
    llm = get_llm(settings)
    report = _assemble(None)
    if llm is not None and llm.available():
        report["summary_pending"] = True
        report_progress("saving preliminary report (database)")
        store.save_report("pr_review", f"{key}#{number}", report)
        report_progress("summarizing the diff (LLM)")
        report = _assemble(summarize(llm, pr))
    report["summary_pending"] = False
    report_progress("saving report (database)", pct=100)
    store.save_report("pr_review", f"{key}#{number}", report)

    if post:
        from tools.pr_reviewer.github_commenter import post_comment

        try:
            comment_url = post_comment(api, pr, report["markdown"])
            report["posted"] = comment_url
            print(f"  posted comment: {comment_url}")
        except Exception as exc:
            print(f"  [warn] failed to post comment: {exc}")

    return report
