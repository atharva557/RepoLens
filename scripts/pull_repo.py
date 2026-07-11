"""One-time fetch of a repo's commit history into the cache.

Interactive: prompts for the repo path.

    python scripts/pull_repo.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli import interactive_pull


def main() -> int:
    env = ".env" if os.path.isfile(".env") else ".env.example"
    interactive_pull(env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
