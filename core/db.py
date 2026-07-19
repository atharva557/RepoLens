"""Storage layer — MongoDB primary, JSON-file fallback.

The revised architecture (GitPulse_Revised_Sections.md §6/§7) makes MongoDB the
primary datastore: hotspot reports, profiles and PR reports are document-shaped.

To keep v0.1 runnable on any machine — including before MongoDB is installed —
`open_store()` returns a `MongoStore` when a server is reachable and otherwise
transparently falls back to a `JsonStore` that persists to `cache_dir`. Both
expose the same small interface, so the rest of the pipeline is storage-agnostic.

pymongo is imported lazily.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Iterable


# --------------------------------------------------------------------------- #
# serialization helpers (datetimes <-> ISO strings for the JSON backend)
# --------------------------------------------------------------------------- #
def report_age_hours(doc: dict | None) -> float | None:
    """Age of a stored report in hours (via its generated_at), or None."""
    gen = (doc or {}).get("generated_at")
    if not isinstance(gen, datetime):
        return None
    if gen.tzinfo is None:  # defensive: treat naive timestamps as UTC
        gen = gen.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - gen).total_seconds() / 3600.0


def _encode(obj):
    if isinstance(obj, datetime):
        return {"__dt__": obj.astimezone(timezone.utc).isoformat()}
    if isinstance(obj, dict):
        return {k: _encode(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_encode(v) for v in obj]
    return obj


def _decode(obj):
    if isinstance(obj, dict):
        if "__dt__" in obj and len(obj) == 1:
            return datetime.fromisoformat(obj["__dt__"])
        return {k: _decode(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decode(v) for v in obj]
    return obj


class JsonStore:
    """File-backed fallback store. One JSON file per (collection, repo)."""

    backend = "json"

    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)
        self.collection_mapping = {
            "repo_insights": "insights",
            "developer_profile": "profiles",
            "commit_quality": "quality_reports",
            "configs": "configs"
        }

    def _slug(self, repo_key: str) -> str:
        return repo_key.replace("/", "__").replace("\\", "__")

    def _path(self, collection: str, repo_key: str) -> str:
        coll_name = self.collection_mapping.get(collection, collection)
        d = os.path.join(self.root, coll_name)
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, f"{self._slug(repo_key)}.json")

    def ensure_indexes(self) -> None:  # no-op for files
        pass

    def save_commits(self, repo_key: str, commits: list[dict]) -> int:
        with open(self._path("commits", repo_key), "w", encoding="utf-8") as fh:
            json.dump(_encode(commits), fh)
        return len(commits)

    def load_commits(self, repo_key: str) -> list[dict]:
        p = self._path("commits", repo_key)
        if not os.path.isfile(p):
            return []
        with open(p, encoding="utf-8") as fh:
            return _decode(json.load(fh))

    def save_hotspots(self, repo_key: str, rows: list[dict]) -> int:
        doc = {"repo": repo_key, "generated_at": datetime.now(timezone.utc), "rows": rows}
        with open(self._path("hotspots", repo_key), "w", encoding="utf-8") as fh:
            json.dump(_encode(doc), fh, indent=2)
        return len(rows)

    def load_hotspots(self, repo_key: str) -> dict | None:
        p = self._path("hotspots", repo_key)
        if not os.path.isfile(p):
            return None
        with open(p, encoding="utf-8") as fh:
            return _decode(json.load(fh))

    def save_report(self, kind: str, key: str, doc: dict) -> None:
        payload = {"key": key, "generated_at": datetime.now(timezone.utc), **doc}
        with open(self._path(kind, key), "w", encoding="utf-8") as fh:
            json.dump(_encode(payload), fh, indent=2)

    def load_report(self, kind: str, key: str) -> dict | None:
        p = self._path(kind, key)
        if not os.path.isfile(p):
            return None
        with open(p, encoding="utf-8") as fh:
            return _decode(json.load(fh))

    def list_reports(self, kind: str, fields: tuple = ()) -> list[dict]:
        """Small discovery summaries: one row per stored document.

        "commits" rows carry a count; "hotspots" rows carry the file count;
        report rows carry key + generated_at (+ any requested `fields`).
        """
        coll_name = self.collection_mapping.get(kind, kind)
        d = os.path.join(self.root, coll_name)
        if not os.path.isdir(d):
            return []
        out = []
        for name in sorted(os.listdir(d)):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(d, name), encoding="utf-8") as fh:
                    doc = _decode(json.load(fh))
            except (OSError, ValueError):
                continue  # unreadable/corrupt cache file — skip, don't fail discovery
            fallback_key = name[:-5].replace("__", "/")
            if kind == "commits":  # commits files are bare lists
                out.append({"key": fallback_key, "commits": len(doc)})
                continue
            row = {"key": doc.get("key") or doc.get("repo") or fallback_key,
                   "generated_at": doc.get("generated_at")}
            if kind == "hotspots":
                row["files"] = len(doc.get("rows") or [])
            for f in fields:
                if f in doc:
                    row[f] = doc[f]
            out.append(row)
        return out


class MongoStore:
    """MongoDB-backed store (primary)."""

    backend = "mongo"

    def __init__(self, uri: str, dbname: str, timeout_ms: int = 800):
        from pymongo import MongoClient  # lazy import

        # tz_aware: commit dates must round-trip as aware UTC datetimes — the
        # feature extractor subtracts them from datetime.now(timezone.utc).
        self.client = MongoClient(uri, serverSelectionTimeoutMS=timeout_ms, tz_aware=True)
        try:
            self.client.admin.command("ping")  # raises if unreachable
        except Exception as e:
            raise ConnectionError(
                f"Failed to connect to MongoDB at {uri}. "
                f"Ensure the MongoDB service is installed and running. Error: {e}"
            ) from e
        self.db = self.client[dbname]
        self.collection_mapping = {
            "repo_insights": "insights",
            "developer_profile": "profiles",
            "commit_quality": "quality_reports",
            "configs": "configs"
        }

    def ensure_indexes(self) -> None:
        from pymongo import ASCENDING, DESCENDING

        self.db.commits.create_index(
            [("repo", ASCENDING), ("sha", ASCENDING)], unique=True
        )
        self.db.commits.create_index([("repo", ASCENDING), ("date", DESCENDING)])
        self.db.hotspots.create_index([("repo", ASCENDING)], unique=True)
        self.db.insights.create_index([("key", ASCENDING)], unique=True)
        self.db.profiles.create_index([("key", ASCENDING)], unique=True)
        self.db.quality_reports.create_index([("key", ASCENDING)], unique=True)
        self.db.configs.create_index([("key", ASCENDING)], unique=True)
        self.db.recent_pulls.create_index([("key", ASCENDING)], unique=True)
        self.db.activity_base.create_index([("key", ASCENDING)], unique=True)

    def save_commits(self, repo_key: str, commits: list[dict]) -> int:
        coll = self.db.commits
        coll.delete_many({"repo": repo_key})
        if commits:
            coll.insert_many([{**c, "repo": repo_key} for c in commits])
        return len(commits)

    def load_commits(self, repo_key: str) -> list[dict]:
        out = []
        for doc in self.db.commits.find({"repo": repo_key}, {"_id": 0, "repo": 0}):
            out.append(doc)
        return out

    def save_hotspots(self, repo_key: str, rows: list[dict]) -> int:
        self.db.hotspots.replace_one(
            {"repo": repo_key},
            {
                "repo": repo_key,
                "generated_at": datetime.now(timezone.utc),
                "rows": rows,
            },
            upsert=True,
        )
        return len(rows)

    def load_hotspots(self, repo_key: str) -> dict | None:
        doc = self.db.hotspots.find_one({"repo": repo_key}, {"_id": 0})
        return doc

    def save_report(self, kind: str, key: str, doc: dict) -> None:
        coll_name = self.collection_mapping.get(kind, kind)
        self.db[coll_name].replace_one(
            {"key": key},
            {"key": key, "generated_at": datetime.now(timezone.utc), **doc},
            upsert=True,
        )

    def load_report(self, kind: str, key: str) -> dict | None:
        coll_name = self.collection_mapping.get(kind, kind)
        return self.db[coll_name].find_one({"key": key}, {"_id": 0})

    def list_reports(self, kind: str, fields: tuple = ()) -> list[dict]:
        """Same discovery shape as JsonStore.list_reports (see there)."""
        if kind == "commits":
            rows = self.db.commits.aggregate([
                {"$group": {"_id": "$repo", "commits": {"$sum": 1}}},
                {"$sort": {"_id": 1}},
            ])
            return [{"key": r["_id"], "commits": r["commits"]} for r in rows]
        if kind == "hotspots":
            rows = self.db.hotspots.aggregate([
                {"$project": {"_id": 0, "key": "$repo", "generated_at": 1,
                              "files": {"$size": {"$ifNull": ["$rows", []]}}}},
                {"$sort": {"key": 1}},
            ])
            return list(rows)
        coll_name = self.collection_mapping.get(kind, kind)
        proj = {"_id": 0, "key": 1, "generated_at": 1, **{f: 1 for f in fields}}
        return sorted(self.db[coll_name].find({}, proj), key=lambda r: r.get("key") or "")


def open_store(settings) -> JsonStore | MongoStore:
    """Pick a store backend based on settings and availability."""
    backend = getattr(settings, "store_backend", "auto")

    if backend in ("auto", "mongo"):
        try:
            store = MongoStore(settings.mongodb_uri, settings.mongodb_db)
            return store
        except Exception as exc:  # connection refused, no pymongo, etc.
            if backend == "mongo":
                raise
            print(
                f"  [warn] MongoDB unavailable ({type(exc).__name__}); "
                f"falling back to JSON cache at {settings.cache_dir}"
            )

    return JsonStore(settings.cache_dir)
