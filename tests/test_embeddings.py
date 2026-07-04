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


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    print(f"running {len(fns)} test(s)...")
    for fn in fns:
        fn()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    _run_all()
