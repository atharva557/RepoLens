# 11 — Testing

9 suites (58 tests). Every suite runs standalone
(`python tests/test_x.py`) **or** under pytest (`pytest tests/`), and every
suite is **network-free and dependency-free** — the core analysis modules are
pure stdlib, and everything heavy is faked.

## The fakes that make it possible

| Real thing | Test stand-in |
|---|---|
| LLM providers | `core/llm.FakeProvider` — canned response, records prompts, can simulate unavailability |
| MongoDB / JSON store | in-memory `FakeStore` implementing the store interface |
| git history | synthetic commit dicts built inline (the commit dict is plain data) |
| GitHub API | stubbed activity dicts / engine entry points |
| FastAPI engine calls | monkeypatched job functions (the API tests exercise HTTP framing, not the analyses) |

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
| `test_identity.py` | multi-user slice: crypto discipline (Fernet round-trip, SHA-256 sessions), user upsert idempotency, session expiry, encrypted LLM configs, the `MULTIUSER=false` 503 gate, full OAuth→cookie→`/me`→CSRF→logout flow (exchange stubbed via `MemoryIdentity`), trigger enforcement. Skips without `cryptography`/`fastapi`. |

## Conventions

- Tests assert on **behavior of pure functions over plain data** wherever
  possible; orchestration tests inject fakes through the same parameters
  production code uses (`settings`, `store`, `llm`) — there is no
  monkeypatching of internals except at the API boundary.
- Every bug found in an audit gets a **regression test** (e.g. the Tool 1
  docs/config false positive, the Mongo timezone crash).
- New code should follow suit: pure logic in a stdlib-only module, a fake for
  anything that talks to the world, and one suite per tool/layer.
