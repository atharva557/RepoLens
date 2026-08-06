# RepoLens — Technical Deep Dive

*The complete engineering picture: architecture, every major decision with
its alternatives, the data model, security posture, testing philosophy — and
a candid map of where a live laptop demo can stall. Module-level detail lives
in [docs/](docs/README.md); this document is the "why" layer above it.*

---

## 1. System at a glance

| | |
|---|---|
| Engine | ~6,800 lines of Python 3.11+ excl. tests (stdlib-first; every heavy dep optional + lazy-imported) |
| Interfaces | interactive CLI · FastAPI backend (32 endpoints) · React 19 + Vite dashboard (~5,500 lines JS/JSX) |
| Storage | MongoDB (analytics documents) · PostgreSQL (identity plane, opt-in) · ChromaDB (vectors) · JSON files (zero-install fallback) |
| ML/AI | XGBoost second-opinion classifier (trained) · sentence-transformers embeddings (pretrained) · pluggable LLM (LM Studio / OpenAI / Claude / Gemini — optional garnish) |
| Tests | 124 tests, 13 suites, network- and DB-free via in-process fakes (5 opt-in Postgres tests skip by default) |
| Status | v1.0 — production-ready: multi-user identity plane, email verification, temporal evaluation, full React dashboard |

Four tools on one shared pipeline: **Bug Hotspot Predictor**, **PR Review
Assistant**, **Developer Skill Profiler**, **Commit Message Quality
Analyzer**. One repo analysis feeds all four.

## 2. Architecture

Strict four-layer stack; higher layers import lower, never the reverse:

```
INTERFACES   cli.py · api/ (FastAPI + webhook + auth) · frontend/ (React)
TOOLS        tools/{bug_hotspot, pr_reviewer, dev_profiler, commit_quality}
PIPELINE     pipeline/ — fetch → classify → extract features (shared steps)
CORE         git_client · github_client · db · identity · llm · embeddings
             paths · analysis · activity · insights · progress
```

**The central data shape** is the commit dict (`{sha, author, email, date
(aware-UTC), message, is_bugfix, files:[{path, insertions, deletions}]}`).
Everything consumes it: Tool 1 aggregates it into per-file features, Tool 4
scores its messages, Tool 3 builds its similarity corpus from it, the
dashboard's activity/health endpoints re-aggregate it. **A repo is read once,
cached in the store, and never re-read until an explicit refresh** —
database-first is a system-wide invariant (a `GET` never silently calls
GitHub; the dashboard's "Sync" button maps to `refresh=true` triggers).

The CLI and API call the *same* orchestration functions; the API adds only
HTTP framing, an in-memory job registry with structured progress
(`{phase, pct, detail}` — phases are worded to answer "what is slow":
`cloning repository (GitHub)`, `embedding bug-fix diffs (ML)`, `summarizing
the diff (LLM)`), and an HMAC-verified GitHub webhook.

## 3. Technology choices — what, why, and the rejected alternative

**Python + GitPython** (history source). Reading a *local clone* is fast,
token-free, and rate-limit-free; the GitHub REST API is used only to obtain
clones, PR metadata, and per-user activity. *Alternative rejected:* pure
GitHub API — 5,000 req/hr would cap analysis at toy sizes. *Known cost:*
GitPython's `commit.stats` spawns one `git diff` subprocess per commit (see
§6).

