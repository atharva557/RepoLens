import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import Settings
from core.db import open_store
from core.github_client import get_repo_meta, get_recent_pulls
from core.analysis import run_hotspot_analysis
from core.insights import run_repo_insights
from core.activity import build_activity_base
from tools.commit_quality.runner import run_commit_quality_report
from tools.dev_profiler.runner import run_developer_profile
from core.identity import open_identity

def main():
    repos = [
        "tiangolo/fastapi",
        "pallets/jinja",
        "encode/httpx",
        "psf/black",
        "vitejs/vite",
        "sindresorhus/chalk",
        "spf13/viper",
        "junegunn/fzf",
        "BurntSushi/ripgrep",
        "jqlang/jq",
    ]

    settings = Settings.load(".env")
    store = open_store(settings)
    identity = open_identity(settings)
    
    # Fetch all user IDs so we can track repos/profiles for them
    user_ids = []
    if identity:
        try:
            if identity.backend == "postgres":
                with identity.conn.cursor() as cur:
                    cur.execute("SELECT id FROM users")
                    user_ids = [r[0] for r in cur.fetchall()]
            elif identity.backend == "memory":
                user_ids = [u["id"] for u in identity._data.get("users", {}).values()]
        except Exception as e:
            print(f"Error fetching users: {e}")

    total = len(repos)
    success = 0
    failed = []
    
    start_time = time.time()
    
    for i, repo in enumerate(repos, 1):
        print(f"[{i}/{total}] Processing {repo}...")
        try:
            # Metadata
            print(f"  - Fetching metadata and PRs")
            get_repo_meta(repo, settings, store, refresh=True)
            get_recent_pulls(repo, settings, store, refresh=True)
            
            # Hotspot Analysis (this fetches commits and stores them)
            print(f"  - Hotspot analysis (commits, bug classification, scoring)")
            run_hotspot_analysis(repo, settings, store, refresh=True)
            
            # Base activity
            commits = store.load_commits(repo)
            base = None
            if commits:
                base = build_activity_base(commits)
                store.save_report("activity_base", repo, base)
            
            # Repo Insights
            print(f"  - Repo insights")
            run_repo_insights(repo, settings, store)
            
            # Commit Quality
            print(f"  - Commit quality report")
            run_commit_quality_report(repo, settings, store)
            
            # Developer Profiles for Contributors (top contributors)
            if base and "contributors" in base:
                print(f"  - Generating Developer Profiles for top {len(base['contributors'])} contributors")
                for c in base["contributors"]:
                    author_login = c.get("author")
                    if author_login and author_login.lower() != "unknown" and " " not in author_login and "@" not in author_login:
                        try:
                            print(f"    - Profiling {author_login}...")
                            run_developer_profile(author_login, settings, store, refresh=False)
                            if identity:
                                for uid in user_ids:
                                    identity.track_profile(uid, author_login)
                        except Exception as e:
                            print(f"    - Failed to profile {author_login}: {e}")
            
            # Track repo for all users
            if identity:
                for uid in user_ids:
                    identity.track_repo(uid, repo)
            
            success += 1
            print(f"  => Successfully cached {repo}\n")
        except Exception as e:
            print(f"  => Failed to process {repo}: {e}\n")
            failed.append((repo, str(e)))
            
    elapsed = time.time() - start_time
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"Total repositories processed: {total}")
    print(f"Successfully cached/updated : {success}")
    print(f"Failed                      : {len(failed)}")
    print(f"Time taken                  : {elapsed:.2f} seconds")
    if failed:
        print("\nFailures:")
        for r, err in failed:
            print(f"  - {r}: {err}")

if __name__ == "__main__":
    main()
