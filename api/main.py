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

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from api.auth import add_auth_routes, current_user, require_user
from api.jobs import JobRegistry
from api.webhook import REVIEW_ACTIONS, review_pr_from_payload, verify_signature
from config.settings import RUNTIME_ENV_KEYS, Settings, persist_env
from core.activity import build_activity_base, window_activity
from core.analysis import run_hotspot_analysis
from core.db import open_store, report_age_hours
from core.identity import open_identity, user_settings
from core.github_client import get_recent_pulls, get_repo_meta
from core.github_client import repo_key as canonical_repo_key
from core.insights import run_repo_insights
from core.mailer import open_mailer
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


class ConfigUpdate(BaseModel):
    """Runtime key/provider updates (PUT /config). Omitted field = unchanged;
    empty string = clear. Values are write-only — every response is masked."""
    llm_provider: str | None = None   # local | openai | claude | gemini
    llm_model: str | None = None
    local_llm_base_url: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    github_token: str | None = None


def _masked_config(s: Settings) -> dict:
    from dataclasses import fields

    import re

    masked = {f.name: getattr(s, f.name) for f in fields(s)}
    for secret in ("github_token", "github_webhook_secret",
                   "anthropic_api_key", "openai_api_key", "gemini_api_key",
                   "fernet_key", "session_secret", "github_oauth_client_secret",
                   "smtp_password"):
        masked[secret] = "***" if getattr(s, secret) else ""
    # a DATABASE_URL may embed credentials (postgresql://user:pass@host/db)
    masked["database_url"] = re.sub(r"//[^/@]+@", "//***@", s.database_url)
    return masked


# --------------------------------------------------------------------------- #
# background-job payloads (small summaries; full reports live in the store)
# --------------------------------------------------------------------------- #
def _analyze_job(req: AnalyzeRequest, settings, store, progress=None) -> dict:
    result = run_hotspot_analysis(
        req.repo, settings, store,
        refresh=req.refresh, max_commits=req.max_commits, top=req.top,
        progress=progress,
    )
    return {
        "repo": result["repo"],
        "commits": result["commits"],
        "bugfix_commits": result["bugfix_commits"],
        "files_scored": result["files_scored"],
        "ml_used": result["ml_used"],
        "top": [s.to_dict() for s in result["scores"][: req.top]],
    }


def _commit_quality_job(req: CommitQualityRequest, settings, store, progress=None) -> dict:
    report = run_commit_quality_report(
        req.repo, settings, store, max_commits=req.max_commits, top=req.top,
        progress=progress,
    )
    return {
        "repo": report.get("repo"),
        "commits": report["commits"],
        "avg_score": report["avg_score"],
        "good": report["good"],
        "weak": report["weak"],
    }


def _profile_job(username: str, settings, store, progress=None) -> dict:
    # POST /profiles/{user} is an explicit rebuild request — skip the cache
    profile = run_developer_profile(username, settings, store,
                                    refresh=True, progress=progress) or {}
    return {
        "username": username,
        "primary_type": profile.get("primary_type"),
        "commits_analyzed": profile.get("commits_analyzed"),
    }


def _pr_review_job(spec: str, settings, store, identity=None, mailer=None,
                   progress=None) -> dict:
    report = run_pr_review(spec, settings, store, post=False, progress=progress)
    from core.notify import notify_pr_review

    emailed = notify_pr_review(report, settings, identity, mailer)
    return {"pr": spec, "level": report.get("level"),
            "warnings": report.get("warnings"), "emailed": emailed}


def _insights_job(repo_key: str, settings, store, progress=None) -> dict:
    report = run_repo_insights(repo_key, settings, store, progress=progress)
    return {"repo": repo_key, "bullets": len(report.get("bullets") or [])}


