"""Build a similarity index over a repo's past bug-fix diffs (Tool 3).

This is the "embedding pipeline": take the repo's bug-fix commits (already
classified in v0.1), pull each commit's diff, and index them so a new PR diff can
be compared against them. Backend (Chroma vs Lite) is chosen by the index itself.
"""
from __future__ import annotations

from core.embeddings import open_similarity_index


def build_bug_diff_index(commits: list[dict], git_client, settings, *, max_diffs: int = 400):
    """Return a built SimilarityIndex over the repo's bug-fix diffs.

    `commits` are v0.1 commit dicts (need `is_bugfix`); `git_client` is a
    GitClient for the same repo (to fetch diffs). Empty index if no bug fixes.
    """
    docs = []
    for c in commits:
        if not c.get("is_bugfix"):
            continue
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

    index = open_similarity_index(settings)
    index.build(docs)
    return index, len(docs)
