"""Diff-similarity engine — pluggable vector index (Tool 3).

Compares a PR diff against a corpus of past bug-fix diffs. Two interchangeable
backends behind one `SimilarityIndex` interface:

  - ChromaIndex : sentence-transformers embeddings + a persistent ChromaDB
                  collection (real semantic similarity). Heavy optional deps.
  - LiteIndex   : pure-stdlib TF-IDF cosine similarity. No install required.

`open_similarity_index()` prefers Chroma and transparently falls back to Lite
(same graceful pattern as MongoDB/LLM in earlier versions), so v0.3 runs
everywhere and simply gets better when the heavy deps are installed.

Doc shape:  {"id": str, "text": str, "meta": dict}
Result shape: {"id": str, "score": float (0..1 cosine), "meta": dict}
"""
from __future__ import annotations

import math
import re
from collections import Counter


def _tokens(text: str) -> list[str]:
    # identifiers + numbers; good enough for code diffs
    return re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*|\d+", (text or "").lower())


class LiteIndex:
    """Dependency-free TF-IDF cosine index."""

    backend = "lite (tf-idf)"

    def __init__(self):
        self.docs: list[dict] = []
        self.vectors: list[dict] = []
        self.norms: list[float] = []
        self.idf: dict[str, float] = {}

    def build(self, docs: list[dict]) -> None:
        self.docs = [{"id": str(d["id"]), "meta": d.get("meta", {})} for d in docs]
        tokenized = [_tokens(d["text"]) for d in docs]
        n = len(tokenized) or 1
        df: Counter = Counter()
        for toks in tokenized:
            for t in set(toks):
                df[t] += 1
        self.idf = {t: math.log((n + 1) / (c + 1)) + 1 for t, c in df.items()}
        self.vectors, self.norms = [], []
        for toks in tokenized:
            vec = self._weight(toks)
            self.vectors.append(vec)
            self.norms.append(math.sqrt(sum(w * w for w in vec.values())) or 1.0)

    def _weight(self, toks: list[str]) -> dict:
        if not toks:
            return {}
        tf = Counter(toks)
        return {t: (c / len(toks)) * self.idf.get(t, 0.0) for t, c in tf.items()}

    def query(self, text: str, k: int = 5) -> list[dict]:
        qv = self._weight(_tokens(text))
        qn = math.sqrt(sum(w * w for w in qv.values())) or 1.0
        out = []
        for i, (vec, norm) in enumerate(zip(self.vectors, self.norms)):
            small, big = (qv, vec) if len(qv) < len(vec) else (vec, qv)
            dot = sum(w * big.get(t, 0.0) for t, w in small.items())
            out.append({
                "id": self.docs[i]["id"],
                "score": round(dot / (qn * norm), 4),
                "meta": self.docs[i]["meta"],
            })
        out.sort(key=lambda r: r["score"], reverse=True)
        return out[:k]


class ChromaIndex:
    """sentence-transformers + ChromaDB (cosine). Heavy optional deps, lazy."""

    backend = "chroma (sentence-transformers)"

    def __init__(self, model_name: str, chroma_path: str, collection: str = "bug_diffs"):
        from sentence_transformers import SentenceTransformer  # lazy
        import chromadb  # lazy

        self.model = SentenceTransformer(model_name)
        self.client = chromadb.PersistentClient(path=chroma_path)
        self.collection = collection
        self.coll = None

    def build(self, docs: list[dict]) -> None:
        try:
            self.client.delete_collection(self.collection)
        except Exception:
            pass
        self.coll = self.client.create_collection(
            self.collection, metadata={"hnsw:space": "cosine"}
        )
        if not docs:
            return
        embs = self.model.encode([d["text"] for d in docs]).tolist()
        self.coll.add(
            ids=[str(d["id"]) for d in docs],
            embeddings=embs,
            metadatas=[(d.get("meta") or {"id": str(d["id"])}) for d in docs],
            documents=[(d["text"] or "")[:2000] for d in docs],
        )

    def query(self, text: str, k: int = 5) -> list[dict]:
        if self.coll is None:
            return []
        emb = self.model.encode([text]).tolist()
        res = self.coll.query(query_embeddings=emb, n_results=k)
        ids = res["ids"][0]
        dists = res["distances"][0]
        metas = (res.get("metadatas") or [[]])[0]
        out = []
        for i, doc_id in enumerate(ids):
            out.append({
                "id": doc_id,
                "score": round(1.0 - float(dists[i]), 4),  # cosine distance -> similarity
                "meta": metas[i] if metas else {},
            })
        return out


def open_similarity_index(settings):
    """Prefer Chroma; fall back to the stdlib Lite index.

    Always announces which backend was picked (and whether it is the primary
    choice, a configured selection, or a fallback) so every run is explicit
    about what produced the similarity scores.
    """
    backend = getattr(settings, "similarity_backend", "auto")
    if backend in ("auto", "chroma"):
        try:
            index = ChromaIndex(settings.embedding_model, settings.chroma_path)
            print("  [backend] similarity: chroma + sentence-transformers (primary)")
            return index
        except Exception as exc:
            if backend == "chroma":
                raise
            print(f"  [backend] similarity: lite tf-idf "
                  f"(FALLBACK — chroma unavailable: {type(exc).__name__})")
            return LiteIndex()
    print("  [backend] similarity: lite tf-idf (selected in config)")
    return LiteIndex()
