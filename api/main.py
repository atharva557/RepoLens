"""GitPulse v0.4 — FastAPI backend.

A thin web layer over the engine, exactly as the roadmap frames it: completed
results are *read* from the store (MongoDB / JSON fallback), new analyses are
*triggered* into FastAPI BackgroundTasks, and the PR-review webhook deferred
from v0.3 lands here. All analysis logic stays in core/, pipeline/ and tools/.

Run from the project root:

    python -m uvicorn api.main:app --reload      # or:  python api/main.py

Interactive docs at http://127.0.0.1:8000/docs

Handlers are plain `def` functions on purpose — the engine is synchronous, and
FastAPI runs sync handlers (and sync background tasks) in its threadpool.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from api.jobs import JobRegistry
from api.webhook import REVIEW_ACTIONS, review_pr_from_payload, verify_signature
from config.settings import Settings
from core.activity import build_activity
from core.analysis import run_hotspot_analysis
from core.db import open_store
from core.github_client import get_repo_meta
from core.insights import run_repo_insights
from tools.commit_quality.runner import run_commit_quality_report
from tools.dev_profiler.runner import run_developer_profile
from tools.pr_reviewer.runner import run_pr_review

API_VERSION = "0.4"


def _env_path() -> str:
    # same convention as cli.py: fall back to the example file pre-setup
    return ".env" if os.path.isfile(".env") or not os.path.isfile(".env.example") else ".env.example"


# --------------------------------------------------------------------------- #
# request bodies
# --------------------------------------------------------------------------- #
class AnalyzeRequest(BaseModel):
    repo: str = Field(min_length=1, description="local path or GitHub URL")
    refresh: bool = False
    max_commits: int | None = None
    top: int = 15


class CommitQualityRequest(BaseModel):
    repo: str = Field(min_length=1, description="local path or GitHub URL")
    max_commits: int | None = None
    top: int = 15


# --------------------------------------------------------------------------- #
# background-job payloads (small summaries; full reports live in the store)
# --------------------------------------------------------------------------- #
def _analyze_job(req: AnalyzeRequest, settings, store) -> dict:
    result = run_hotspot_analysis(
        req.repo, settings, store,
        refresh=req.refresh, max_commits=req.max_commits, top=req.top,
    )
    return {
        "repo": result["repo"],
        "commits": result["commits"],
        "bugfix_commits": result["bugfix_commits"],
        "files_scored": result["files_scored"],
        "ml_used": result["ml_used"],
        "top": [s.to_dict() for s in result["scores"][: req.top]],
    }


def _commit_quality_job(req: CommitQualityRequest, settings, store) -> dict:
    report = run_commit_quality_report(
        req.repo, settings, store, max_commits=req.max_commits, top=req.top,
    )
    return {
        "repo": report.get("repo"),
        "commits": report["commits"],
        "avg_score": report["avg_score"],
        "good": report["good"],
        "weak": report["weak"],
    }


def _profile_job(username: str, settings, store) -> dict:
    # POST /profiles/{user} is an explicit rebuild request — skip the cache
    profile = run_developer_profile(username, settings, store, refresh=True) or {}
    return {
        "username": username,
        "primary_type": profile.get("primary_type"),
        "commits_analyzed": profile.get("commits_analyzed"),
    }


def _pr_review_job(spec: str, settings, store) -> dict:
    report = run_pr_review(spec, settings, store, post=False)
    return {"pr": spec, "level": report.get("level"), "warnings": report.get("warnings")}


def _insights_job(repo_key: str, settings, store) -> dict:
    report = run_repo_insights(repo_key, settings, store)
    return {"repo": repo_key, "bullets": len(report.get("bullets") or [])}


# --------------------------------------------------------------------------- #
# app factory
# --------------------------------------------------------------------------- #
def create_app(settings: Settings | None = None, store=None) -> FastAPI:
    """Build the app. `settings`/`store` overrides exist for tests."""
    # resolved eagerly (not in lifespan): the CORS middleware needs the origin
    # list at build time
    settings = settings or Settings.load(_env_path())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.store = store if store is not None else open_store(settings)
        app.state.jobs = JobRegistry()
        yield

    app = FastAPI(
        title="RepoLens API",
        version=API_VERSION,
        description="GitHub analytics & intelligence — read layer + analysis triggers.",
        lifespan=lifespan,
    )

    # let the dashboard (a different origin in dev, e.g. localhost:5173) call us
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def _accepted(jobs: JobRegistry, kind: str, params: dict, tasks: BackgroundTasks,
                  fn, *args) -> dict:
        job_id = jobs.create(kind, params)
        tasks.add_task(jobs.run, job_id, fn, *args)
        return {"job_id": job_id, "status": "pending", "status_url": f"/jobs/{job_id}"}

    def _require_token(settings) -> None:
        if not settings.github_token:
            raise HTTPException(400, "GITHUB_TOKEN is not configured")

    # ------------------------------------------------------------------ meta
    @app.get("/")
    def root():
        return {
            "name": "RepoLens API",
            "version": API_VERSION,
            "docs": "/docs",
            "endpoints": sorted(
                {getattr(r, "path", "") for r in app.routes if getattr(r, "path", "").count("/")}
            ),
        }

    @app.get("/health")
    def health(request: Request):
        return {"status": "ok", "store": request.app.state.store.backend,
                "version": API_VERSION}

    @app.get("/config")
    def config(request: Request):
        from dataclasses import fields

        s = request.app.state.settings
        masked = {f.name: getattr(s, f.name) for f in fields(s)}
        for secret in ("github_token", "github_webhook_secret",
                       "anthropic_api_key", "openai_api_key", "gemini_api_key"):
            masked[secret] = "***" if getattr(s, secret) else ""
        return masked

    @app.get("/test")
    def selftest(request: Request):
        """API self-test: cheap live checks of every subsystem in one call.

        Store = real save/load round-trip; LLM = provider's own availability
        check (key presence / local-server ping); similarity = which backend
        would be selected (without loading the embedding model); GitHub/webhook
        = configuration presence only, no network.
        """
        st = request.app.state
        s = st.settings
        checks: dict = {"api": "ok", "version": API_VERSION}

        try:
            stamp = datetime.now(timezone.utc).isoformat()
            st.store.save_report("api_selftest", "ping", {"stamp": stamp})
            loaded = st.store.load_report("api_selftest", "ping") or {}
            checks["store"] = {"backend": st.store.backend,
                               "ok": loaded.get("stamp") == stamp}
        except Exception as exc:
            checks["store"] = {"backend": getattr(st.store, "backend", "?"),
                               "ok": False, "error": f"{type(exc).__name__}: {exc}"}

        try:
            from core.llm import get_llm

            llm = get_llm(s)
            checks["llm"] = {"provider": llm.describe(), "available": llm.available()}
        except Exception as exc:
            checks["llm"] = {"provider": s.llm_provider, "available": False,
                             "error": f"{type(exc).__name__}: {exc}"}

        from importlib.util import find_spec

        heavy = (find_spec("chromadb") is not None
                 and find_spec("sentence_transformers") is not None)
        if s.similarity_backend == "lite":
            checks["similarity"] = "lite (selected in config)"
        elif heavy:
            checks["similarity"] = "chroma (deps installed)"
        elif s.similarity_backend == "chroma":
            checks["similarity"] = "UNAVAILABLE (chroma forced but deps missing)"
        else:
            checks["similarity"] = "lite (fallback — chroma deps not installed)"

        checks["github_token"] = bool(s.github_token)
        checks["webhook"] = {"enabled": bool(s.github_webhook_secret),
                             "auto_post": s.webhook_post_comment}
        checks["ok"] = bool(checks["store"].get("ok"))
        return checks

    # ------------------------------------------------------------------ jobs
    @app.get("/jobs/{job_id}")
    def job_status(job_id: str, request: Request):
        job = request.app.state.jobs.get(job_id)
        if job is None:
            raise HTTPException(404, f"no such job '{job_id}'")
        return job

    # ------------------------------------------------------- analysis triggers
    @app.post("/analyze", status_code=202)
    def analyze(req: AnalyzeRequest, request: Request, tasks: BackgroundTasks):
        st = request.app.state
        return _accepted(st.jobs, "analyze", {"repo": req.repo}, tasks,
                         _analyze_job, req, st.settings, st.store)

    @app.post("/commit-quality", status_code=202)
    def commit_quality(req: CommitQualityRequest, request: Request, tasks: BackgroundTasks):
        st = request.app.state
        return _accepted(st.jobs, "commit_quality", {"repo": req.repo}, tasks,
                         _commit_quality_job, req, st.settings, st.store)

    @app.post("/profiles/{username}", status_code=202)
    def build_profile(username: str, request: Request, tasks: BackgroundTasks):
        st = request.app.state
        _require_token(st.settings)
        return _accepted(st.jobs, "profile", {"username": username}, tasks,
                         _profile_job, username, st.settings, st.store)

    @app.post("/repos/{repo_key:path}/pr-reviews/{number}", status_code=202)
    def review_pr(repo_key: str, number: int, request: Request, tasks: BackgroundTasks):
        st = request.app.state
        _require_token(st.settings)
        spec = f"{repo_key}#{number}"
        return _accepted(st.jobs, "pr_review", {"pr": spec}, tasks,
                         _pr_review_job, spec, st.settings, st.store)

    # ------------------------------------------------------- discovery layer
    # what's in the store — the dashboard's landing-page data
    @app.get("/repos")
    def list_repos(request: Request):
        store = request.app.state.store
        commits = {r["key"]: r for r in store.list_reports("commits")}
        hotspots = {r["key"]: r for r in store.list_reports("hotspots")}
        quality = {r["key"]: r for r in store.list_reports("commit_quality")}
        reviews: dict[str, list[int]] = {}
        for r in store.list_reports("pr_review"):
            repo, _, num = (r.get("key") or "").rpartition("#")
            if repo and num.isdigit():
                reviews.setdefault(repo, []).append(int(num))
        out = []
        for key in sorted({*commits, *hotspots, *quality, *reviews}):
            h, q = hotspots.get(key), quality.get(key)
            out.append({
                "repo": key,
                "commits": commits.get(key, {}).get("commits", 0),
                "hotspots": ({"generated_at": h.get("generated_at"),
                              "files": h.get("files")} if h else None),
                "commit_quality": ({"generated_at": q.get("generated_at")} if q else None),
                "pr_reviews": sorted(reviews.get(key, [])),
            })
        return {"repos": out}

    @app.get("/profiles")
    def list_profiles(request: Request):
        rows = request.app.state.store.list_reports(
            "developer_profile", fields=("primary_type",))
        return {"profiles": [{"username": r["key"],
                              "generated_at": r.get("generated_at"),
                              "primary_type": r.get("primary_type")} for r in rows]}

    @app.get("/repos/{repo_key:path}/pr-reviews")
    def list_pr_reviews(repo_key: str, request: Request):
        rows = request.app.state.store.list_reports("pr_review", fields=("level",))
        out = []
        for r in rows:
            repo, _, num = (r.get("key") or "").rpartition("#")
            if repo == repo_key and num.isdigit():
                out.append({"number": int(num), "level": r.get("level"),
                            "generated_at": r.get("generated_at")})
        return {"repo": repo_key,
                "pr_reviews": sorted(out, key=lambda r: r["number"])}

    # ------------------------------------------------- dashboard read layer
    @app.get("/repos/{repo_key:path}/activity")
    def activity(repo_key: str, request: Request, days: int = 365, recent: int = 15):
        """Contributors, recent commits, daily heatmap and health score —
        aggregated from the cached commit history."""
        st = request.app.state
        commits = st.store.load_commits(repo_key)
        if not commits:
            raise HTTPException(404, f"no cached commits for '{repo_key}' — "
                                     f"POST /analyze first")
        quality = st.store.load_report("commit_quality", repo_key)
        return {"repo": repo_key,
                **build_activity(commits, days=days, recent=recent, quality=quality)}

    @app.get("/repos/{repo_key:path}/meta")
    def repo_meta(repo_key: str, request: Request, refresh: bool = False):
        """GitHub-side header metadata (description, stars, forks, languages,
        open issues) — store-cached; needs GITHUB_TOKEN for the first fetch."""
        st = request.app.state
        try:
            doc = get_repo_meta(repo_key, st.settings, st.store, refresh=refresh)
        except Exception as exc:
            raise HTTPException(502, f"GitHub metadata fetch failed: "
                                     f"{type(exc).__name__}: {exc}")
        if doc is None:
            raise HTTPException(404, f"no metadata for '{repo_key}' — needs an "
                                     f"'owner/repo' key and GITHUB_TOKEN")
        return doc

    @app.get("/repos/{repo_key:path}/insights")
    def insights(repo_key: str, request: Request):
        doc = request.app.state.store.load_report("repo_insights", repo_key)
        if doc is None:
            raise HTTPException(404, f"no insights for '{repo_key}' — "
                                     f"POST /repos/{repo_key}/insights first")
        return doc

    @app.post("/repos/{repo_key:path}/insights", status_code=202)
    def generate_insights(repo_key: str, request: Request, tasks: BackgroundTasks):
        st = request.app.state
        return _accepted(st.jobs, "insights", {"repo": repo_key}, tasks,
                         _insights_job, repo_key, st.settings, st.store)

    # ------------------------------------------------------------ read layer
    # `:path` keys accept both "owner/repo" and bare local-clone names.
    @app.get("/repos/{repo_key:path}/hotspots")
    def hotspots(repo_key: str, request: Request, top: int = 50):
        doc = request.app.state.store.load_hotspots(repo_key)
        if doc is None:
            raise HTTPException(404, f"no hotspot report for '{repo_key}' — POST /analyze first")
        doc["rows"] = (doc.get("rows") or [])[:top]
        return doc

    @app.get("/repos/{repo_key:path}/commit-quality")
    def commit_quality_report(repo_key: str, request: Request):
        doc = request.app.state.store.load_report("commit_quality", repo_key)
        if doc is None:
            raise HTTPException(404, f"no commit-quality report for '{repo_key}' — "
                                     f"POST /commit-quality first")
        return doc

    @app.get("/repos/{repo_key:path}/pr-reviews/{number}")
    def pr_review_report(repo_key: str, number: int, request: Request):
        doc = request.app.state.store.load_report("pr_review", f"{repo_key}#{number}")
        if doc is None:
            raise HTTPException(404, f"no review for {repo_key}#{number}")
        return doc

    @app.get("/profiles/{username}")
    def profile(username: str, request: Request):
        doc = request.app.state.store.load_report("developer_profile", username)
        if doc is None:
            raise HTTPException(404, f"no profile for '{username}' — POST /profiles/{username} first")
        return doc

    # --------------------------------------------------------------- webhook
    @app.post("/webhook/github", status_code=202)
    async def github_webhook(request: Request, tasks: BackgroundTasks):
        st = request.app.state
        if not st.settings.github_webhook_secret:
            raise HTTPException(503, "webhook disabled (GITHUB_WEBHOOK_SECRET not set)")

        body = await request.body()
        if not verify_signature(st.settings.github_webhook_secret, body,
                                request.headers.get("X-Hub-Signature-256")):
            raise HTTPException(401, "invalid or missing X-Hub-Signature-256")

        event = request.headers.get("X-GitHub-Event", "")
        payload = await request.json()
        if event != "pull_request":
            return {"ok": True, "ignored": f"event '{event or '?'}'"}
        action = payload.get("action", "")
        if action not in REVIEW_ACTIONS:
            return {"ok": True, "ignored": f"action '{action or '?'}'"}
        if not st.settings.github_token:
            raise HTTPException(503, "GITHUB_TOKEN not configured; cannot review PRs")

        pr = (payload.get("repository") or {}).get("full_name", "?")
        number = (payload.get("pull_request") or {}).get("number", "?")
        return _accepted(st.jobs, "webhook_pr_review", {"pr": f"{pr}#{number}"}, tasks,
                         review_pr_from_payload, payload, st.settings, st.store)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api.main:app", host="127.0.0.1", port=8000, reload=True)
