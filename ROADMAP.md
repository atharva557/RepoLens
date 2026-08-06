# RepoLens — Roadmap

This is the working roadmap. It supersedes §15 of `../GitPulse_Revised_Sections.md`
and reflects the architecture as actually built. For shipped detail per version,
see [CHANGELOG.md](CHANGELOG.md).

Legend: ✅ done · 🔜 next · ⏳ planned

---

## Architecture decisions baked in (deviations from the original guide)

These choices carry across every version below:

- **MongoDB** is the datastore (not SQLite), with a transparent **JSON-file fallback**
  so everything runs before Mongo is installed.
- **Bug Hotspot = a transparent recency-weighted score**, not a trained classifier.
  XGBoost survives only as an **optional "second opinion"** (training-free scorer is primary).
- **LLM is a pluggable provider** — local **LM Studio** by default, or bring your own
  **Claude / OpenAI / Gemini** key. Always optional; rule-based features work without it.
- **Developer Skill Profiler is per-GitHub-user across repos** (the guide's full framing).
- **The GitHub Action is dropped** — a single webhook path handles PR review automation.
- **Interface is an interactive CLI** plus a React dashboard (shipped in v0.4/v1.0).

---

## ✅ v0.1 — Foundation

**Adds: the data pipeline + Tool 1 (Bug Hotspot Predictor) behind a CLI.**

- GitHub/git client with MongoDB caching (+ JSON fallback).
- Bug-fix commit classification (keyword detection).
- **Tool 1 — Bug Hotspot Predictor**: recency-weighted risk score
  (`0.40·bug + 0.25·churn + 0.15·authors + 0.20·complexity`) with plain-English reasons.
- Interactive CLI.
- *Bonus (pulled forward):* optional **XGBoost "second opinion"** — temporal labeling
  (no leakage), per-repo percentile normalization, language-agnostic features, trained
  once across pooled repos, with cross-repo + held-out-language evaluation.

## ✅ v0.2 — Intelligence Layer

**Adds: the LLM + two more tools.**

- **Pluggable LLM provider** (`core/llm.py`): `local` (LM Studio) · `openai` · `claude`
  · `gemini`. Optional and graceful; `test-llm` checks connectivity.
- **Tool 4 — Commit Message Quality Analyzer**: rule-based 0–10 scoring (length,
  vagueness, imperative verb, "why" context, issue refs), per-contributor health,
  repo trends, common bad patterns, + optional LLM rewrites (from the diff).
- **Tool 2 — Developer Skill Profiler** (per-user): type distribution over
  Bug Fixer / Feature Builder / Refactorer / Reviewer / Documentation Writer / Architect,
  top languages, commit-message quality (reuses Tool 4), review participation,
  + optional LLM summary of PR descriptions.

## ✅ v0.3 — PR Review

**Adds: Tool 3 (PR Review Assistant) and the embedding/similarity layer.**

- **Embedding pipeline**: index the repo's past bug-fix diffs. Pluggable
  `SimilarityIndex` — sentence-transformers + ChromaDB when installed, stdlib
  TF-IDF fallback otherwise.
- **Tool 3 — PR Review Assistant**: for a PR, a pre-review report — file risk
  (queries Tool 1's hotspot scores), missing-tests heuristic, change focus/size,
  **diff-similarity to past bug diffs**, and an **LLM diff summary** (v0.2 provider).
- **Delivery**: on-demand CLI `review-pr owner/repo#N` + opt-in GitHub PR-comment
  posting. The webhook receiver moves to v0.4 (with FastAPI).
- *Cleanup done:* bug history is now credited only to source files, so docs/config
  (`.md`, `.toml`) stop producing false-positive hotspots.

## ✅ v0.4 — API + Dashboard

**Adds: a web backend and the unified visual dashboard.**

- ✅ **FastAPI** backend reading completed results from MongoDB (thin read layer;
  analysis stays in the engine), with `BackgroundTasks` for long pulls (`api/`).
- ✅ The **PR-review webhook** deferred from v0.3 (auto-trigger Tool 3 on PR
  open/update; HMAC-verified; opt-in comment posting).
- ✅ **React dashboard** (Vite + React 19 + Tailwind 4 + Recharts): Home, Dashboard,
  Bug Hotspots, Developer Profile, PR Review, Status, Settings, Preferences.

## ✅ v1.0 — Production-Ready Release

**Adds: multi-user support, email verification, evaluation, and hardening.**

- ✅ **Multi-user identity plane** (PostgreSQL, `MULTIUSER=true`): accounts, sessions,
  GitHub OAuth + email/password login, Fernet-encrypted tokens, per-user credential
  overlay, audit log — off by default, one env var to enable.
- ✅ **Email verification (OTP)**: signup requires a 6-digit code, single-use,
  10-minute TTL, 5-attempt lockout; stdlib SMTP with a console fallback for local dev.
- ✅ **PR review email delivery**: webhook reviews email all repo trackers automatically;
  dashboard reviews email on user request (`?email=true` / Email button).
- ✅ **Temporal hold-out evaluation** (CLI option 10): precision@k of the hotspot score
  against a future bug window it never saw — on nodejs/node: P@5 = 0.850 (~115× lift).
- ✅ **Performance trilogy**: one-shot `git log --numstat` parse (~40× faster history
  reads), 8-worker threaded profiler fetches, per-repo similarity corpus with
  fingerprint-based reuse (fixes cross-repo concurrency bug).
- ✅ **Settings + Preferences pages**, BYO-key drawer, session-scoped API cache,
  activity base pre-aggregation (367ms → 3ms per dashboard load).
- ✅ **13 suites, 124 tests** — all network- and DB-free by default.

---

## 🔜 Post-v1.0

- Per-repo read ACLs and private-repo ownership (deferred from v2 slice)
- Quotas and rate limiting per user
- OAuth scope escalation for comment posting
- Developer-profile comparison view (two users side by side)
- Weight tuning for the hotspot formula via held-out evaluation data

---

## Future ideas

Slack integration · IDE plugin (file risk in VS Code) · org-level analytics ·
trend alerts (notify on risk-score jumps) · API export · LLM response caching ·
background worker queue (Celery + Redis) if BackgroundTasks is outgrown.
