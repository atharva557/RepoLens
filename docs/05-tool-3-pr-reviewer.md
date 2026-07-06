# 05 — Tool 3: PR Review Assistant

**Question it answers:** *is this pull request risky?* — answered **before**
any human reviews it.

Entry points: CLI option 6 (`review-pr`), `POST /repos/{o}/{r}/pr-reviews/{n}`,
and the GitHub webhook (`POST /webhook/github`) which auto-reviews PRs as they
open/update. Requires `GITHUB_TOKEN`.

## Pipeline (`tools/pr_reviewer/runner.py`)

```
"owner/repo#42"  (or a full PR URL — parse_pr_spec handles both)
  1. fetch PR metadata + changed files (patches) via the GitHub API
  2. ensure a local clone; load/refresh the cached commit history
  3. build the bug-diff similarity corpus            [pipeline/build_bug_index.py]
  4. get the repo's hotspot list (Tool 1)            for the file-risk check
  5. mechanical risk checks                          [risk_scorer.py]
     + diff similarity to past bug fixes             [similarity.py]
     + LLM summary of the diff                       [llm_summarizer.py]
  6. assemble markdown + structured report           [report_builder.py]
  7. persist as kind "pr_review", key "owner/repo#N"; optionally post as PR comment
```

## Mechanical risk checks (`risk_scorer.py`)

Deterministic, LLM-free, driven by the PR's changed file list and the repo's
hotspot paths:

| Check | Trigger (defaults) |
|---|---|
| **File risk** | PR touches files in the repo's top-`HOTSPOT_TOP_N` (10) hotspots |
| **Missing tests** | source files changed (`is_source_file`) but no test files touched (`is_test_file` — `test`/`spec` in name, `/tests/` dirs) |
| **Unfocused change** | ≥ 12 files changed, or changes span ≥ 4 top-level directories |
| **Large change** | ≥ 400 lines added |

Each failed check produces a warning string; each passed one an "OK" line —
the report shows both, so a clean PR gets explicit green checkmarks.

## Similarity to past bugs (`similarity.py` + `pipeline/build_bug_index.py`)

The core idea: *code that looks like code we've had to fix before deserves
extra scrutiny.*

1. **Corpus**: every bug-fix commit in the cached history (up to 400) has its
   diff extracted (`GitClient.commit_diff`, truncated to 4,000 chars) and
   indexed.
2. **Query**: the PR's concatenated patch text (first 8,000 chars) is embedded
   and compared against the corpus with cosine similarity.
3. **Warning**: the top match's score ≥ `PR_SIMILARITY_WARN` (default 0.6)
   raises a similarity warning, and the top-`PR_SIMILARITY_TOP_K` matches
   (with their commit SHAs/messages) appear in the report.

The index backend is pluggable (see [07-llm-and-similarity.md](07-llm-and-similarity.md)):
real semantic embeddings via sentence-transformers + ChromaDB when installed,
otherwise a stdlib TF-IDF cosine index. Same interface, zero setup required.

## Risk level & report (`report_builder.py`)

```
HIGH    — hotspot files touched, or similarity warning fired
MEDIUM  — any other mechanical warning
LOW     — all checks passed
```

The report is rendered as markdown ("🤖 RepoLens Pre-Review Report": risk
level, warnings, similarity matches, AI summary, OK-list) and stored as a
structured dict alongside it. The **AI summary** — the configured LLM
describing what the diff actually does — is optional and skipped cleanly
without a provider.

## Posting back to GitHub

- **CLI**: after printing the report, asks interactively whether to post it as
  a PR comment.
- **Webhook**: posting is controlled by `GITPULSE_WEBHOOK_POST` (default
  **off**, because it is outward-facing). The report is always persisted to
  the store either way.

See [08-api.md](08-api.md) for the webhook's HMAC verification and event
filtering.
