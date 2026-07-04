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


def _hotspot_paths(store, key: str, settings, url: str) -> set[str]:
    hs = store.load_hotspots(key)
    if hs and hs.get("rows"):
        return {r.get("path") for r in hs["rows"][: settings.hotspot_top_n] if r.get("path")}
    # no cached hotspots -> compute them (also caches for next time)
    try:
        from core.analysis import run_hotspot_analysis

        res = run_hotspot_analysis(url, settings, store, top=settings.hotspot_top_n)
        return {s.path for s in res["scores"][: settings.hotspot_top_n]}
    except Exception as exc:
        print(f"  [warn] could not compute hotspots for file-risk: {exc}")
        return set()


def run_pr_review(spec: str, settings, store, *, post: bool = False) -> dict:
    if not settings.github_token:
        raise SystemExit("GITHUB_TOKEN required to review a PR. Set it in .env.")

    from core.github_client import GitHubAPI, ensure_local_clone

    owner, repo, number = parse_pr_spec(spec)
    key = f"{owner}/{repo}"
    url = f"https://github.com/{owner}/{repo}.git"

    print(f"  fetching PR {key}#{number} ...")
    api = GitHubAPI(settings.github_token)
    pr = api.get_pull(owner, repo, number)

    # similarity corpus from the repo's own bug-fix history
    index, corpus_n = None, 0
    try:
        from core.git_client import GitClient
        from pipeline.build_bug_index import build_bug_diff_index
        from pipeline.fetch_commits import fetch_and_store_commits

        local_path, _ = ensure_local_clone(url, settings.cache_dir)
        commits = store.load_commits(key) or fetch_and_store_commits(
            local_path, key, store, keywords=settings.bug_keywords)
        index, corpus_n = build_bug_diff_index(commits, GitClient(local_path), settings)
        print(f"  bug-diff corpus: {corpus_n} diffs [{index.backend}]")
    except Exception as exc:
        print(f"  [warn] similarity corpus unavailable: {exc}")

    hotspots = _hotspot_paths(store, key, settings, url)

    from core.llm import get_llm
    from tools.pr_reviewer.llm_summarizer import summarize
    from tools.pr_reviewer.report_builder import build_report
    from tools.pr_reviewer.risk_scorer import assess_risk
    from tools.pr_reviewer.similarity import assess_similarity

    risk = assess_risk(pr["files"], hotspots)
    sim = assess_similarity(index, pr, settings)
    summary = summarize(get_llm(settings), pr)
    report = build_report(pr, risk, sim, summary)
    report.update({"repo": key, "pr": number, "url": pr["url"], "corpus_size": corpus_n})

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
