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


def run_setup_indexes(env: str) -> None:
    settings = Settings.load(env)
    store = open_store(settings)
    store.ensure_indexes()
    print(f"  indexes ensured on backend: {store.backend}\n")


def run_pull(repo: str, env: str = ".env", max_commits: int = 0) -> None:
    from core.github_client import ensure_local_clone
    from pipeline.fetch_commits import fetch_and_store_commits

    settings = Settings.load(env)
    store = open_store(settings)
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
    store = open_store(settings)
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


MENU = """
GitPulse v0.1 - Bug Hotspot foundation
======================================
  1) analyze        rank bug-hotspot files (+ XGBoost second opinion if trained)
  2) pull           fetch & cache commit history
  3) train          train the XGBoost second-opinion model (from train_repos.txt)
  4) setup-indexes  create MongoDB indexes
  5) config         show resolved settings
  6) quit
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
            choice = input("Select an option (1-5): ").strip().lower()
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
            elif choice in ("4", "setup-indexes", "setup", "s"):
                run_setup_indexes(env)
            elif choice in ("5", "config", "c"):
                run_config(env)
            elif choice in ("6", "quit", "q", "exit", ""):
                print("bye.")
                return 0
            else:
                print("  unknown option; choose 1-6.")
        except (EOFError, KeyboardInterrupt):
            print("\ncancelled.")
        except SystemExit as exc:
            print(f"  {exc}")
        except Exception as exc:  # keep the menu alive on operational errors
            print(f"  error: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
