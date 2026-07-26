# 02 — Data model & storage

## Repo keys

Every repository is identified by a stable **repo key**
(`core/github_client.repo_key`):

- GitHub URL (`https://github.com/pallets/flask`, `git@github.com:...`) →
  `"pallets/flask"` (owner/repo, `.git` stripped)
- Local path (`C:\work\myproject`) → the directory name (`"myproject"`)

The key is used everywhere: as the cache key in the store, in API URLs
(`GET /repos/pallets/flask/hotspots` — routes use `:path` params so the slash
survives), and as the JSON filename slug (`/` → `__`).

Remote URLs are cloned once into `data/cache/clones/<owner>__<repo>` by
`ensure_local_clone()`; subsequent runs reuse (and fetch-update) the clone.
The directory is keyed on the **full** repo key (`_clone_dest()`, same `/` →
`__` slug the JSON store uses), not the bare repo name — otherwise
`pallets/flask` and `yourfork/flask` would share one `clones/flask` and the
second repo analyzed would silently reuse the first one's history.

## The commit dict — the project's central data shape

`core/git_client.GitClient.iter_commits()` produces one dict per commit
(newest first, **merge commits skipped** — their diffs double-count churn):

```python
{
    "sha":     "abc123...",
    "author":  "Jane Doe",
    "email":   "jane@example.com",          # lowercased; author identity key
    "date":    datetime(..., tzinfo=utc),   # ALWAYS timezone-aware UTC
    "message": "Fix session cookie expiry",
    "is_bugfix": True,                      # added by pipeline/classify_commits
    "files": [
        {"path": "src/auth/session.py", "insertions": 12, "deletions": 4},
        ...
    ],
}
```

Everything downstream consumes this shape: feature extraction (Tool 1),
message scoring (Tool 4), the bug-diff corpus (Tool 3), and the dashboard
activity aggregations. Tool 2 uses a near-identical shape built from the
GitHub REST API instead of a local clone (plus a per-file `status` field).

**Timezone rule:** dates are aware-UTC end to end. The feature extractor
subtracts them from `datetime.now(timezone.utc)`, so the Mongo client is
created with `tz_aware=True` and the JSON codec round-trips datetimes through
a `{"__dt__": "<iso>"}` marker.

## The store interface

`core/db.py` defines two interchangeable backends behind one duck-typed
interface. Everything above the store is storage-agnostic.

```python
store.backend                     # "mongo" | "json"  (announced at startup)
store.ensure_indexes()            # Mongo: create indexes; JSON: no-op

# commit history (the shared cache)
store.save_commits(repo_key, commits)   # replace-all semantics
store.load_commits(repo_key)            # [] if none; ALWAYS newest-first

# Tool 1 reports (dedicated shape: {repo, generated_at, rows})
store.save_hotspots(repo_key, rows)
store.load_hotspots(repo_key)           # None if none

# everything else: generic (kind, key) documents
store.save_report(kind, key, doc)       # wraps as {key, generated_at, **doc}
store.load_report(kind, key)            # None if none
store.list_reports(kind, fields=())     # small discovery summaries
```

**Ordering contract:** `load_commits` returns **newest-first** from both
backends. Consumers depend on it — `pipeline/build_bug_index.py` takes the
first N qualifying commits and fingerprints the first/last SHA. JsonStore gets
this for free (commits are saved in git-log order and the file preserves it);
Mongo returns documents in unordered *natural* order, so `MongoStore` sorts
explicitly (`.sort([("date", -1)])`, backed by the `(repo, date desc)` index).
Without the explicit sort it worked only by accident of delete-then-insert
and was one compaction away from indexing the oldest diffs instead.

### Report kinds in use

