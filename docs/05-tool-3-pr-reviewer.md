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
  3. build (or reuse) the bug-diff similarity corpus [pipeline/build_bug_index.py]
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
| **File risk** | PR touches **source files** in the repo's top-`HOTSPOT_TOP_N` (10) hotspots — docs/config/test files in the hotspot list (which rank on churn/authors) don't count as risky code |
| **Bug echo** | PR touches source files whose *latest* change was a bug fix within the churn window (fixes attract follow-up fixes) — read from the stored hotspot rows' features |
| **Missing tests** | source files changed (`is_source_file`) but no test files touched (`is_test_file` — `test`/`spec` in name, `/tests/` dirs) |
| **Unfocused change** | ≥ 12 files changed, or changes span ≥ 4 top-level directories |
| **Large change** | ≥ 400 lines added |
| **Weak description** | PR body empty, or Tool 4's message scorer rates `title\n\nbody` below 4/10 — tools composing: the commit-quality scorer reused verbatim |
| **New-file blind spot** *(note, not warning)* | brand-new source files ≥ 150 added lines have no history, so hotspot analysis cannot assess them — stated instead of silently reading as safe |

Each failed check produces a warning string; each passed one an "OK" line —
the report shows both, so a clean PR gets explicit green checkmarks.

## Similarity to past bugs (`similarity.py` + `pipeline/build_bug_index.py`)

The core idea: *code that looks like code we've had to fix before deserves
extra scrutiny.*

1. **Corpus**: every bug-fix commit **that touched at least one source file**
   (up to 400) has its diff extracted (`GitClient.commit_diff`, truncated to
   4,000 chars) and indexed. Docs/config-only "fixes" (changelog typos) are
   excluded — matching a PR's own changelog edit against them produced false
   similarity warnings.
   The corpus is **per-repo and reused when unchanged**: a corpus fingerprint
   (the qualifying SHAs) lets an unchanged repo skip the git-show loop and
   re-embedding entirely — see [07-llm-and-similarity.md](07-llm-and-similarity.md).
2. **Query**: the PR's concatenated patch text (first 8,000 chars) is embedded
   and compared against the corpus with cosine similarity.
3. **Warning**: the top match's score ≥ `PR_SIMILARITY_WARN` (default 0.6)
   raises a similarity warning, and the top-`PR_SIMILARITY_TOP_K` matches
   (with their commit SHAs/messages) appear in the report.

The index backend is pluggable (see [07-llm-and-similarity.md](07-llm-and-similarity.md)):
real semantic embeddings via sentence-transformers + ChromaDB when installed,
otherwise a stdlib TF-IDF cosine index. Same interface, zero setup required.

## Risk level & report (`report_builder.py`)

The level comes from a **weighted signal score** — same brand as Tool 1's
hotspot formula. Each fired check contributes a weight
(`report_builder.RISK_WEIGHTS`):

```
file_risk 0.30 · similarity 0.25 · missing_tests 0.20 · bug_echo 0.15
unfocused 0.10 · large_change 0.10 · weak_description 0.05
score = min(1.0, Σ fired weights)
HIGH ≥ PR_RISK_HIGH (0.5) · MEDIUM ≥ PR_RISK_MEDIUM (0.2) · else LOW
```

The arithmetic is printed in the report ("Score = 0.30 (hotspot files) +
0.20 (missing tests)"), so the level is always explainable, and the band
thresholds are `.env`-tunable for the v0.5 evaluation. HIGH requires
corroborated or strong evidence on purpose: any single heuristic meaning
HIGH made nearly every real-world PR HIGH, teaching reviewers to ignore the
level. (Validated on `pallets/flask#6066`: a focused, tests-updated feature
PR went from a false HIGH to LOW — score 0.00, description 10/10.)

A **coverage note** keeps the report honest when inputs are missing: if the
repo has no cached hotspots or bug-fix corpus, the report says which checks
could not run instead of silently scoring on fewer signals.

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
