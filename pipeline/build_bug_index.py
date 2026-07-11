"""Build a similarity index over a repo's past bug-fix diffs (Tool 3).

This is the "embedding pipeline": take the repo's bug-fix commits (already
classified in v0.1), pull each commit's diff, and index them so a new PR diff
can be compared against them. Backend (Chroma vs Lite) is chosen by the index.

The corpus only changes when new commits arrive, so the persistent Chroma
backend is reused when the corpus fingerprint matches — skipping both the
git-show loop and the re-embedding that used to run on every single review.
Collections are per-repo: sharing one meant two concurrent reviews of
different repos silently corrupted each other's similarity scores.
"""
from __future__ import annotations

import re

from core.embeddings import open_similarity_index
from core.paths import is_code_file


def _qualifying(commits: list[dict]):
    """Bug fixes that touched at least one source file: a changelog-typo "fix"
    is not bug signal, and matching a PR's own changelog edit against it
    produced false similarity warnings."""
    for c in commits:
        if not c.get("is_bugfix"):
            continue
        if any(is_code_file(f.get("path", "")) for f in c.get("files", [])):
            yield c


def corpus_fingerprint(commits: list[dict], max_diffs: int = 400) -> str:
    """Cheap identity for the would-be corpus, computed WITHOUT extracting
    diffs: the shas that would be indexed fully determine it."""
    shas = [c.get("sha", "")[:12] for c in _qualifying(commits)][:max_diffs]
    return f"{len(shas)}:{shas[0] if shas else ''}:{shas[-1] if shas else ''}"


def collection_name(repo_key: str) -> str:
    """Chroma-safe per-repo collection name (alnum/_/-, 3-63 chars)."""
    slug = re.sub(r"[^a-zA-Z0-9_-]", "_", repo_key or "default")
    return f"bugdiffs_{slug}"[:63].rstrip("_-") or "bugdiffs_default"


def build_bug_diff_index(commits: list[dict], git_client, settings, *,
                         repo_key: str = "", max_diffs: int = 400, index=None):
    """Return (SimilarityIndex, corpus_size) over the repo's bug-fix diffs.

    `commits` are v0.1 commit dicts (need `is_bugfix`); `git_client` is a
    GitClient for the same repo (to fetch diffs). Empty index if no bug fixes.
    `index` is injectable for tests.
    """
    if index is None:
        index = open_similarity_index(settings, collection=collection_name(repo_key))

    fingerprint = corpus_fingerprint(commits, max_diffs)
    if hasattr(index, "try_reuse") and index.try_reuse(fingerprint):
        n = index.count() if hasattr(index, "count") else 0
        print(f"  [cache] bug-diff corpus unchanged - reusing persisted index ({n} diffs)")
        return index, n

    docs = []
    for c in _qualifying(commits):
        sha = c.get("sha", "")
        diff = git_client.commit_diff(sha) if sha else ""
        text = f"{c.get('message', '')}\n{diff}".strip()
        if not text:
            continue
        docs.append({
            "id": sha[:12] or str(len(docs)),
            "text": text,
            "meta": {"sha": sha[:12], "subject": (c.get("message", "").splitlines() or [""])[0][:80]},
        })
        if len(docs) >= max_diffs:
            break

    index.build(docs, fingerprint=fingerprint)
    return index, len(docs)