# --------------------------------------------------------------------------- #
# app factory
# --------------------------------------------------------------------------- #
def create_app(settings: Settings | None = None, store=None, identity=None,
               env_path: str | None = None, mailer=None) -> FastAPI:
    """Build the app. `settings`/`store`/`identity`/`mailer`/`env_path`
    overrides exist for tests (`env_path` keeps PUT /config away from the real
    .env; `mailer` keeps signup off the network)."""
    # resolved eagerly (not in lifespan): the CORS middleware needs the origin
    # list at build time
    settings = settings or Settings.load(_env_path())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.store = store if store is not None else open_store(settings)
        app.state.store.ensure_indexes()
        # None when MULTIUSER=false; a hard requirement (Postgres) when true
        app.state.identity = identity if identity is not None else open_identity(settings)
        # always present: falls back to the console backend when SMTP is unset
        app.state.mailer = mailer if mailer is not None else open_mailer(settings)
        app.state.jobs = JobRegistry()
        yield

    app = FastAPI(
        title="RepoLens API",
        version=API_VERSION,
        description="GitHub analytics & intelligence — read layer + analysis triggers.",
        lifespan=lifespan,
    )
    # PUT /config persists here — always ".env" proper (never .env.example);
    # tests inject a scratch path so they can't touch the real file
    app.state.env_path = env_path or ".env"

    # let the dashboard (a different origin in dev, e.g. localhost:5173) call us.
    # multiuser mode pins CORS to the dashboard origin and allows credentials —
    # the session cookie must never ride on a wildcard origin (spec §8.1).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.dashboard_origin] if settings.multiuser
        else settings.cors_origins,
        allow_credentials=settings.multiuser,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def _accepted(jobs: JobRegistry, kind: str, params: dict, tasks: BackgroundTasks,
                  fn, *args) -> dict:
        job_id = jobs.create(kind, params)
        # every job fn accepts progress= and threads it into the engine, so
        # GET /jobs/{id} can report which phase (GitHub / git / ML / LLM) is running
        tasks.add_task(jobs.run, job_id, fn, *args, progress=jobs.reporter(job_id))
        return {"job_id": job_id, "status": "pending", "status_url": f"/jobs/{job_id}"}

    def _require_token(settings) -> None:
        if not settings.github_token:
            raise HTTPException(400, "GITHUB_TOKEN is not configured")

    def _effective_settings(request: Request) -> Settings:
        """Config for THIS request: in multiuser mode the signed-in user's own
        GitHub token / LLM key overlaid on the global settings (a copy — see
        core.identity.user_settings). Single-user mode returns the global
        object unchanged, so nothing about that path changes."""
        if not settings.multiuser:
            return settings
        user = current_user(request)
        if user is None:
            return settings
        return user_settings(settings, request.app.state.identity, user["id"])

    def _trigger_params(request: Request, params: dict) -> dict:
        """Multiuser: analysis triggers require a session and are attributed
        to the user (jobs.created_by, spec §6.4). Single-user: unchanged."""
        if settings.multiuser:
            user = require_user(request)
            params["created_by"] = user["github_login"] or user["email"]
        return params

    def _track_for_user(request: Request, *, repo: str | None = None,
                        profile: str | None = None) -> None:
        """Record what a signed-in user searched (multiuser only) — this is
        what scopes the Home discovery lists per user. Called after
        _trigger_params, so the session is already established."""
        if not settings.multiuser:
            return
        user = current_user(request)
        if user is None:
            return
        identity = request.app.state.identity
        if repo:
            identity.track_repo(user["id"], repo)
        if profile:
            identity.track_profile(user["id"], profile)

    def _visible_scope(request: Request) -> tuple[set | None, set | None]:
        """(repo_keys, profile_names) the requester may list; None = no limit.

        Multiuser discovery shows each user only what they themselves have
        analyzed/searched; anonymous requesters see empty lists (the login
        wall owns that UX). Single-user mode stays global."""
        if not settings.multiuser:
            return None, None
        user = current_user(request)
        if user is None:
            return set(), set()
        identity = request.app.state.identity
        return (set(identity.user_repo_keys(user["id"])),
                set(identity.user_profile_names(user["id"])))

    def _require_scope(request: Request, *, repo: str | None = None,
                       profile: str | None = None) -> None:
        """Authorize a per-key READ in multiuser mode.

        Scoping only the discovery lists was not access control: the hidden
        keys are guessable ('owner/repo'), so any stranger could read another
        account's hotspots, profiles and reports by naming them directly.
        Every keyed read now proves the requester tracks that key.

        Anonymous -> 401 (actionable: sign in). Signed in but not theirs ->
        404, identical to a key that was never analyzed, so the response
        cannot be used to enumerate what other accounts have looked at.
        Single-user mode is unaffected."""
        if not settings.multiuser:
            return
        if current_user(request) is None:
            raise HTTPException(401, "not signed in")
        visible_repos, visible_profiles = _visible_scope(request)
        if repo is not None:
            # triggers track both raw path keys and canonical 'owner/repo'
            # forms, so accept either spelling of the same repo
            if not ({repo, canonical_repo_key(repo)} & (visible_repos or set())):
                raise HTTPException(404, f"no data for '{repo}'")
        if profile is not None and profile not in (visible_profiles or set()):
            raise HTTPException(404, f"no profile for '{profile}'")

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
        return _masked_config(request.app.state.settings)

    @app.put("/config")
    def update_config(req: ConfigUpdate, request: Request):
        """Single-user runtime settings: bring-your-own LLM key + GitHub token
        from the dashboard. Changes apply to the live process immediately
        (get_llm() re-reads settings per job) and persist to .env so the CLI
        and the next server start agree. Multiuser deployments manage keys
        per-user via /api/v1/me (encrypted at rest) — this flat-file path is
        disabled there on purpose.
        """
        st = request.app.state
        s = st.settings
        if s.multiuser:
            raise HTTPException(403, "disabled in multiuser mode — manage keys "
                                     "per-user via /api/v1/me")
        changes = {k: (v or "").strip() for k, v in
                   req.model_dump(exclude_unset=True).items()}
        if not changes:
            raise HTTPException(400, "no settings provided")
        if "llm_provider" in changes:
            changes["llm_provider"] = changes["llm_provider"].lower()
            if changes["llm_provider"] not in ("local", "openai", "claude", "gemini"):
                raise HTTPException(
                    422, "llm_provider must be local | openai | claude | gemini")

        for field_name, value in changes.items():
            setattr(s, field_name, value)
        persisted = False
        try:
            persist_env({RUNTIME_ENV_KEYS[f]: v for f, v in changes.items()},
                        env_path=st.env_path)
            persisted = True
        except OSError as exc:  # applied in-memory even if the file write fails
            print(f"  [warn] settings applied but not persisted to .env: {exc}")
        return {"ok": True, "persisted": persisted, "applied": sorted(changes),
                "config": _masked_config(s)}

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

            # report the provider that would actually run this caller's jobs —
            # in multiuser that is their own BYO key, not the server's
            llm = get_llm(_effective_settings(request))
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
        checks["multiuser"] = {"enabled": s.multiuser,
                               "identity": getattr(st.identity, "backend", None)}
        # configuration only — no connection is opened and nothing is sent
        checks["mail"] = {"backend": getattr(st.mailer, "backend", None),
                          "host": getattr(st.mailer, "host", "")}
        checks["ok"] = bool(checks["store"].get("ok"))
        return checks

    # ------------------------------------------------------------------ jobs
    @app.get("/jobs/{job_id}")
    def job_status(job_id: str, request: Request):
        job = request.app.state.jobs.get(job_id)
        if job is None:
            raise HTTPException(404, f"no such job '{job_id}'")
        if settings.multiuser:
            # job ids are short random hex, but the record carries the
            # requester's identity and the analysis result — owner-only
            user = current_user(request)
            if user is None:
                raise HTTPException(401, "not signed in")
            if (job.get("params") or {}).get("created_by") not in (
                    user["github_login"], user["email"]):
                raise HTTPException(404, f"no such job '{job_id}'")
        return job

    # ------------------------------------------------------- analysis triggers
    @app.post("/analyze", status_code=202)
    def analyze(req: AnalyzeRequest, request: Request, tasks: BackgroundTasks):
        st = request.app.state
        params = _trigger_params(request, {"repo": req.repo})
        _track_for_user(request, repo=canonical_repo_key(req.repo))
        return _accepted(st.jobs, "analyze", params,
                         tasks, _analyze_job, req,
                         _effective_settings(request), st.store)

    @app.post("/commit-quality", status_code=202)
    def commit_quality(req: CommitQualityRequest, request: Request, tasks: BackgroundTasks):
        st = request.app.state
        params = _trigger_params(request, {"repo": req.repo})
        _track_for_user(request, repo=canonical_repo_key(req.repo))
        return _accepted(st.jobs, "commit_quality", params,
                         tasks, _commit_quality_job, req,
                         _effective_settings(request), st.store)

    @app.post("/profiles/{username}", status_code=202)
    def build_profile(username: str, request: Request, tasks: BackgroundTasks):
        st = request.app.state
        params = _trigger_params(request, {"username": username})
        # resolved AFTER the session check so a user's own OAuth token counts
        # toward "is a token configured" — a multiuser deployment need not
        # carry a server-wide GITHUB_TOKEN at all
        job_settings = _effective_settings(request)
        _require_token(job_settings)
        _track_for_user(request, profile=username)
        return _accepted(st.jobs, "profile", params,
                         tasks, _profile_job, username, job_settings, st.store)

    @app.post("/repos/{repo_key:path}/pr-reviews/{number}", status_code=202)
    def review_pr(repo_key: str, number: int, request: Request, tasks: BackgroundTasks):
        st = request.app.state
        spec = f"{repo_key}#{number}"
        params = _trigger_params(request, {"pr": spec})
        job_settings = _effective_settings(request)
        _require_token(job_settings)
        _track_for_user(request, repo=repo_key)
        return _accepted(st.jobs, "pr_review", params,
                         tasks, _pr_review_job, spec, job_settings, st.store,
                         st.identity, st.mailer)

    # ------------------------------------------------------- discovery layer
    # what's in the store — the dashboard's landing-page data. In multiuser
    # mode these lists are scoped per user (what THEY analyzed/searched);
    # a brand-new account correctly sees empty lists.
    @app.get("/repos")
    def list_repos(request: Request):
        store = request.app.state.store
        visible_repos, _ = _visible_scope(request)
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
            if visible_repos is not None and key not in visible_repos:
                continue
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
        _, visible_profiles = _visible_scope(request)
        rows = request.app.state.store.list_reports(
            "developer_profile", fields=("primary_type",))
        if visible_profiles is not None:
            rows = [r for r in rows if r["key"] in visible_profiles]
        return {"profiles": [{"username": r["key"],
                              "generated_at": r.get("generated_at"),
                              "primary_type": r.get("primary_type")} for r in rows]}

    @app.get("/repos/{repo_key:path}/pr-reviews")
    def list_pr_reviews(repo_key: str, request: Request):
        _require_scope(request, repo=repo_key)
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
    def activity(repo_key: str, request: Request,
                 days: int = Query(365, ge=1), recent: int = Query(15, ge=0, le=50)):
        """Contributors, recent commits, daily heatmap and health score —
        served from the cached `activity_base` aggregate (computed when the
        history is saved). Re-reading the full commit list per request made
        big repos crawl on every dashboard view."""
        st = request.app.state
        _require_scope(request, repo=repo_key)
        base = st.store.load_report("activity_base", repo_key)
        if base is None:
            # pre-aggregate-era cache: build the base once from the stored
            # commits and heal it; genuinely unknown repos still 404
            commits = st.store.load_commits(repo_key)
            if not commits:
                raise HTTPException(404, f"no cached commits for '{repo_key}' — "
                                         f"POST /analyze first")
            base = build_activity_base(commits)
            st.store.save_report("activity_base", repo_key, base)
        quality = st.store.load_report("commit_quality", repo_key)
        return {"repo": repo_key,
                **window_activity(base, days=days, recent=recent, quality=quality)}

    @app.get("/repos/{repo_key:path}/meta")
    def repo_meta(repo_key: str, request: Request, refresh: bool = False):
        """GitHub-side header metadata (description, stars, forks, languages,
        open issues) — store-cached; needs GITHUB_TOKEN for the first fetch."""
        st = request.app.state
        _require_scope(request, repo=repo_key)
        try:
            doc = get_repo_meta(repo_key, _effective_settings(request), st.store,
                                refresh=refresh)
        except Exception as exc:
            raise HTTPException(502, f"GitHub metadata fetch failed: "
                                     f"{type(exc).__name__}: {exc}")
        if doc is None:
            raise HTTPException(404, f"no metadata for '{repo_key}' — needs an "
                                     f"'owner/repo' key and GITHUB_TOKEN")
        return doc

    @app.get("/repos/{repo_key:path}/pulls")
    def recent_pulls(repo_key: str, request: Request, refresh: bool = False,
                     limit: int = Query(5, ge=1, le=20)):
        """The repo's last-N GitHub pull requests, whether Tool 3 has reviewed
        them or not — store-cached with a short TTL (PULLS_CACHE_HOURS). The
        dashboard joins these against /pr-reviews for the review chips."""
        st = request.app.state
        _require_scope(request, repo=repo_key)
        try:
            doc = get_recent_pulls(repo_key, _effective_settings(request), st.store,
                                   refresh=refresh, limit=limit)
        except Exception as exc:
            raise HTTPException(502, f"GitHub pulls fetch failed: "
                                     f"{type(exc).__name__}: {exc}")
        if doc is None:
            raise HTTPException(404, f"no pull requests for '{repo_key}' — needs "
                                     f"an 'owner/repo' key and GITHUB_TOKEN")
        age = report_age_hours(doc)
        doc["age_hours"] = round(age, 1) if age is not None else None
        return doc

    @app.get("/repos/{repo_key:path}/insights")
    def insights(repo_key: str, request: Request):
        _require_scope(request, repo=repo_key)
        doc = request.app.state.store.load_report("repo_insights", repo_key)
        if doc is None:
            raise HTTPException(404, f"no insights for '{repo_key}' — "
                                     f"POST /repos/{repo_key}/insights first")
        return doc

    @app.post("/repos/{repo_key:path}/insights", status_code=202)
    def generate_insights(repo_key: str, request: Request, tasks: BackgroundTasks):
        st = request.app.state
        params = _trigger_params(request, {"repo": repo_key})
        _track_for_user(request, repo=repo_key)
        return _accepted(st.jobs, "insights", params,
                         tasks, _insights_job, repo_key,
                         _effective_settings(request), st.store)

    # ------------------------------------------------------------ read layer
    # `:path` keys accept both "owner/repo" and bare local-clone names.
    @app.get("/repos/{repo_key:path}/hotspots")
    def hotspots(repo_key: str, request: Request, top: int = Query(50, ge=0)):
        _require_scope(request, repo=repo_key)
        doc = request.app.state.store.load_hotspots(repo_key)
        if doc is None:
            raise HTTPException(404, f"no hotspot report for '{repo_key}' — POST /analyze first")
        doc["rows"] = (doc.get("rows") or [])[:top]
        return doc

    @app.get("/repos/{repo_key:path}/commit-quality")
    def commit_quality_report(repo_key: str, request: Request):
        _require_scope(request, repo=repo_key)
        doc = request.app.state.store.load_report("commit_quality", repo_key)
        if doc is None:
            raise HTTPException(404, f"no commit-quality report for '{repo_key}' — "
                                     f"POST /commit-quality first")
        return doc

    @app.get("/repos/{repo_key:path}/pr-reviews/{number}")
    def pr_review_report(repo_key: str, number: int, request: Request):
        _require_scope(request, repo=repo_key)
        doc = request.app.state.store.load_report("pr_review", f"{repo_key}#{number}")
        if doc is None:
            raise HTTPException(404, f"no review for {repo_key}#{number}")
        return doc

    @app.get("/profiles/{username}")
    def profile(username: str, request: Request):
        # Pure read: 404 when not built yet (its detail names the POST to run).
        # Building is the async trigger POST /profiles/{username} — a GET must
        # never block on a multi-minute live build (browsers/proxies time out),
        # and the dashboard already turns this 404 into that POST + job poll.
        st = request.app.state
        _require_scope(request, profile=username)
        try:
            doc = st.store.load_report("developer_profile", username)
        except Exception as e:
            raise HTTPException(500, f"Database read failure: {e}")
        if doc is None:
            raise HTTPException(404, f"no profile for '{username}' — POST /profiles/{username} first")

        # Freshness is computed on read, never stored — a persisted "stale"
        # flag would itself go stale. Lets the UI offer "synced 3d ago — refresh"
        # (POST /profiles/{username}) instead of silently showing old data.
        age = report_age_hours(doc)
        max_age = getattr(st.settings, "profile_cache_hours", 24)
        doc["age_hours"] = round(age, 1) if age is not None else None
        doc["stale"] = bool(age is not None and age > max_age)
        return doc

    # ------------------------------------------------- auth & account (v2)
    # §7.4 endpoints; every one answers 503 while MULTIUSER=false
    add_auth_routes(app)

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
                         review_pr_from_payload, payload, st.settings, st.store,
                         st.identity, st.mailer)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api.main:app", host="127.0.0.1", port=8000, reload=True)
