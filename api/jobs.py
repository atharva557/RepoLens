"""In-process job registry for BackgroundTasks runs (v0.4).

The stores persist the *results* (hotspot reports, PR reviews, profiles); this
only tracks the transient pending/running/done/failed state of background jobs,
so it lives in memory and resets on restart — enough for the single-process
uvicorn deployment the roadmap calls for. A worker queue (Celery + Redis) is
listed as a post-submission idea if this is outgrown.

Pure stdlib.
"""
from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobRegistry:
    """Thread-safe, bounded map of job_id -> status dict."""

    def __init__(self, max_jobs: int = 200):
        self._lock = threading.Lock()
        self._jobs: OrderedDict[str, dict] = OrderedDict()
        self._max = max_jobs

    def create(self, kind: str, params: dict | None = None) -> str:
        job_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._jobs[job_id] = {
                "id": job_id,
                "kind": kind,
                "params": params or {},
                "status": "pending",
                "created_at": _now(),
                "finished_at": None,
                "progress": None,   # latest {phase, pct, detail, updated_at}
                "result": None,
                "error": None,
            }
            while len(self._jobs) > self._max:
                self._jobs.popitem(last=False)
        return job_id

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def _update(self, job_id: str, **changes) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.update(changes)

    def reporter(self, job_id: str):
        """A progress callback bound to a job (see core/progress.py).

        Threaded into the engine so `GET /jobs/{id}` can say *which* stage a
        long run is in — cloning from GitHub vs scoring vs LLM."""
        def report(phase: str, pct: int | None = None, detail: str = "") -> None:
            self._update(job_id, progress={"phase": phase, "pct": pct,
                                           "detail": detail, "updated_at": _now()})
        return report

    def run(self, job_id: str, fn, *args, **kwargs) -> None:
        """Execute `fn` and record its outcome. Designed for BackgroundTasks.

        SystemExit is caught too — the engine raises it for operational errors
        (e.g. missing token), and it must not kill the server process.
        """
        self._update(job_id, status="running")
        try:
            result = fn(*args, **kwargs)
        except (Exception, SystemExit) as exc:
            self._update(
                job_id, status="failed", finished_at=_now(),
                error=f"{type(exc).__name__}: {exc}",
            )
            return
        self._update(job_id, status="done", finished_at=_now(), result=result)
