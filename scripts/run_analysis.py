"""Run the Bug Hotspot analysis on a repo and print the ranked table.

Interactive: prompts for the repo path and options.

    python scripts/run_analysis.py

(In v0.1 this runs Tool 1 only; Tools 2-4 land in later milestones.)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli import interactive_analyze


def main() -> int:
    env = ".env" if os.path.isfile(".env") else ".env.example"
    interactive_analyze(env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
