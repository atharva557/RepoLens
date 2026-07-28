# 11 — Testing

11 suites, 103 tests. Every suite runs standalone
(`python tests/test_x.py`) **or** under pytest (`pytest tests/`), and by
default every suite is **network-free and dependency-free** — the core
analysis modules are pure stdlib, and everything heavy is faked. The one
exception is opt-in and skips unless you ask for it (see
[Where a fake stops being enough](#where-a-fake-stops-being-enough)).

## The fakes that make it possible

| Real thing | Test stand-in |
|---|---|
| LLM providers | `core/llm.FakeProvider` — canned response, records prompts, can simulate unavailability |
| MongoDB / JSON store | in-memory `FakeStore` implementing the store interface |
| git history | synthetic commit dicts built inline (the commit dict is plain data) |
| GitHub API | stubbed activity dicts / engine entry points |
| FastAPI engine calls | monkeypatched job functions (the API tests exercise HTTP framing, not the analyses) |
| PostgreSQL identity plane | `core/identity.MemoryIdentity` — same interface as `PgIdentity`, real Fernet/SHA-256 crypto, dict storage |

This works because of the architecture: heavy imports are lazy and the
analysis logic consumes plain dicts, so the interesting code paths never need
the real backends.

## The suites

| Suite | Covers |
|---|---|
| `test_bug_hotspot.py` | classifier word-boundary behavior ("fix" ≠ "prefix"), recency weighting, feature extraction, weighted scoring, explanations, and the docs/config false-positive regression (bug credit only to code files) |
| `test_ml_scorer.py` | percentile normalization, **no-leakage temporal labeling** (features strictly pre-cutoff, labels strictly post-cutoff), end-to-end train/predict on synthetic signal (AUC ≈ 0.95) |
| `test_llm.py` | provider factory (`get_llm`) per provider, default models, graceful-unavailability paths, `FakeProvider` behavior |
| `test_commit_quality.py` | each scoring dimension, report aggregation (per-author, trends, patterns), suggester fallback without an LLM |
| `test_dev_profiler.py` | per-type classification signals, distribution normalization, profile assembly |
| `test_embeddings.py` | LiteIndex TF-IDF ranking, factory fallback selection |
| `test_pr_reviewer.py` | PR spec parsing (`owner/repo#N` + URLs), each mechanical risk check, similarity assessment, risk-level logic, report building |
| `test_api.py` | read layer + 404 messages, job lifecycle (success and failure), `GITHUB_TOKEN` gates, webhook security (secret gate, HMAC verification, event/action filtering, dispatch), discovery endpoints, CORS. Skips itself cleanly if `fastapi` isn't installed. |
| `test_github_cache.py` | GitHub-data freshness policy for `get_repo_meta`: fresh cache served without a call, **stale cache refetches itself**, `refresh=True` forces a refetch, local keys / missing token never hit GitHub, and a failed refresh falls back to the stale copy rather than blanking the dashboard. `GitHubAPI` stubbed. |
| `test_hotspot_eval.py` | v0.5 temporal hold-out evaluation: truth gated to pre-existing code files, methods deliberately disagree (bug-history finds the future bug at rank 1, churn doesn't), unusable snapshots skipped, honest thin-data flagging. |
| `test_identity.py` | multi-user slice: crypto discipline (Fernet round-trip, SHA-256 sessions, scrypt hash/verify/tamper), user upsert idempotency, session expiry, encrypted LLM configs, hash-stripping discipline, the `MULTIUSER=false` 503 gate, full signup→code→verify→login and OAuth→cookie→`/me`→CSRF→logout flows (exchange stubbed via `MemoryIdentity`), every OTP rejection path (wrong `401` / locked `429` / expired `410` / replayed — none of which may create an account), the resend cooldown, trigger enforcement, per-user credential overlay. Skips without `cryptography`/`fastapi`. Plus 5 **opt-in real-Postgres tests** — see below. |
| `test_notify.py` | PR-review notification: the report renders to text + HTML with warnings/oks/summary, singular-vs-plural subject, a bare report (no LLM summary, no url) still renders, **report text is HTML-escaped** (warnings carry file paths and LLM output), recipients are the repo's trackers, a repo nobody tracks falls back to the sending account, and **one refused address or a dead identity lookup never fails the review**. `ConsoleMailer` + `MemoryIdentity`; no network. |
| `test_mailer.py` | outbound mail: the OTP message is `multipart/alternative` with the code in both parts, STARTTLS on 587 vs implicit TLS on 465, backend selection (SMTP needs host **and** credentials — anything missing falls back to console, and `open_mailer` never raises at startup), **every `smtplib` failure surfacing as a `MailError`** since the background task may not raise, and a refused recipient being flagged `bad_address` so signup drops the pending code. Fake SMTP connection; no network. |

## Where a fake stops being enough

`MemoryIdentity` enforces **no constraints** — no `UNIQUE`, no transactions,
no connection to lose. That is what makes it fast and dependency-free, and it
is also its blind spot: a GitHub sign-in for an address that already had a
password account passed every test while failing against real Postgres on
`UNIQUE(email)`.

So `test_identity.py` carries five tests that run against a **real database**
and skip by default. Set `TEST_DATABASE_URL` to a *throwaway* database — each
run truncates every table — to include them:

```bash
set TEST_DATABASE_URL=postgresql://postgres:pw@localhost:5432/gitpulse_test
python tests/test_identity.py
```

They cover what only the real schema can show: the full round-trip through
real `BYTEA`/`TIMESTAMPTZ` columns, OAuth adopting an existing password
account instead of duplicating it, an expired session actually being deleted
on access, `email_otps`' `PRIMARY KEY(email)` making a resend *replace* the
pending code rather than leaving two live ones, and the store reconnecting
after its connection drops. Unset, they print a skip line and the suite stays
network-free.

The general rule: **fake the transport, not the constraint.** When the
behavior under test *is* the constraint, the test needs the real backend, even
if that means making it opt-in.

## Conventions

- Tests assert on **behavior of pure functions over plain data** wherever
  possible; orchestration tests inject fakes through the same parameters
  production code uses (`settings`, `store`, `llm`) — there is no
  monkeypatching of internals except at the API boundary.
- Every bug found in an audit gets a **regression test** (e.g. the Tool 1
  docs/config false positive, the Mongo timezone crash).
- New code should follow suit: pure logic in a stdlib-only module, a fake for
  anything that talks to the world, and one suite per tool/layer.
