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

Remote URLs are cloned once into `data/cache/clones/<name>` by
`ensure_local_clone()`; subsequent runs reuse (and fetch-update) the clone.

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
store.load_commits(repo_key)            # [] if none

# Tool 1 reports (dedicated shape: {repo, generated_at, rows})
store.save_hotspots(repo_key, rows)
store.load_hotspots(repo_key)           # None if none

# everything else: generic (kind, key) documents
store.save_report(kind, key, doc)       # wraps as {key, generated_at, **doc}
store.load_report(kind, key)            # None if none
store.list_reports(kind, fields=())     # small discovery summaries
```

### Report kinds in use

| `kind` | `key` | Written by | Read by |
|---|---|---|---|
| `commit_quality` | repo key | Tool 4 runner | CLI, `GET /repos/{key}/commit-quality`, health score |
| `developer_profile` | GitHub username | Tool 2 runner | CLI, `GET /profiles/{user}` |
| `pr_review` | `owner/repo#N` | Tool 3 runner / webhook | CLI, `GET /repos/{key}/pr-reviews/{n}` |
| `repo_insights` | repo key | `core/insights.py` | `GET /repos/{key}/insights` |
| `repo_meta` | repo key | `core/github_client.get_repo_meta` | `GET /repos/{key}/meta` |
| `api_selftest` | `"ping"` | `GET /test` round-trip check | — |

`report_age_hours(doc)` computes a report's age from its `generated_at`;
Tool 2 and repo metadata use it as a TTL (`PROFILE_CACHE_HOURS`, default 24 h)
to serve cached documents instead of re-hitting the GitHub API.

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
| `data/cache/clones/<repo>/` | local clones of remote URLs |
| `data/cache/<kind>/*.json` | JsonStore documents (when Mongo is absent) |
| `data/models/hotspot_xgb.json` | trained XGBoost model + metadata (optional) |
| `data/chroma/` | persistent ChromaDB collection for Tool 3 similarity (optional) |