**MongoDB** (analytics store). Every result is a nested document (a hotspot
report = repo key + rows with components/reasons; a profile = distributions +
heatmaps) and the access pattern is pure key lookup — no joins anywhere.
Write path is `replace_one(upsert=True)`: the store always holds exactly the
latest report. *Alternatives rejected:* SQLite (original plan — would mean
JSON blobs in columns or pointless normalization); Postgres-for-everything
(JSONB could do it, but 100% of analytics data is document-shaped and the
JSON-file fallback shares Mongo's model 1:1). *Consequence accepted:* no
history-of-reports, last writer wins.

**PostgreSQL** (identity plane, `MULTIUSER=true` only). Accounts, sessions,
repo ownership, encrypted secrets, audit log — relational, transactional,
FK-cascading. This is deliberate polyglot persistence: *choose per workload*.
Identity has **no file fallback** — a silent auth downgrade would be a
vulnerability, so Postgres is a hard requirement in multiuser mode (opposite
of the Mongo→JSON philosophy, on purpose).

**ChromaDB + sentence-transformers** (`all-MiniLM-L6-v2`) for Tool 3's
"does this diff resemble past bug fixes?" — real semantic similarity from a
pretrained 22M-param encoder, persisted vectors, cosine space.
*Alternative shipped as fallback:* a pure-stdlib TF-IDF cosine index
(`LiteIndex`) — same interface, zero install, so Tool 3 works on a bare
machine. *Alternative rejected:* pgvector (consolidation stretch-goal, not
worth the coupling now).

**XGBoost** (optional trained "second opinion"). Gradient-boosted trees over
language-agnostic process metrics. The legitimacy is in the training design,
not the library: **temporal snapshot labeling** (features strictly before a
cutoff, label = bug fix in the window after — no leakage), **per-repo
percentile normalization** (a 90th-percentile churn means the same in a
100-commit and a 5,000-commit repo — this is what makes cross-repo and
cross-language pooling valid), **GroupKFold-by-repo AUC** plus held-out-
language AUC, and a `reliable: False` refusal below a positive-sample floor.
*Alternative rejected:* training a per-repo classifier as the primary scorer
— tiny, imbalanced, leaky data (see decision #1 below).

**Pluggable LLM layer** (`LLM_PROVIDER` = local | openai | claude | gemini).
LM Studio/OpenAI/Gemini share one OpenAI-compatible client; Claude uses the
anthropic SDK. Local-first default keeps the privacy story honest and the
cost zero; `LOCAL_LLM_AUTOLOAD=true` makes the local provider resolve and
JIT-load a model when the server is up but empty. *Alternative rejected:*
hardcoding one vendor — the provider is a constructor-time choice, and the
`FakeProvider` twin makes every LLM feature testable offline.

**FastAPI** (web layer). Pydantic validation, auto Swagger at `/docs`,
BackgroundTasks for job execution, sync handlers on the threadpool (the
engine is synchronous — pretending otherwise with async wrappers would gain
nothing). *Alternatives rejected:* Flask (no typed validation/docs for free),
Django (an ORM and admin we'd fight — our data layer is custom by design).

**Keyword bug-fix classifier** (word-boundary regex over `fix, bug, resolve,
patch, hotfix, closes` — the SZZ starting point). Auditable, testable
("fix" matches "fixes" but never "prefix"), zero deps. *Known weakness and
plan:* it's the weakest scientific link (misses keyword-less fixes); the
evaluated upgrade path is a fine-tuned small transformer classifier behind
the same `classify_commits()` interface, measured against this baseline.

## 4. The decisions that define the system

1. **The hotspot score is a transparent formula, not a trained model.**
   `0.40·bug (recency-decayed, half-life 30d) + 0.25·churn + 0.15·authors +
   0.20·size`, min-max normalized per repo. Training on one repo's history
   suffers label leakage and tiny data; a formula needs no training, works on
   50-commit repos, and every score ships reasons. Weights follow the
   defect-prediction literature; ML survives as an *advisory* column.

2. **Graceful degradation everywhere.** Mongo→JSON, Chroma→TF-IDF,
   XGBoost→formula-only, LLM→feature skipped, radon→LOC. All heavy imports
   are lazy; every run announces its backend (`[backend] store: mongodb
   (primary)`). Consequence: the demo can't be killed by missing
   infrastructure, and the test suite runs anywhere.

3. **Bug credit only for source files** (and, post-calibration, hotspot
   *risk-matching* and the *similarity corpus* are source-only too). A "fix
   typo" commit touching `CHANGES.rst` is not bug signal. This was validated
   the hard way: a real Flask PR rated falsely HIGH; after the filters and a
   graded risk level (HIGH now requires **two independent signals**), the
   same PR correctly reads LOW — with regression tests pinning it.

4. **LLM as garnish, never judge.** No score, rank, or risk level is
   LLM-decided; the LLM writes prose (rewrites, summaries, insight bullets)
   over deterministic results. This keeps outputs reproducible and the
   explainability claim intact.

5. **Security discipline in the identity plane:** *hash what you check,
   encrypt what you use.* Session cookies → SHA-256 hashes only (httpOnly,
   SameSite=Lax, 30-day sliding); GitHub/LLM tokens → Fernet ciphertext,
   decrypted at call time, every save/revoke audited; CSRF via a required
   custom header; OAuth state nonces; auth routes answer 503 while
   `MULTIUSER=false` (same gating pattern as the webhook-without-secret).

6. **In-memory JobRegistry, single process — knowingly.** Results persist in
   the store; only transient job state is in memory. Cost: exactly one
   uvicorn worker (jobs and OAuth state don't cross workers) and job status
   loss on restart. Upgrade path if outgrown: Celery + Redis.

## 5. Where a live demo on a laptop will slow down (and what to do)

Ranked by pain, with the honest mechanism behind each:

| # | Slow spot | Mechanism | Magnitude | Demo mitigation |
|---|---|---|---|---|
| 1 | **First-time developer profile** | PyGithub lazily fetches **one HTTPS request per commit** for file stats: up to 15 repos × 100 commits ≈ 1,500 sequential calls, plus 4 slow search-API calls | **6–10 min**, burns ~30% of the hourly token limit | Pre-build the profile (DB-first serves it instantly forever after); or set `PROFILE_MAX_REPOS=5`, `PROFILE_MAX_COMMITS_PER_REPO=30` → under a minute |
| 2 | **First clone of a big repo** | plain network transfer of the full history | ~1–5 min for flask-sized; worse on event Wi-Fi | Pre-clone into `data/cache/clones/`; the progress bar (`cloning repository (GitHub) — receiving objects, 60%`) keeps the audience informed if you must do it live |
| 3 | **First history pull** | GitPython spawns one `git diff --numstat` **subprocess per commit**; process spawn is expensive on Windows | ~30–90 s for 400 commits | Use `max_commits`; cached commits skip this entirely; planned fix: single `git log --numstat` parse (10–50×) |
| 4 | **First Tool 3 run of the session** | sentence-transformers weights load (~5–10 s), then the bug-diff corpus is re-embedded **every review** (per-repo reuse is a pending fix); plus `git show` per bug-fix commit | 15–40 s per review | Run one throwaway review before the demo (warms the model); review the same repo you analyzed |
| 5 | **LLM latency** | local model generation is tokens/sec-bound; reasoning models spend budget "thinking" (insights already raise `max_tokens` for this) | 5–30 s per summary/insight | Keep LM Studio open with the model loaded (or rely on `LOCAL_LLM_AUTOLOAD`); generate insights before the demo — they're cached |
| 6 | **Fresh-machine cold start** | first Chroma use downloads the embedding model from Hugging Face (hundreds of MB); `pip install` of torch is GB-scale | one-time, minutes→hours on bad Wi-Fi | Never demo on a machine that hasn't run Tool 3 once |
| 7 | Mongo unreachable | 800 ms ping timeout, then JSON fallback | sub-second, self-announcing | Non-issue — arguably a feature to show |

**Pre-demo checklist:** analyze the demo repos the night before (hotspots +
commit-quality + insights cached), build the profile you'll show, run one PR
review to warm the embedding model, keep LM Studio running with a loaded
model, start exactly one uvicorn worker, and demo *reads* first (instant,
database-first) before triggering one live analysis on a **small** repo to
show the progress phases.

## 6. Known bottlenecks (identified, quantified, fix designed)

All three share one pattern — *a hidden per-item network call or subprocess
inside a loop*: (1) profiler's per-commit GitHub fetch → fix: thread-pool the
detail fetches (~8×); (2) GitPython per-commit stats → fix: one-shot
`git log --numstat` parse; (3) Tool 3 similarity index rebuilt per review in
a **single shared Chroma collection** — which is also a concurrency bug (two
simultaneous reviews of different repos would cross-contaminate scores) →
fix: one collection per repo, fingerprinted by newest cached SHA, rebuilt
only when the corpus changed.

## 7. Security posture — honest boundaries

Single-user mode is built for localhost: no auth by default, CORS `*`,
`GET /config` masks all secrets, webhook HMAC-verified (timing-safe) and
disabled without its secret, comment-posting opt-in. The multiuser slice
adds login-gated triggers, `created_by` job attribution, CORS pinned to the
dashboard origin with credentials, encrypted tokens, and an audit trail.
Per-request credential resolution **is** wired: `core.identity.user_settings`
overlays the signed-in user's decrypted GitHub token and BYO LLM key onto a
*copy* of the global settings, so a job runs on its owner's credentials and
one user's key can't leak into another's run.

**Deliberately not yet built** (deferred, spec §7.12/§8.3): per-repo read
ACLs, private-repo ownership, quotas, OAuth scope escalation for comment
posting, clone-cache eviction. Consequence: safe to host for yourself; not
yet for strangers.

## 8. Testing philosophy

124 tests / 13 suites, every one runnable standalone (`python tests/test_x.py`)
or via pytest, **network- and DB-free by default**: `FakeProvider` for LLMs,
`FakeStore` for the database, `MemoryIdentity` (real Fernet/SHA-256, no
Postgres) for auth, synthetic commit dicts for git, a stubbed OAuth exchange
for login. This works because analysis logic is pure functions over plain
data and every external system hides behind a constructor-injected interface.
Every audit finding becomes a regression test (docs/config hotspot false
positive, Mongo timezone crash, the always-HIGH PR calibration).

The one place fakes were *not* enough: `MemoryIdentity` enforces no
constraints, so it happily accepted a GitHub sign-in that real Postgres
rejected on `UNIQUE(email)` — a green suite over a broken OAuth callback.
Four opt-in tests (`TEST_DATABASE_URL`, skipped otherwise) now run against a
throwaway database to cover the constraints, the connection lifecycle, and
real expiry. **Fake the transport, not the constraint.**

## 9. Honest limitations & the road ahead

- **The hotspot score is validated quantitatively** — temporal hold-out
  evaluation (precision@k) is shipped in v1.0 (`tools/bug_hotspot/evaluate.py`,
  CLI option 10). On nodejs/node: weighted P@5 = 0.850 (~115× lift over base rate).
  Weight tuning against held-out data remains a future improvement.
- **The keyword classifier under-counts bug fixes**; the measured-upgrade
  path is a small fine-tuned transformer behind the same interface.
- **Reports have no history** (latest-only by design) and job state dies
  with the process (by design, single-worker).
- **Multiuser is a slice, not a product**: per-user credentials and
  discovery scoping work, but deep reads are still open by key — anyone with
  a repo key can open its report — and there are no quotas.
- Sequence next: per-repo read ACLs → quotas → OAuth scope escalation for
  comment posting.
