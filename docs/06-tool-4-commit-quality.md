# 06 — Tool 4: Commit Message Quality Analyzer

**Question it answers:** *are our commit messages any good — and which ones
should have been better?*

Entry points: CLI option 4, `POST /commit-quality` +
`GET /repos/{key}/commit-quality`. Runs entirely offline; the LLM only enters
for the optional rewrites.

## Scoring one message (`tools/commit_quality/scorer.py`)

Each message gets **0–10** across five rule-based dimensions:

| Dimension | Good looks like |
|---|---|
| **length** | subject neither too short nor too long |
| **vagueness** | not just filler ("fix", "update", "wip", "changes", ...) |
| **verb** | starts with an imperative verb (Add / Fix / Refactor / ... — a curated `VERBS` set) |
| **context** | explains the *why*: a body, or a genuinely descriptive subject |
| **reference** | links an issue/ticket: `#142`, `ABC-123`, `closes #...` |

Pure stdlib and deterministic, so it is unit-testable and reusable — Tool 2
calls this same scorer to rate a developer's message quality.

## Repo-wide report (`reporter.py`)

`build_report(commits)` scores every cached commit and aggregates:

- overall stats: average score, good/weak counts
- **per-contributor health** (grouped by author)
- **monthly trend** over time
- the **most common bad patterns** (which dimensions fail most often)
- the **worst N commits**, kept as candidates for LLM rewrites

Persisted as kind `commit_quality`, key = repo key. The dashboard's health
score reuses the stored `avg_score`
(`health = 0.6·commit_quality + 0.4·(1−recent_bugfix_ratio)·10`).

## Optional LLM rewrites (`suggester.py`)

The scorer detects *that* a message is weak; the suggester proposes a better
one. Crucially, it works from the **actual diff** (`GitClient.commit_diff`),
not the old message — you can't write a meaningful commit message from a bad
one alone. The prompt enforces the conventional shape: imperative subject
under 72 chars, blank line, 1–3 lines of what/why.

Provider-agnostic (takes any `LLMProvider`) and degrades to a clear
placeholder when no LLM is configured. The CLI asks before running rewrites;
they're never automatic.