| `kind` | `key` | Written by | Read by |
|---|---|---|---|
| `commit_quality` | repo key | Tool 4 runner | CLI, `GET /repos/{key}/commit-quality`, health score |
| `developer_profile` | GitHub username | Tool 2 runner | CLI, `GET /profiles/{user}` |
| `pr_review` | `owner/repo#N` | Tool 3 runner / webhook | CLI, `GET /repos/{key}/pr-reviews/{n}` |
| `repo_insights` | repo key | `core/insights.py` | `GET /repos/{key}/insights` |
| `repo_meta` | repo key | `core/github_client.get_repo_meta` | `GET /repos/{key}/meta` |
| `recent_pulls` | repo key | `core/github_client.get_recent_pulls` | `GET /repos/{key}/pulls` (dashboard PR card) |
| `activity_base` | repo key | `pipeline/fetch_commits.py` on every history save (self-heals on read for older caches) | `GET /repos/{key}/activity`, insights digest — the window-independent aggregate, so reads never scan the commit list |
| `api_selftest` | `"ping"` | `GET /test` round-trip check | — |

`report_age_hours(doc)` computes a report's age from its `generated_at`.
GitHub-backed documents are cached, but they differ in *how* they go live
again — the split is driven by how expensive a refetch is:

| Document | Refresh policy |
|---|---|
| `repo_meta` (stars, forks, description, languages) | **Cache with a TTL.** Served while younger than `PROFILE_CACHE_HOURS` (default 24 h); once stale, the next read refetches from GitHub by itself. A refetch is two cheap API calls, so this needs no user action. `refresh=True` forces it. |
| `developer_profile` | **Database-first.** Any cached profile is served regardless of age, because a rebuild costs hundreds of API calls and minutes. `GET /profiles/{u}` reports `age_hours` and `stale` (computed on read) so the UI can offer a re-sync; rebuilding is the explicit async `POST /profiles/{u}`. |

Reads never block on a live GitHub build: a profile rebuild is always the
async trigger, never a side effect of a `GET`.

An explicit `POST /analyze {"refresh": true}` means *go back to GitHub* for
everything about that repo — it pulls the cached clone, re-reads the commit
history, **and** refreshes `repo_meta` — so the dashboard header can't keep
showing the stars/description captured on the very first analysis.

## MongoStore (primary)

- Connects with `serverSelectionTimeoutMS=800` and issues a `ping` in the
  constructor — unreachable Mongo fails fast and triggers the JSON fallback.
- Collections: `commits` (one doc per commit, unique index on
  `(repo, sha)`, secondary on `(repo, date desc)`), `hotspots` (one doc per
  repo, unique on `repo`), plus one collection per generic report kind.
- Writes are replace-style (`delete_many` + `insert_many` for commits;
  `replace_one(upsert=True)` for reports) — the store always holds exactly the
  latest version of each document. There is no history-of-reports.
- `list_reports("commits")` / `("hotspots")` are Mongo aggregations returning
  per-repo counts; used by the dashboard discovery endpoint `GET /repos`.

## JsonStore (fallback)

One JSON file per (collection, key): `data/cache/<kind>/<key-slug>.json`.
Same interface, same semantics. Datetimes are encoded with the `__dt__`
marker. `list_reports` scans the directory, skipping unreadable/corrupt files
rather than failing discovery.

This is what makes the project runnable on a machine with nothing installed
but Python and GitPython — Mongo becomes an upgrade, not a prerequisite.

## Backend selection

```python
open_store(settings)   # settings.store_backend: "auto" | "mongo" | "json"
```

- `auto` (default): try Mongo, warn and fall back to JSON on any failure
  (connection refused, pymongo missing, ...).
- `mongo`: failure is a hard error.
- `json`: skip Mongo entirely.

## Other on-disk artifacts

| Path | Contents |
|---|---|
| `data/cache/clones/<owner>__<repo>/` | local clones of remote URLs |
| `data/cache/<kind>/*.json` | JsonStore documents (when Mongo is absent) |
| `data/models/hotspot_xgb.json` | trained XGBoost model + metadata (optional) |
| `data/chroma/` | persistent ChromaDB collection for Tool 3 similarity (optional) |
