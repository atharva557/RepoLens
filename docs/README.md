# RepoLens — Technical Documentation

This folder explains **how RepoLens works internally** — the architecture, the
data model, each tool's algorithm, and the API. It complements the top-level
[README.md](../README.md) (usage / quick start) and
[PROJECT_OVERVIEW.md](../PROJECT_OVERVIEW.md) (executive summary).

## The 60-second mental model

RepoLens reads a repository's **git history**, classifies which commits were
**bug fixes**, aggregates that into **per-file features**, and answers four
questions on top of that one shared pipeline:

| Tool | Question | Doc |
|---|---|---|
| 1 — Bug Hotspot Predictor | Which files will break next? | [03-tool-1-bug-hotspots.md](03-tool-1-bug-hotspots.md) |
| 2 — Developer Skill Profiler | What kind of developer is `@user`? | [04-tool-2-developer-profiler.md](04-tool-2-developer-profiler.md) |
| 3 — PR Review Assistant | Is this pull request risky? | [05-tool-3-pr-reviewer.md](05-tool-3-pr-reviewer.md) |
| 4 — Commit Message Quality | Are our commit messages useful? | [06-tool-4-commit-quality.md](06-tool-4-commit-quality.md) |

Everything is exposed three ways: an **interactive CLI** (`cli.py`), a
**FastAPI backend** (`api/`), and a **React dashboard** (`frontend/`).
Results persist in **MongoDB** (with a transparent JSON-file fallback).

Two design principles show up everywhere:

1. **Explainability over black-box accuracy** — every score ships with
   plain-English reasons; the primary hotspot signal is a transparent formula,
   not a trained model.
2. **Graceful degradation** — every heavy dependency (MongoDB, XGBoost,
   ChromaDB, any LLM) is optional; the system picks the best available backend
   at runtime and announces which one it picked.

## Reading order

| # | Doc | Covers |
|---|---|---|
| 01 | [Architecture](01-architecture.md) | Layers, end-to-end data flow, fallback design, repo layout |
| 02 | [Data & storage](02-data-and-storage.md) | The commit dict, repo keys, the store interface, MongoDB vs JSON |
| 03 | [Tool 1 — Bug Hotspots](03-tool-1-bug-hotspots.md) | Classification → features → weighted score → explanations → optional XGBoost |
| 04 | [Tool 2 — Developer Profiler](04-tool-2-developer-profiler.md) | GitHub activity fetch, rule-based type classification, profile assembly |
| 05 | [Tool 3 — PR Reviewer](05-tool-3-pr-reviewer.md) | Mechanical risk checks, diff similarity to past bugs, report building |
| 06 | [Tool 4 — Commit Quality](06-tool-4-commit-quality.md) | 0–10 message scoring, repo aggregation, LLM rewrites |
| 07 | [LLM & similarity engines](07-llm-and-similarity.md) | Pluggable LLM providers; ChromaDB vs TF-IDF similarity backends |
| 08 | [Web API](08-api.md) | FastAPI layer, background jobs, GitHub webhook, dashboard endpoints |
| 09 | [Frontend](09-frontend.md) | React dashboard: pages, API client conventions, job polling |
| 10 | [Configuration](10-configuration.md) | Every `.env` knob with its default and effect |
| 11 | [Testing](11-testing.md) | The network-free suites and the fakes that make them possible |
| 12 | [Identity plane (Postgres)](12-identity-postgres.md) | Multi-user slice: email/password + OAuth login, sessions, encrypted tokens, per-user scoping, audit — `MULTIUSER=true` |
