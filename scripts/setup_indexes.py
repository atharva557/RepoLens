"""Create MongoDB indexes (replaces the old setup_db.py).

    python scripts/setup_indexes.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli import run_setup_indexes


def main() -> int:
    env = ".env" if os.path.isfile(".env") else ".env.example"
    run_setup_indexes(env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
