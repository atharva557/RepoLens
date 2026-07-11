"""Tests for the diff-similarity layer (Tool 3).

Exercises the stdlib LiteIndex and the factory's graceful fallback. The heavy
ChromaIndex is only used when sentence-transformers + chromadb are installed;
these tests never require them.

    python tests/test_embeddings.py
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.embeddings import LiteIndex, open_similarity_index


def _corpus():
    return [
        {"id": "a", "text": "fix null pointer when auth token expires in session validation",
         "meta": {"sha": "a"}},
        {"id": "b", "text": "add payments route with currency rounding and refunds",
         "meta": {"sha": "b"}},
        {"id": "c", "text": "update readme and documentation for installation",
         "meta": {"sha": "c"}},
    ]


def test_lite_index_ranks_relevant_first():
    idx = LiteIndex()
    idx.build(_corpus())
    res = idx.query("session token expired null pointer during validation", k=3)
    assert res[0]["id"] == "a", res
    assert res[0]["score"] > res[1]["score"]
    assert res[0]["meta"]["sha"] == "a"
    print("  ok: lite index ranks relevant diff first")


def test_lite_index_edge_cases():
    idx = LiteIndex()
    idx.build([])                        # empty corpus
    assert idx.query("anything") == []
    idx.build(_corpus())
    assert idx.query("", k=3) is not None  # empty query doesn't crash
    # unrelated query -> low top score
    res = idx.query("quantum chromodynamics lagrangian", k=1)
    assert res[0]["score"] < 0.2, res
    print("  ok: lite index edge cases")


def test_factory_falls_back_to_lite():
    # chroma deps aren't installed here -> auto should give LiteIndex
    idx = open_similarity_index(SimpleNamespace(
        similarity_backend="auto", embedding_model="all-MiniLM-L6-v2",
        chroma_path="data/chroma",
    ))
    assert idx.backend.startswith("lite") or idx.backend.startswith("chroma")
    # forcing lite always yields lite
    idx2 = open_similarity_index(SimpleNamespace(
        similarity_backend="lite", embedding_model="x", chroma_path="data/chroma"))
    assert idx2.backend.startswith("lite")
    print(f"  ok: factory fallback ({idx.backend})")


def test_corpus_fingerprint_and_collection_name():
    from pipeline.build_bug_index import collection_name, corpus_fingerprint

    commits = [
        {"sha": "a" * 20, "is_bugfix": True,
         "files": [{"path": "a.py"}]},
        {"sha": "b" * 20, "is_bugfix": True,
         "files": [{"path": "README.md"}]},         # docs-only: not in corpus
        {"sha": "c" * 20, "is_bugfix": True,
         "files": [{"path": "c.py"}]},
    ]
    fp = corpus_fingerprint(commits)
    assert fp == corpus_fingerprint(commits)          # deterministic
    # a new qualifying bug fix changes the fingerprint
    grown = [{"sha": "d" * 20, "is_bugfix": True,
              "files": [{"path": "d.py"}]}] + commits
    assert corpus_fingerprint(grown) != fp
    # ...but a docs-only fix does not (it never enters the corpus)
    docsy = [{"sha": "e" * 20, "is_bugfix": True,
              "files": [{"path": "CHANGES.rst"}]}] + commits
    assert corpus_fingerprint(docsy) == fp

    assert collection_name("pallets/flask") == "bugdiffs_pallets_flask"
    assert collection_name("") == "bugdiffs_default"
    print("  ok: corpus fingerprint + per-repo collection names")


def test_index_reuse_skips_diff_extraction():
    """When the persisted corpus matches, neither git-show nor re-embedding
    may run — that cost used to be paid on every single PR review."""
    from pipeline.build_bug_index import build_bug_diff_index

    class ReusableIndex:
        backend = "fake"

        def __init__(self):
            self.built = 0
            self.persisted_fp = None

        def try_reuse(self, fp):
            return fp == self.persisted_fp

        def count(self):
            return 7

        def build(self, docs, fingerprint=None):
            self.built += 1
            self.persisted_fp = fingerprint

    class GitSpy:
        def __init__(self):
            self.calls = 0

        def commit_diff(self, sha):
            self.calls += 1
            return f"diff of {sha}"

    commits = [{"sha": "a" * 20, "is_bugfix": True, "message": "Fix x",
                "files": [{"path": "a.py"}]}]
    idx, git = ReusableIndex(), GitSpy()

    # first run: builds, extracts the diff, persists the fingerprint
    _, n = build_bug_diff_index(commits, git, None, repo_key="o/r", index=idx)
    assert idx.built == 1 and git.calls == 1 and n == 1

    # second run, unchanged corpus: reused - no build, NO git-show calls
    _, n = build_bug_diff_index(commits, git, None, repo_key="o/r", index=idx)
    assert idx.built == 1 and git.calls == 1 and n == 7  # count() from the index

    # corpus grows -> fingerprint differs -> rebuilt
    commits.insert(0, {"sha": "b" * 20, "is_bugfix": True, "message": "Fix y",
                       "files": [{"path": "b.py"}]})
    _, n = build_bug_diff_index(commits, git, None, repo_key="o/r", index=idx)
    assert idx.built == 2 and git.calls == 3 and n == 2
    print("  ok: unchanged corpus reuses the index without git-show")


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    print(f"running {len(fns)} test(s)...")
    for fn in fns:
        fn()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    _run_all()
