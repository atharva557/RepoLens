"""GitPulse v0.1 interactive command-line interface.

Run it with no arguments and answer the prompts:

    python cli.py

A menu lets you analyze a repo's bug hotspots, pull/cache commit history,
create MongoDB indexes, or view the resolved settings. `<repo>` is a local git
repository path or a remote URL (cloned once).
"""
from __future__ import annotations

import os
import sys

# make sibling packages importable no matter where this is run from
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import Settings  # noqa: E402
from core.db import open_store  # noqa: E402


def open_store_announced(settings):
    """Open the store and always say which backend is serving this run —
    the primary (MongoDB), a configured choice, or the JSON fallback."""
    store = open_store(settings)
    if store.backend == "mongo":
        print("  [backend] store: mongodb (primary)")
    elif settings.store_backend == "json":
        print("  [backend] store: json files (selected in config)")
    else:
        print(f"  [backend] store: json files at {settings.cache_dir} "
              f"(FALLBACK — MongoDB unavailable)")
    return store


# --------------------------------------------------------------------------- #
# input() helpers
# --------------------------------------------------------------------------- #
def prompt(label: str, default: str | None = None, required: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        val = input(f"{label}{suffix}: ").strip()
        if val:
            return val
        if default is not None:
            return default
        if not required:
            return ""
        print("  this value is required.")


def prompt_int(label: str, default: int) -> int:
    while True:
        val = input(f"{label} [{default}]: ").strip()
        if not val:
            return default
        try:
            return int(val)
        except ValueError:
            print("  please enter a whole number.")


def prompt_bool(label: str, default: bool = False) -> bool:
    hint = "Y/n" if default else "y/N"
    val = input(f"{label} [{hint}]: ").strip().lower()
    if not val:
        return default
    return val in ("y", "yes", "true", "1")


# --------------------------------------------------------------------------- #
# output
# --------------------------------------------------------------------------- #
def _print_table(result: dict, top: int) -> None:
    scores = result["scores"][:top]
    ml = result.get("ml_used")
    print()
    print(
        f"Bug Hotspots - {result['repo']}  "
        f"({result['commits']} commits, {result['bugfix_commits']} bug-fix, "
        f"{result['files_scored']} files scored"
        f"{'; XGBoost second opinion ON' if ml else ''})"
    )
    print("=" * 100)
    if not scores:
        print("  (no files to score - is this a non-empty git repository?)")
        return

    if ml:
        rank_w, file_w = 4, 38
        print(f"{'#':<{rank_w}} {'File':<{file_w}} {'Wtd':<6} {'ML':<6} Top reasons")
        print("-" * 100)
        for i, fs in enumerate(scores, 1):
            path = fs.path
            if len(path) > file_w - 1:
                path = "..." + path[-(file_w - 4):]
            mlp = f"{fs.ml_prob:.2f}" if fs.ml_prob is not None else "  -"
            reasons = "; ".join(fs.reasons[:2])
            print(f"{i:<{rank_w}} {path:<{file_w}} {fs.score:<6.3f} {mlp:<6} {reasons}")
        _print_disagreements(scores)
    else:
        rank_w, file_w, score_w = 4, 44, 6
        print(f"{'#':<{rank_w}} {'File':<{file_w}} {'Score':<{score_w}} Top reasons")
        print("-" * 100)
        for i, fs in enumerate(scores, 1):
            path = fs.path
            if len(path) > file_w - 1:
                path = "..." + path[-(file_w - 4):]
            reasons = "; ".join(fs.reasons)
            print(f"{i:<{rank_w}} {path:<{file_w}} {fs.score:<{score_w}.3f} {reasons}")
    print()


def _print_disagreements(scores) -> None:
    """Highlight where the formula and the ML model disagree - the useful signal."""
    rows = []
    for fs in scores:
        if fs.ml_prob is None:
            continue
        if fs.score >= 0.6 and fs.ml_prob < 0.3:
            rows.append(f"  - {fs.path}: formula HIGH ({fs.score:.2f}) but ML LOW ({fs.ml_prob:.2f})")
        elif fs.score < 0.3 and fs.ml_prob >= 0.6:
            rows.append(f"  - {fs.path}: formula LOW ({fs.score:.2f}) but ML HIGH ({fs.ml_prob:.2f})")
    if rows:
        print("-" * 100)
        print("Disagreements (worth a look):")
        print("\n".join(rows))


def _print_commit_quality(report: dict, top: int) -> None:
    print()
    print(f"Commit Message Quality - {report.get('repo', '?')}  "
          f"({report['commits']} commits, avg {report['avg_score']}/10; "
          f"{report['good']} good, {report['weak']} weak)")
    print("=" * 100)

    if report.get("common_issues"):
        print("Most common issues:")
        for issue, count in report["common_issues"]:
            print(f"  - {issue} ({count})")
        print()

    contribs = report.get("contributors", [])
    if contribs:
        print("Per-contributor health (lowest first):")
        for c in contribs[:8]:
            print(f"  {c['author'][:28]:<28} {c['commits']:>4} commits   avg {c['avg_score']}/10")
        print()

    print(f"Weakest messages (showing {min(top, len(report['worst']))}):")
    print("-" * 100)
    for i, row in enumerate(report["worst"][:top], 1):
        print(f"{i:<3} [{row['score']}/10] {row['sha']}  {row['subject'][:70]}")
        if row.get("issues"):
            print(f"      issues: {', '.join(row['issues'])}")
        if row.get("suggestion"):
            indented = row["suggestion"].replace("\n", "\n      ")
            print(f"      suggested:\n      {indented}")
    print()


def _print_profile(profile) -> None:
    if not profile:
        print("  (no profile produced)\n")
        return
    print()
    print(f"Developer Profile: @{profile['username']}")
    print("=" * 60)
    print(f"  Primary type : {profile['label']}")
    print(f"  Analyzed     : {profile['commits_analyzed']} commits across "
          f"{profile['repos_analyzed']} repos")
    user = profile.get("user") or {}
    if user:
        print(f"  GitHub       : {user.get('followers', 0)} followers · "
              f"{user.get('following', 0)} following · "
              f"{user.get('public_repos', 0)} public repos · "
              f"{user.get('years_active', '?')} yrs active")
        if user.get("bio"):
            print(f"  Bio          : {user['bio'][:70]}")
    print("  Activity split:")
    for dev_type, pct in profile["activity_split"].items():
        if pct <= 0:
            continue
        bar = "#" * (pct // 4)
        print(f"    {dev_type:<22} {pct:>3}%  {bar}")
    if profile.get("languages"):
        print("  Top languages: " + ", ".join(
            f"{l['name']} {l['pct']}%" for l in profile["languages"][:5]))
    elif profile.get("top_languages"):  # older cached profiles
        print(f"  Top languages: {', '.join(profile['top_languages'])}")
    print(f"  Commit msg quality : {profile['commit_message_quality']}/10")
    prs = f"  PRs authored       : {profile['authored_prs']}"
    if "prs_merged" in profile:
        prs += f" ({profile['prs_merged']} merged)"
    print(prs)
    if "issues_resolved" in profile:
        print(f"  Issues resolved    : {profile['issues_resolved']}")
    if profile.get("heatmap"):
        days_active = len(profile["heatmap"])
        total = sum(d["count"] for d in profile["heatmap"])
        print(f"  Last 365 days      : {total} commits on {days_active} days")
    print(f"  Review participation: {profile['review_participation']}")
    if profile.get("llm_summary"):
        print("\n  AI summary:")
        for line in profile["llm_summary"].splitlines():
            print(f"    {line}")
    print()


def _print_train_report(report: dict) -> None:
    print("\n" + "=" * 60)
    print("XGBoost training report")
    print("=" * 60)
    print(f"  rows           : {report['n_rows']}  "
          f"({report['positives']} positive / {report['negatives']} negative)")
    print(f"  repos          : {report['repos']}   languages: {report['languages']}")
    auc = report.get("auc_cross_repo")
    print(f"  cross-repo AUC : {auc:.3f}" if auc is not None else "  cross-repo AUC : n/a")
    if report.get("precision_at_k") is not None:
        print(f"  precision@{report['k']:<4}: {report['precision_at_k']:.3f}")
    by_lang = report.get("by_language_auc") or {}
    if by_lang:
        print("  held-out-language AUC (cross-language transfer):")
        for lang, a in by_lang.items():
            print(f"    - trained without {lang}, tested on {lang}: AUC {a:.3f}")
    print("  feature importance:")
    for feat, imp in report.get("importances", [])[:8]:
        bar = "#" * int(round(imp * 40))
        print(f"    {feat:<18} {imp:.3f}  {bar}")
    print(f"  reliable       : {report['reliable']}  "
          f"(>= {report.get('min_positives', 20) if 'min_positives' in report else ''} positives & AUC>=0.55)")
    print(f"  model saved    : {report.get('model_path')}")
    if not report["reliable"]:
        print("  NOTE: dataset is thin - treat ML probabilities as a weak hint, not truth.")
    print()


# --------------------------------------------------------------------------- #
# actions
# --------------------------------------------------------------------------- #
def run_config(env: str) -> None:
    settings = Settings.load(env)
    print("\nResolved configuration:")
    print(settings.summary())
    print()


def run_test_llm(env: str) -> None:
    from core.llm import LLMUnavailable, get_llm

    settings = Settings.load(env)
    try:
        llm = get_llm(settings)
    except LLMUnavailable as exc:
        print(f"  {exc}\n")
        return
    print(f"\n  Provider: {llm.describe()}")
    if getattr(llm, "autoload", False):
        print("  autoload: on (LOCAL_LLM_AUTOLOAD)")
    if not llm.available():
        hint = "start LM Studio, or set the provider's API key"
        if getattr(llm, "autoload", None) is False:  # local provider, toggle off
            hint += "; LOCAL_LLM_AUTOLOAD=true auto-loads a model"
        print(f"  status  : UNAVAILABLE ({hint})\n")
        return
    print("  status  : available — sending a test prompt ...")
    try:
        reply = llm.generate(
            "Reply with exactly: RepoLens LLM OK",
            system="You are a terse assistant.",
            max_tokens=20,
        )
        print(f"  reply   : {reply}\n")
    except LLMUnavailable as exc:
        print(f"  reply   : FAILED - {exc}\n")


def run_setup_indexes(env: str) -> None:
    settings = Settings.load(env)
    store = open_store_announced(settings)
    store.ensure_indexes()
    print(f"  indexes ensured on backend: {store.backend}\n")


def run_pull(repo: str, env: str = ".env", max_commits: int = 0) -> None:
    from core.github_client import ensure_local_clone
    from pipeline.fetch_commits import fetch_and_store_commits

    settings = Settings.load(env)
    store = open_store_announced(settings)
    local_path, key = ensure_local_clone(repo, settings.cache_dir)
    print(f"  pulling {key} from {local_path} ...")
    commits = fetch_and_store_commits(
        local_path, key, store,
        keywords=settings.bug_keywords,
        max_commits=max_commits or None,
    )
    bug = sum(1 for c in commits if c.get("is_bugfix"))
    print(f"  cached {len(commits)} commits ({bug} bug-fix) for '{key}' [{store.backend}]\n")


def run_analyze(repo: str, env: str = ".env", top: int = 15,
                refresh: bool = False, max_commits: int = 0) -> None:
    from core.analysis import run_hotspot_analysis

    settings = Settings.load(env)
    store = open_store_announced(settings)
    result = run_hotspot_analysis(
        repo, settings, store,
        refresh=refresh,
        max_commits=max_commits or None,
        top=top,
    )
    _print_table(result, top)


def run_train(env: str = ".env", repo_list: str = "train_repos.txt",
              max_commits: int = 0) -> None:
    from pipeline.build_training_data import train_from_list

    settings = Settings.load(env)
    report = train_from_list(
        settings, repo_list_path=repo_list, max_commits=max_commits or None
    )
    report["min_positives"] = settings.ml_min_positives
    _print_train_report(report)


# --------------------------------------------------------------------------- #
# interactive prompts per action
# --------------------------------------------------------------------------- #
def interactive_analyze(env: str) -> None:
    repo = prompt("Repo path or URL", required=True)
    top = prompt_int("Rows to display", 15)
    refresh = prompt_bool("Re-pull history (ignore cache)?", False)
    max_commits = prompt_int("Max commits to scan (0 = all)", 0)
    run_analyze(repo, env=env, top=top, refresh=refresh, max_commits=max_commits)


def interactive_pull(env: str) -> None:
    repo = prompt("Repo path or URL", required=True)
    max_commits = prompt_int("Max commits to scan (0 = all)", 0)
    run_pull(repo, env=env, max_commits=max_commits)


def interactive_train(env: str) -> None:
    repo_list = prompt("Path to repo list", "train_repos.txt")
    max_commits = prompt_int("Max commits per repo (0 = all)", 0)
    run_train(env, repo_list=repo_list, max_commits=max_commits)


def run_commit_quality(repo: str, env: str = ".env", top: int = 15,
                       suggest: bool = False, max_commits: int = 0) -> None:
    from tools.commit_quality.runner import run_commit_quality_report

    settings = Settings.load(env)
    store = open_store_announced(settings)
    report = run_commit_qual5ity_report(
        repo, settings, store,
        max_commits=max_commits or None, suggest=suggest, top=top,
    )
    _print_commit_quality(report, top)


def interactive_commit_quality(env: str) -> None:
    repo = prompt("Repo path or URL", required=True)
    top = prompt_int("Worst messages to display", 15)
    suggest = prompt_bool("Generate LLM rewrites for the worst ones?", False)
    run_commit_quality(repo, env=env, top=top, suggest=suggest)


def run_profile(username: str, env: str = ".env", refresh: bool = False) -> None:
    from tools.dev_profiler.runner import run_developer_profile

    settings = Settings.load(env)
    store = open_store_announced(settings)
    profile = run_developer_profile(username, settings, store, refresh=refresh)
    _print_profile(profile)


def interactive_profile(env: str) -> None:
    username = prompt("GitHub username (@handle)", required=True).lstrip("@")
    refresh = prompt_bool("Re-fetch even if a fresh cached profile exists?", False)
    run_profile(username, env=env, refresh=refresh)


def run_review_pr(spec: str, env: str = ".env", post: bool = False) -> None:
    from tools.pr_reviewer.runner import run_pr_review

    settings = Settings.load(env)
    store = open_store_announced(settings)
    report = run_pr_review(spec, settings, store, post=post)
    print("\n" + "=" * 100)
    print(report["markdown"])
    print("=" * 100 + "\n")


def interactive_review_pr(env: str) -> None:
    spec = prompt("PR (owner/repo#number or URL)", required=True)
    # produce the report first, then offer to post it
    from tools.pr_reviewer.runner import run_pr_review

    settings = Settings.load(env)
    store = open_store_announced(settings)
    report = run_pr_review(spec, settings, store, post=False)
    print("\n" + "=" * 100)
    print(report["markdown"])
    print("=" * 100)
    if prompt_bool("\nPost this as a comment on the PR?", False):
        from tools.pr_reviewer.github_commenter import post_comment
        from tools.pr_reviewer.runner import parse_pr_spec
        from core.github_client import GitHubAPI

        owner, repo, number = parse_pr_spec(spec)
        api = GitHubAPI(settings.github_token)
        try:
            url = post_comment(api, {"owner": owner, "repo": repo, "number": number},
                               report["markdown"])
            print(f"  posted: {url}\n")
        except Exception as exc:
            print(f"  [warn] failed to post: {exc}\n")


MENU = """
RepoLens - GitHub Analytics & Intelligence
==========================================
  1) analyze        rank bug-hotspot files (+ XGBoost second opinion if trained)
  2) pull           fetch & cache commit history
  3) train          train the XGBoost second-opinion model (from train_repos.txt)
  4) commit-quality score commit messages (+ LLM rewrites)
  5) profile        build a developer skill profile for a GitHub user
  6) review-pr      pre-review report for a pull request (Tool 3)
  7) test-llm       check the configured LLM provider
  8) setup-indexes  create MongoDB indexes
  9) config         show resolved settings
 10) quit
"""


def main() -> int:
    env = ".env"
    if not os.path.isfile(env) and os.path.isfile(".env.example"):
        # convenience: fall back to the example file if no .env exists yet
        env = ".env.example"

    print(f"(using settings from: {env})")
    while True:
        print(MENU)
        try:
            choice = input("Select an option (1-10): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        try:
            if choice in ("1", "analyze", "a"):
                interactive_analyze(env)
            elif choice in ("2", "pull", "p"):
                interactive_pull(env)
            elif choice in ("3", "train", "t"):
                interactive_train(env)
            elif choice in ("4", "commit-quality", "commit", "cq"):
                interactive_commit_quality(env)
            elif choice in ("5", "profile", "prof"):
                interactive_profile(env)
            elif choice in ("6", "review-pr", "pr", "review"):
                interactive_review_pr(env)
            elif choice in ("7", "test-llm", "llm"):
                run_test_llm(env)
            elif choice in ("8", "setup-indexes", "setup", "s"):
                run_setup_indexes(env)
            elif choice in ("9", "config", "c"):
                run_config(env)
            elif choice in ("10", "quit", "q", "exit", ""):
                print("bye.")
                return 0
            else:
                print("  unknown option; choose 1-10.")
        except (EOFError, KeyboardInterrupt):
            print("\ncancelled.")
        except SystemExit as exc:
            print(f"  {exc}")
        except Exception as exc:  # keep the menu alive on operational errors
            print(f"  error: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
