"""Shared file-path classification.

Used by the PR risk scorer (Tool 3) and by the bug-attribution gate in feature
extraction (Tool 1 cleanup). Pure stdlib.
"""
from __future__ import annotations

import os

CODE_EXT = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".rb", ".c",
    ".cpp", ".cc", ".h", ".hpp", ".cs", ".php", ".kt", ".swift", ".scala",
    ".m", ".mm", ".sh", ".sql", ".vue", ".dart", ".lua", ".r", ".ex", ".exs",
}
DOC_EXT = {".md", ".rst", ".txt", ".adoc"}
CONFIG_EXT = {
    ".toml", ".ini", ".cfg", ".yaml", ".yml", ".json", ".xml", ".env",
    ".lock", ".properties", ".conf",
}
_TEST_HINTS = ("test", "spec", "__tests__", "/tests/", "/test/")


def _ext(path: str) -> str:
    return os.path.splitext(path.lower())[1]


def is_doc_file(path: str) -> bool:
    p = path.lower()
    return _ext(p) in DOC_EXT or "readme" in p or "changelog" in p or "license" in p


def is_config_file(path: str) -> bool:
    return _ext(path) in CONFIG_EXT


def is_test_file(path: str) -> bool:
    p = path.lower()
    base = p.rsplit("/", 1)[-1]
    return any(h in p for h in ("/tests/", "/test/", "__tests__")) or \
        "test" in base or "spec" in base


def is_code_file(path: str) -> bool:
    """A real source-code file (excludes docs, config, lockfiles)."""
    return _ext(path) in CODE_EXT


def is_source_file(path: str) -> bool:
    """Code that isn't a test (used for the missing-tests heuristic)."""
    return is_code_file(path) and not is_test_file(path)
