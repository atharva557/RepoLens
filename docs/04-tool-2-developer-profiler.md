# 04 — Tool 2: Developer Skill Profiler

**Question it answers:** *what kind of developer is `@username`?*

Builds a profile card from a user's **public GitHub activity** across their
repositories. Entry points: CLI option 5, `POST /profiles/{username}` +
`GET /profiles/{username}`. Requires `GITHUB_TOKEN` (PyGithub).

## Pipeline

```
username
  → pipeline/fetch_user_activity.py     GitHub REST → normalized activity dict
  → tools/dev_profiler/classifier.py    rule-based type distribution
  → tools/commit_quality/scorer.py      message quality (reuses Tool 4)
  → tools/dev_profiler/llm_analyzer.py  optional LLM read of the whole profile
  → tools/dev_profiler/profile_builder  final profile document
  → store.save_report("developer_profile", username, doc)
```

## Fetching activity — rate-limit-conscious by design

The GitHub API is expensive per-commit, so hard caps apply (all `.env`-tunable):

| Cap | Default | Meaning |
|---|---|---|
| `PROFILE_MAX_REPOS` | 15 | most recently active public repos scanned |
| `PROFILE_MAX_COMMITS_PER_REPO` | 100 | commits fetched per repo |
| `PROFILE_PR_SAMPLE` | 8 | PR descriptions sampled for the LLM summary |

The result is a normalized `activity` dict: commits (with additions/deletions,
message, per-file `status` — added/modified/removed/renamed), language counts
per repo, review participation (`reviews_count`, `review_comments`), and PR
descriptions. Commit messages run through the same bug-fix keyword classifier
as Tool 1.

**Caching — database-first:** any stored profile is served without touching
GitHub, however old. A rebuild costs hundreds of API calls and minutes, so it
is never a side effect of a read: `GET /profiles/{user}` is a pure store read
that returns `age_hours` and `stale` (computed on read — a persisted flag
would itself go stale) alongside the profile. The UI uses those to offer a
re-sync. GitHub is hit only on the first build or an explicit refresh: the CLI
asks, and `POST /profiles/{user}` — the async job the dashboard's re-fetch
button triggers — always rebuilds.

> Contrast with `repo_meta`, which *is* cheap to refetch and therefore
> auto-refreshes on a TTL (see [02-data-and-storage.md](02-data-and-storage.md)).

## Classification — six developer types, deterministic signals

`classifier.py` turns the activity into a **percentage distribution** (not a
single label) over the guide's six types. Each type's signal is a simple,
explainable ratio:

| Type | Signal |
|---|---|
| **Bug Fixer** | share of bug-fix commits; edits mostly existing files |
| **Feature Builder** | share of commits creating new files |
| **Refactorer** | deletion-heavy commits (removes more than it adds) |
| **Reviewer** | PR reviews/comments relative to commit volume |
| **Documentation Writer** | share of doc-file touches (`core/paths.is_doc_file`) |
| **Architect** | wide commits (many files at once) + dependency/module file edits |

No LLM involved — this layer is pure stdlib and unit-testable. The
distribution is normalized to percentages and the max becomes `primary_type`.

## Profile assembly

`profile_builder.py` combines:

- the type distribution + primary type
- **top languages** (from repo language metadata)
- **commit-message quality** — the mean Tool 4 score over the fetched commits
- **review participation** counts
- a **daily activity heatmap** (last 365 days)
- optionally, an **LLM summary**: `llm_analyzer.py` builds a *digest* of the
  whole computed profile — the type distribution, language mix,
  commit/PR/review counts, commit-message quality, and a few real commit
  subjects (sampled PR descriptions are one input among these) — and asks the
  configured provider for a grounded qualitative paragraph. Summarizing PR
  descriptions alone left anyone without authored PRs (most users, including
  the project owner) with no summary at all; the digest fixes that. The
  prompt requires every claim to follow from the data given. Skipped cleanly
  when no LLM is available.

The final document is stored under kind `developer_profile`, key = username,
and rendered by the CLI and the dashboard's Developer Profile page.
