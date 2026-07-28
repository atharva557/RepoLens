# Changelog

All notable changes to RepoLens (formerly GitPulse) are documented here.
This project follows the milestone roadmap in `../GitPulse_Revised_Sections.md`.

---

## [Unreleased]

- **Fixed: multiuser mode could not change its LLM model.** `PUT /config`
  refused the whole endpoint with "manage keys per-user via /api/v1/me", but
  that route cannot stand in for it — `PUT /api/v1/me/llm` requires a provider
  in `openai|claude|gemini` *and* a non-empty `api_key`, so a `local`
  (LM Studio) deployment had nowhere at all to set its model, provider or base
  URL. The dashboard's Settings drawer calls `PUT /config` unconditionally, so
  saving anything in the AI section just produced the 403. The block now
  applies to the four fields it was always about — `anthropic_api_key`,
  `openai_api_key`, `gemini_api_key`, `github_token` — and names whichever one
  was sent; `llm_provider`, `llm_model` and `local_llm_base_url` are
  non-secret server config and go through. A mixed payload is refused whole,
  so a rejected request never half-applies.

- **Finished PR reviews are emailed.** Tool 3 already ran automatically on a
  webhook and persisted its report; the only ways to see one were opening the
  dashboard or enabling the PR comment. Email is now a second delivery channel
  on both the webhook path and `POST /repos/{key}/pr-reviews/{n}` — subject
  carries the risk level and warning count (`[HIGH] owner/repo#42 — 2
  warnings`), body carries the warnings, the passing checks, the LLM summary
  when there is one, and a link back to the PR.
  **No configuration of its own**: it reuses the SMTP account already set up
  for signup codes, so there is nothing extra to switch on. With SMTP unset
  the console backend prints reviews exactly as it prints codes.
  Sending is driven from the UI rather than a config file. The report page has
  an **Email** button (`POST /repos/{key}/pr-reviews/{n}/email`, synchronous —
  the user clicked it and wants to know whether it went), and
  *Settings → Email PR reviews* is a per-user switch that rides along with each
  trigger as `?email=true`. The server keeps no preference of its own, so a
  dashboard review is silent unless somebody asked for mail. The webhook is the
  exception and always sends: nobody is watching an unattended trigger, which
  is the entire reason it exists.
  Recipients in multiuser mode are everyone tracking that repo
  (`emails_tracking_repo`, the inverse of `user_repo_keys`) — deliberately the
  same set already permitted to read the report, so a notification cannot
  surface a repo the recipient couldn't open. With no accounts, or a repo
  nobody tracks, it falls back to `SMTP_USER` so a single-user install still
  gets its own reviews. Report text is HTML-escaped on the way into the HTML
  part: warnings carry file paths and the summary is LLM output, none of it
  ours to trust. A refused address or an identity lookup that raises is logged
  and skipped — the report is saved before any of this runs, and mail trouble
  must never turn a successful analysis into a failed job.
  *`emails_tracking_repo` deliberately promises no ordering: Postgres sorts by
  the database collation and `MemoryIdentity` by code point, and they disagree
  on addresses like `pg@x.com` vs `pg2@x.com`. Recipients are a set.*
- **Signup now verifies the email address with a one-time code.**
  `POST /api/v1/auth/signup` validates the form, parks the scrypt hash of the
  chosen password on an `email_otps` row, emails a 6-digit code and returns
  `202` — it creates **nothing**. `POST /api/v1/auth/signup/verify` exchanges
  a valid code for the account and a session (`201`). Verify-then-create was
  chosen over an `email_verified` flag so an unverified signup can never squat
  the `UNIQUE(email)` that the GitHub path also depends on, and so no later
  read path has to remember to check a flag. Rejections stay distinct
  (`404` none / `401` wrong / `410` expired / `429` locked or too soon) so the
  UI can say what actually happened. Codes come from `secrets.randbelow`, are
  single-use, expire in `OTP_TTL_MINS` (10), and lock after 5 wrong attempts —
  without that cap a 6-digit code is 10⁶ guesses against a local API.
  Re-POSTing `/signup` is the resend: `email` is the primary key, so a new
  code replaces the old one and two live codes cannot coexist. Abuse is
  bounded per-address by `sent_at` and per-caller by an in-process IP counter
  (20/hour).
  *Codes are stored as sent, not hashed — a deliberate call for this
  milestone, since a code is single-use, short-lived and valid nowhere else;
  hashing it is a one-line change in `start_email_otp`/`verify_email_otp`.*
- **New `core/mailer.py` — outbound email on the stdlib**, no new dependency
  (`smtplib` + `email.message`, the same call as urllib over authlib for the
  OAuth exchange). Two backends behind one `send()`, like
  `MongoStore`/`JsonStore` and `PgIdentity`/`MemoryIdentity`: `SmtpMailer`
  (implicit TLS on 465, STARTTLS on 587, and a hard failure rather than a
  cleartext login if a server offers neither) and `ConsoleMailer`, which
  prints the code so signup runs on a laptop with no mail account.
  SMTP is selected only once `SMTP_HOST`, `SMTP_USER` and `SMTP_PASSWORD` are
  all set — a host with no login is never a working config, and a half-filled
  `.env` should print codes rather than fail every send. Sends go through
  `BackgroundTasks` because handlers are sync `def` and a hung SMTP handshake
  would otherwise tie up a threadpool worker; every failure arrives as a
  `MailError` since that task may not raise. A refused recipient is flagged
  `bad_address` and drops the pending row, so a typo'd address can be
  corrected immediately instead of waiting out the resend cooldown.
- **Fixed: GitHub sign-in locked out anyone who already had a password
  account.** `users.email` is `UNIQUE` and a password account has
  `github_id` NULL, so `INSERT ... ON CONFLICT (github_id)` never matched it
  and fell through to an INSERT that violated the email constraint — the
  OAuth callback reported it as a 502. `upsert_github_user` now resolves in
  three explicit steps (match `github_id` → adopt an unlinked row with the
  same email, audited as `github_linked` → insert), so the two sign-in paths
  converge on one account. Every test passed throughout, because
  `MemoryIdentity` enforces no constraints; the twin now mirrors the same
  branch, and four **opt-in real-Postgres tests** (`TEST_DATABASE_URL`,
  skipped by default) cover what only the real schema can show.
- **Fixed: a dropped Postgres connection broke sign-in until the API process
  was restarted.** One autocommit connection was opened at startup and used
  forever, so a database restart or an idle link reaped by the OS/a proxy
  left every later call raising on a dead handle. All statements now go
  through a `_cursor()` helper that reopens a known-closed connection and
  discards one that dies mid-statement. The failed statement is deliberately
  *not* replayed — under autocommit an INSERT may already have committed, and
  a blind retry would duplicate it.
- **Fixed: the session-expiry race, and three round trips on every
  authenticated request.** `user_for_session` was SELECT → check expiry in
  Python → UPDATE → SELECT user; a session that expired between the check and
  the update was slid back to life. It is now a single CTE that slides
  `expires_at`/`last_seen_at` with `expires_at > now` in its own `WHERE` and
  joins the user row in the same statement, and a miss deletes the dead row
  so expired sessions don't accumulate.
- **Postgres startup failures are now actionable.** A raw `OperationalError`
  at server start is a wall of libpq text that reads as "the app is broken"
  rather than "Postgres needs one more setup step". `_pg_hint` maps the four
  real cases — driver not installed in *this* interpreter, database missing,
  bad credentials, server unreachable — to the specific command that fixes
  each, with the password masked out of the DSN. Still fatal (identity has no
  safe fallback), just legible.
- **Fixed: ML training labels disagreed with the evaluator and the live
  scorer.** `dataset.py` labeled *any* file touched by a future bug-fix
  commit as positive — docs/config included — while `evaluate.py`'s ground
  truth and the live feature extractor both gate bug credit to
  `is_code_file`. The same gate now applies to `buggy_future`, so training,
  evaluation and serving share one definition of "received a bug fix".
  Retrain the second-opinion model (CLI `train`) to pick up the corrected
  labels. Regression test in `test_ml_scorer.py`.
- **Fixed: `MongoStore.load_commits` had no sort.** Consumers assume
  newest-first — the bug-diff corpus takes the *first* N qualifying commits
  and fingerprints the first/last SHA — but Mongo's natural order is
  unguaranteed and only matched by accident of delete-then-insert. Now an
  explicit `.sort([("date", -1)])`, backed by the existing `(repo, date
  DESC)` index, with the ordering contract documented on both stores and
  asserted by a fake-cursor unit test (`test_api.py`, 19 tests).
- **Fixed: the clone cache collided on repo *name*, dropping the owner.**
  `pallets/flask` and `yourfork/flask` both mapped to `data/cache/clones/flask`,
  so analyzing the second silently reused the first repo's clone and cached
  the wrong history under its own key. Clone directories now use the
  full-key slug (`clones/pallets__flask` — JsonStore's `__` convention, via
  the new `_clone_dest()` helper); old-style directories are orphaned and
  simply re-cloned on next use. Regression test in `test_github_cache.py`.
- **Fixed: Home showed every user the whole store.** In multiuser mode the
  discovery lists are now per-user: each analysis trigger records what the
  signed-in user searched (repos → `user_repos` with the canonical
  `repo_key()`; profile usernames → new `user_profiles` table, idempotent
  `CREATE TABLE` so existing DBs pick it up on start), re-searching
  refreshes recency, and `GET /repos` / `GET /profiles` filter to the
  requesting user's own history — a brand-new account sees empty lists
  (Home's existing empty states), anonymous requesters see empty lists, and
  `/me` now returns both recency-ordered lists. `created_by` on jobs falls
  back to email for password accounts. Deep reads stay open by key (hard
  per-repo ACLs remain the next slice, per spec §7.12). Single-user mode is
  untouched — no filtering. Verified live against the real store (fresh
  user: empty; after analyzing one repo: exactly that repo listed). New
  `test_api.py` scoping test (18 in the suite) with engine stubs;
  `test_identity.py` covers profile tracking + recency ordering.
- **User login/signup is live (email + password), with an in-memory dev
  identity mode.** New auth routes on the existing session plane
  (`api/auth.py`): `POST /api/v1/auth/signup` (validates email shape +
  ≥8-char password, salted-**scrypt** hash via `core.identity.hash_password`
  — format `scrypt$n$r$p$salt$hash` so params can be raised later — signs the
  user in on creation, 409 on duplicate email) and `POST /api/v1/auth/login`
  (constant-time verify; wrong email and wrong password are one generic 401;
  failures audited). The hash is readable only by the login lookup — every
  other user read strips it, in Postgres (`_USER_COLS`) and the Memory twin
  alike. `IDENTITY_BACKEND=memory` (new knob, default `postgres`) runs the
  identity plane in process memory — a DEV escape hatch that makes login
  demoable before Postgres is set up (accounts reset on restart; announced
  loudly at startup). Frontend: `lib/auth.jsx` AuthProvider probes
  `/api/v1/me` (503 = single-user → no wall; 401 = Login wall on every URL,
  original URL preserved after sign-in; 200 = signed in), new `Login.jsx`
  (sign-in/sign-up card in the app style), navbar account chip + sign-out,
  and `postJSON`/`putJSON` now always send the `X-GitPulse-Client` CSRF
  header. `MULTIUSER=false` remains exactly the old single-user app.
  Verified live end-to-end (wall → signup → app → logout → login). Suite
  grown to 11 tests (`test_identity.py`): scrypt hash/verify/tamper,
  hash-stripping discipline, memory-backend gate, and the full
  signup→session→logout→login API flow incl. CSRF and generic-401 checks.
- **Performance trio — the dashboard's remaining request-path costs are
  gone.** (1) `GET /repos/{key}/activity` no longer re-reads and re-scans the
  entire commit history per view: `core/activity.py` is split into
  `build_activity_base` (one expensive pass, computed when a history is saved
  in `fetch_and_store_commits` and cached as `activity_base` with per-day
  bugfix buckets) and `window_activity` (cheap per-request windowing — any
  time range sums ≤ a few thousand day rows). Pre-aggregate caches self-heal
  on first read; the insights digest uses the base too. Measured on a
  50k-commit history through the JSON store: **367ms → 3ms per request
  (~123x)**. (2) The Dashboard fetch waterfall is flat: activity now rides in
  the same `Promise.all` as meta/quality/insights/pr-reviews/pulls (was:
  awaited alone first, total = activity + slowest of the rest). (3)
  `lib/api.js` gained a session-scoped TTL cache — opt-in `{ ttl }` per GET
  (Dashboard/BugHotspots 60s, Home 30s, `/jobs` never cached), every
  successful GET reprimes, and any successful POST/PUT clears the whole cache
  so triggered re-analyses always show fresh — Home ⇄ Dashboard navigation is
  now instant. `?recent=` is capped at 50 (422 above — the base stores 50).
  Activity endpoint tests extended (served-without-commits + heal).
- **Bring-your-own keys from the dashboard.** The Settings drawer gained an
  "AI Provider & Keys" section: pick the LLM backend (Local/LM Studio,
  Claude, OpenAI, Gemini) with its API key and optional model, and set the
  GitHub token — no `.env` editing. Backed by `PUT /config` (single-user
  only; `403` in multiuser mode where keys are per-user via `/api/v1/me`):
  changes apply to the live process immediately (`get_llm()` reads settings
  per job) and `persist_env()` writes them back to `.env` — seeded from
  `.env.example` on first save, other lines/comments preserved — so the CLI
  and the next server start agree. Secrets are write-only: inputs show only
  a "configured ✓" state (from the masked `GET /config`) and responses never
  echo values. Save runs `GET /test` and reports whether the LLM/token
  actually work. Only keys + LLM choice are runtime-editable on purpose —
  analysis tuning stays file-only. New suite entry (`test_api.py`, 17
  tests); runtime-editable keys marked in `docs/10-configuration.md`.
- **PR reviews render before the LLM finishes; the dashboard lists real
  GitHub PRs.** Tool 3 now saves the deterministic report (risk level,
  warnings, similarity) *before* the LLM phase with `summary_pending: true`,
  then re-saves with the summary (`runner.py` two-phase save; single save
  when no LLM is configured; webhook comments still post only the final
  report). The PR page shows that report as soon as it exists — new AI
  Change Summary card with a generating/absent state, a live analysis
  banner (fed by job `progress`), and stale-while-reanalyzing instead of a
  full-page spinner; a failed job on a visible report becomes a banner
  error, not a page swap. The Dashboard's Pull Requests card now shows the
  repo's **last 5 GitHub PRs whether reviewed or not** (`GET
  /repos/{key}/pulls` + `GitHubAPI.list_pulls`; store-cached under
  `recent_pulls` with a short `PULLS_CACHE_HOURS` TTL, default 1h, since PR
  lists churn fast; card sync button and analyze-refresh both force-refetch)
  with state chips (open/merged/closed/draft) joined against review-severity
  chips; unreviewed rows link straight into a review. Falls back to the old
  reviewed-only list without a token. New tests: two-phase save + LLM-off
  single save (`test_pr_reviewer.py`, 13), `/pulls` read (`test_api.py`, 16).
- **Developer AI summary now works for everyone; dashboard surfaces PRs;
  profile cards rebuilt.** The Tool 2 LLM summary is generated from the whole
  computed profile — type distribution, languages, commit/PR/review counts,
  and real commit subjects — not just PR descriptions, so accounts without
  authored PRs (most users, including the project owner) finally get a
  grounded paragraph instead of nothing (`llm_analyzer.py` digest, prompt
  requires every claim to follow from the data). The Dashboard gained a Pull
  Requests card listing the repo's reviewed PRs with severity chips (each
  links to the PR review page; empty state offers a "Review a pull request"
  CTA), and the PR review input screen shows that same list when arriving via
  `?repo=`. Profile cards redrawn: Top Languages is a GitHub-style segmented
  bar + legend (was a single-language conic radial), Contribution Mix is
  ranked with the primary type highlighted, and Commit Health is a clean
  conic ring, all on a fixed-hue categorical palette that stays distinct in
  both themes.
- **Settings moved into a right-hand drawer with theme-wide accents.** The old
  `GlobalSettingsModal` is replaced by `SettingsDrawer` (portal-rendered so the
  navbar's backdrop-blur can't clip it); it applies theme (`dark | light |
  system`) and accent-color changes live and persists them through
  `ThemeContext`. A chosen accent recolors the whole app — primary, borders,
  muted text, glows — via an injected per-theme palette (`lib/theme.js`:
  `accentThemeCss`, `mixHex`). Home's "Recent Analysis" list is now actually
  ordered most-recent-first.
- **GitHub owner/repo shorthand.** Analysis inputs accept a bare `owner/repo`
  (not only a full URL); the uvicorn reloader no longer watches the clone
  cache, so pulling a repo mid-run stops restarting the server.
- **Performance: the three N-per-item bottlenecks are gone.**
  (1) History pulls are ONE `git log --numstat` invocation parsed in Python
  (`parse_numstat_log`) instead of one `git diff` subprocess per commit -
  flask's full 3,812-commit history now reads in ~1.2s. (2) The profiler's
  per-commit GitHub detail fetches (up to 15 repos x 100 commits, previously
  sequential) run on an 8-worker thread pool with identical order/skip
  semantics. (3) Tool 3's similarity index persists per repo with a corpus
  fingerprint: an unchanged corpus is reused - no git-show loop, no
  re-embedding per review - and per-repo Chroma collections fix the
  concurrency bug where two simultaneous reviews of different repos silently
  corrupted each other's similarity scores. New regression tests in
  test_bug_hotspot / test_dev_profiler / test_embeddings.
- **v0.5 hotspot evaluation** (CLI option 10, `tools/bug_hotspot/evaluate.py`):
  temporal hold-out validation of the weighted score - rank files as of past
  cutoffs, measure precision/recall@k against the files that actually received
  code bug fixes in the following window, compared against per-component
  baselines, equal weights, and the random base rate. On nodejs/node
  (46,993 commits, 4 snapshots): weighted P@5 = 0.850 vs base rate 0.0074
  (~115x lift), beating every single-component baseline. Reports persist as
  `hotspot_eval`; new suite tests/test_hotspot_eval.py.

- **Pre-review upgrades (Tool 3)**: the risk level is now a **weighted signal
  score** (mirroring Tool 1's formula brand — `RISK_WEIGHTS`, bands tunable
  via `PR_RISK_HIGH`/`PR_RISK_MEDIUM`, arithmetic printed in the report);
  four new deterministic checks: **PR description quality** (Tool 4's scorer
  reused on `title\n\nbody`), **bug echo** (source files whose latest change
  was a recent bug fix, read from stored hotspot features), a **new-file
  blind-spot note** (large brand-new files have no history for hotspot
  analysis), and a **coverage honesty note** (report states which checks
  could not run when the repo lacks cached hotspots/corpus). Report dict
  gains `risk_score`, `breakdown`, `notes`. Suite grown to 11 tests.
- **PR risk levels are no longer always-HIGH** — three root causes fixed:
  (1) hotspot file-risk now counts **source files only** — churn-ranked docs
  and test files in the hotspot list (e.g. `CHANGES.rst`) no longer mark a PR
  risky; (2) the similarity corpus **excludes docs/config-only bug fixes**
  (changelog typo "fixes" matched PRs' own changelog edits — flask's corpus
  dropped 53 → 20 diffs); (3) **HIGH now requires two independent signals**,
  one signal = MEDIUM, none = LOW. Validated live: `pallets/flask#6066`
  (focused feature PR with tests) went from a false HIGH to LOW. Four new
  regression tests in `tests/test_pr_reviewer.py`.
- **Job progress reporting — long runs are no longer a black box**: every
  background job now carries a `progress` field
  (`{phase, pct, detail, updated_at}` on `GET /jobs/{id}`), fed by a progress
  callback (`core/progress.py`) threaded through all five engine runners.
  Phases are worded to answer "what is slow": `cloning repository (GitHub)`
  with live per-stage percentages (GitPython progress adapter, decile-
  throttled), `reading commit history (git)`, `fetching commits (GitHub)`
  (percent = repos completed — the profiler's dominant cost),
  `embedding bug-fix diffs (ML)`, `scoring files (weighted formula / ML
  second opinion)`, LLM phases, `saving report (database)`. The CLI prints
  the same phases through the default `print_progress` sink; the dashboard
  progress bar is specced in `frontend/AGENTS.md` (§4.2). Verified live: a
  fresh clone shows `[ 40%] cloning repository (GitHub) - receiving objects`.
- **GitHub reads are now database-first everywhere**: cached repo metadata and
  developer profiles are served whatever their age — the server never silently
  re-hits GitHub on a `GET`. GitHub is called only on the first fetch or an
  explicit refresh (`GET .../meta?refresh=true`, `POST /profiles/{u}`,
  `POST /analyze {"refresh": true}` — the dashboard's "Sync from GitHub"
  button, spec'd in `frontend/AGENTS.md` §5a). `PROFILE_CACHE_HOURS` now only
  labels a served profile as stale. Fixed along the way: an explicit analyze
  refresh now actually `git pull`s the cached clone (previously it re-read
  the same stale history), with a graceful warn-and-continue when offline.
  Tests updated + a new database-first suite entry (`test_dev_profiler.py`).
- **Multi-user identity plane (Postgres) — first v2 slice** (`MULTIUSER=true`,
  default off = exactly the single-user app): the spec §6.4 schema (`users`,
  `sessions`, `user_repos`, `llm_configs`, `audit_log`) bootstrapped
  idempotently in PostgreSQL (`core/identity.py`, psycopg lazy import);
  "Sign in with GitHub" OAuth (`api/auth.py`: login redirect with state nonce,
  code exchange, user upsert, session cookie httpOnly/SameSite=Lax with only
  its SHA-256 hash stored, sliding 30-day expiry); GitHub tokens and BYO LLM
  keys **Fernet-encrypted** at rest with `FERNET_KEY` (spec §2.5: hash what
  you check, encrypt what you use); CSRF via required `X-GitPulse-Client`
  header; account routes `/api/v1/me` (+ llm / github-token management,
  write-only secrets); every audit-worthy action logged. In multiuser mode,
  analysis triggers require a session and jobs record `created_by`; CORS pins
  to `DASHBOARD_ORIGIN` with credentials. Auth routes answer 503 while off
  (webhook precedent). New deps (optional): `psycopg[binary]`, `cryptography`.
  New 9th suite `tests/test_identity.py` (8 tests, DB- and network-free via a
  `MemoryIdentity` twin + stubbed OAuth exchange). Deferred to the next slice:
  per-repo access rules (§7.12), quotas, per-request LLM resolution (§8.3),
  scope escalation.
- **LM Studio model autoload** (`LOCAL_LLM_AUTOLOAD=true`, default off): when
  the local provider finds the server running but no model loaded, it resolves
  a model (`LLM_MODEL` if downloaded, else an already-loaded one, else the
  first downloaded chat model — via the new `pick_local_model()`), triggers
  LM Studio's just-in-time load with a 1-token request, and falls back to the
  `lms load` CLI if JIT loading is disabled. Announced with `[llm] autoload:`
  lines; `test-llm` shows the toggle; off = exactly the previous behavior.
  Two new tests in `tests/test_llm.py` (7 total in the suite).
- **ChromaDB similarity backend is now live**: `chromadb` + `sentence-transformers`
  installed and verified end-to-end; Tool 3 diff-similarity now uses real semantic
  embeddings (persistent index at `data/chroma`) instead of the TF-IDF fallback.
- **Backends are always announced**: every CLI action prints a `[backend]` line
  stating whether the primary or an alternative was used (store: mongodb vs json
  fallback; similarity: chroma vs lite fallback) — previously only fallbacks warned.
- **Developer profiles are cached**: a profile younger than `PROFILE_CACHE_HOURS`
  (default 24, new `.env` knob) is served from the store instead of re-hitting the
  GitHub API; the CLI asks before re-fetching, and `POST /profiles/{user}` still
  always rebuilds. Cache hits/saves are announced with `[cache]` lines.
- **API: CORS enabled** (`GITPULSE_CORS_ORIGINS`, default `*`) so the React
  dashboard dev server can call the API cross-origin.
- **API: discovery layer** for the dashboard landing pages — `GET /repos`
  (per-repo summary: commit count, hotspot/commit-quality report presence,
  PR-review numbers), `GET /profiles`, and `GET /repos/{key}/pr-reviews`.
  Backed by a new `list_reports()` on both stores (Mongo aggregation /
  JSON-dir scan).
- **API: `GET /test` self-test endpoint** — one call checks every subsystem:
  store save/load round-trip, LLM provider availability, which similarity
  backend would be selected, GitHub-token & webhook configuration.
- `tests/test_api.py` grew to ten tests (discovery, CORS simple + preflight,
  self-test). All eight suites pass.
- **Dashboard read layer** (driven by the `ui_protoype/` screens):
  - `GET /repos/{key}/activity` — contributor leaderboard, recent commits,
    daily heatmap buckets and a transparent health score
    (`0.6·commit_quality + 0.4·(1−recent_bugfix_ratio)·10`), all aggregated
    from the cached commit history (`core/activity.py`).
  - `GET /repos/{key}/meta` — GitHub header metadata (description, stars,
    forks, open issues, language percentages), store-cached with the
    `PROFILE_CACHE_HOURS` TTL (`GitHubAPI.repo_meta` + `get_repo_meta`).
    Fixed: some PyGithub versions leak a `url` string into `get_languages()`.
  - `POST` + `GET /repos/{key}/insights` — LLM-generated insight bullets from
    a digest of stored reports (`core/insights.py`), cached as `repo_insights`.
    Reasoning models get a ≥1536-token budget (512 truncated gemma to empty).
  - Commit-quality reports now carry `avg_subject_len`, `pct_imperative`,
    `pct_referenced` for the dashboard's quality card.
  - `tests/test_api.py`: 13 tests. Shared `report_age_hours()` moved to
    `core/db.py` (profiler + repo-meta reuse it).
- **Developer profile grew the dashboard fields** (Developer_profile.html):
  `user` social header (avatar, bio, followers/following, public repos,
  years active — `GitHubAPI.user_meta`), `languages` with percentages,
  `prs_merged` + `issues_resolved` (GitHub search counts; "resolved" =
  closed issues the user was assigned), and a per-day `heatmap` of the last
  365 days. CLI profile card prints them; old cached profiles still render
  (fields are optional). Rebuild profiles (re-fetch) to populate.
- **Renamed GitPulse → RepoLens** (user-facing strings only): CLI banner,
  API title/root, PR-report header, doc titles. Internals unchanged on
  purpose — `GITPULSE_*` env vars, the `gitpulse` Mongo database, and module
  paths keep working.
- **React scaffold** in `frontend/` (Vite + React, Tailwind v4 via
  `@tailwindcss/vite`, Recharts, react-router-dom). No UI implemented yet —
  `src/pages/*.jsx` are comment-only specs mapping each prototype screen to
  its API endpoints (Home, Loading, Dashboard, BugHotspots, DeveloperProfile;
  conventions in `src/lib/api.js`). The prototype color/font theme is wired
  into `src/index.css` `@theme`; `npm run dev` proxies `/api/*` to
  `127.0.0.1:8000`. Build verified.

---

## [v0.4] — API Layer — 2026-07-02

Adds the **FastAPI backend**: a thin web layer over the existing engine, plus the
**PR-review webhook** deferred from v0.3. The React dashboard is the remaining
v0.4 item. Also fixes several bugs found in an audit of v0.1–v0.3.

### FastAPI backend (`api/`)

| File | Purpose |
|------|---------|
| `api/main.py` | App factory + routes. Reads come from the store; analyses run via `BackgroundTasks` (`202` + job id). Sync handlers on purpose — the engine is synchronous and runs in FastAPI's threadpool. |
| `api/webhook.py` | `POST /webhook/github` — HMAC-verified (`GITHUB_WEBHOOK_SECRET`); auto-runs Tool 3 on PR `opened/reopened/synchronize/ready_for_review`. Posting the report as a PR comment is opt-in (`GITPULSE_WEBHOOK_POST`). |
| `api/jobs.py` | Bounded in-memory job registry (pending/running/done/failed); catches `SystemExit` so engine errors can't kill the server. |

Read endpoints: `/repos/{key}/hotspots`, `/repos/{key}/commit-quality`,
`/repos/{key}/pr-reviews/{n}`, `/profiles/{user}` (the `{key}` param accepts
both `owner/repo` and bare local-clone names). Triggers: `POST /analyze`,
`POST /commit-quality`, `POST /profiles/{user}`, `POST /repos/{o}/{r}/pr-reviews/{n}`.
Meta: `/health`, `/config` (secrets masked), `/jobs/{id}`, `/docs`.

Run: `python -m uvicorn api.main:app --reload` (or `python api/main.py`).

### Bug fixes

- **Tool 4 LLM rewrites crashed** (`TypeError: 'bool' object is not callable`):
  the `suggest` bool parameter in `run_commit_quality_report` shadowed the
  imported `suggest()` function. Import aliased; rewrite path verified end-to-end.
- **MongoDB-backed analysis crashed on date math**: pymongo returns *naive*
  datetimes by default, so cached commit dates couldn't be subtracted from
  tz-aware "now" in the feature extractor. `MongoClient` now uses `tz_aware=True`.
- **Settings crashed on blank numeric `.env` values** (`int("")`): numeric
  settings now fall back to their defaults with a warning instead.
- CLI menu prompt said "1-5" for a 10-option menu; README pointed `test-llm` at
  menu option 6 (it is 7).

### Config & tests

- New `.env`: `GITPULSE_WEBHOOK_POST` (default false). `GITHUB_WEBHOOK_SECRET`
  is now actually consumed (by the webhook).
- New test suite: `tests/test_api.py` — FakeStore + stubbed engine entry points,
  network-free; covers the read layer, job lifecycle, token gates, and webhook
  security (secret gate, HMAC, ignore rules, dispatch). Skips cleanly when
  fastapi isn't installed. All **eight** suites pass.
- New deps (API only): `fastapi`, `uvicorn` (+ `httpx` for the test client).

### Next up (v0.4 completion / v0.5)

- React dashboard (Tailwind + shadcn/ui + Recharts) on top of this API.
- v0.5 evaluation pass (temporal hold-out for Tool 1, human-rated LLM sample).

---

## [v0.3] — PR Review — 2026-07-01

Adds **Tool 3 — PR Review Assistant**: an automated pre-review report for a pull
request, combining v0.1 hotspot risk and the v0.2 LLM, plus a new diff-similarity
engine. Delivered as an on-demand CLI action (webhook deferred to v0.4).

### Roadmap items completed (v0.3)

- [x] Similarity / embedding pipeline (past bug-fix diffs)
- [x] PR Review Assistant (Tool 3)
- [x] On-demand analysis + optional GitHub PR-comment posting *(no GitHub Action)*
- [x] *Folded in:* Tool 1 classifier cleanup (docs/config false positives)

### Diff-similarity engine (pluggable, graceful)

`core/embeddings.py` — a `SimilarityIndex` with two backends, auto-selected:

| Backend | How | Deps |
|---------|-----|------|
| `ChromaIndex` | sentence-transformers (`all-MiniLM-L6-v2`) + ChromaDB (cosine) | heavy, optional |
| `LiteIndex` | stdlib TF-IDF cosine | none |

`open_similarity_index()` prefers Chroma and falls back to Lite with a warning, so
v0.3 runs everywhere and upgrades when the heavy deps are installed. The corpus is
the repo's own past **bug-fix** diffs (`pipeline/build_bug_index.py`).

### Tool 3 — PR Review Assistant

| File | Purpose |
|------|---------|
| `tools/pr_reviewer/risk_scorer.py` | File risk (hotspot membership), missing tests, unfocused/large change — pure stdlib |
| `tools/pr_reviewer/similarity.py` | Embed the PR diff, query the bug corpus, flag high similarity |
| `tools/pr_reviewer/llm_summarizer.py` | LLM plain-English summary of the diff (optional) |
| `tools/pr_reviewer/report_builder.py` | Markdown report (Risk level / ⚠️ Warnings / 📋 Summary / ✅ OK) |
| `tools/pr_reviewer/github_commenter.py` | Post the report as a PR comment (opt-in) |
| `tools/pr_reviewer/runner.py` | Orchestration + `owner/repo#N` / URL parsing |

`GitHubAPI` gained `get_pull()` and `post_pr_comment()`. CLI **`review-pr`** prints
the report and asks before posting. Needs `GITHUB_TOKEN`.

### Tool 1 classifier cleanup

New `core/paths.py` (shared file classification). `extract_features.py` now credits
**bug history only to source files** — a "fix ..." commit that also touches a
`README.md` / `.toml` no longer marks those as hotspots. Churn/authors unchanged.
Regression test added.

### Config & tests

- New `.env`: `SIMILARITY_BACKEND`, `EMBEDDING_MODEL`, `PR_SIMILARITY_TOP_K`,
  `PR_SIMILARITY_WARN`, `HOTSPOT_TOP_N`.
- New tests: `test_embeddings.py`, `test_pr_reviewer.py`, + a Tool-1 regression test.
  All **seven** suites pass (network-free via LiteIndex + FakeProvider + synthetic data).

### Optional dependencies

- `sentence-transformers`, `chromadb` (upgrade the similarity engine). Not required —
  `LiteIndex` is the default fallback.

### Next up (v0.4 — API + Dashboard)

- FastAPI backend (+ the deferred PR webhook), React dashboard.

---

## [v0.2] — Intelligence Layer — 2026-06-30

Adds the LLM and two more tools. Two design decisions shaped it: the LLM backend
is **pluggable** (local LM Studio *or* bring-your-own Claude/OpenAI/Gemini key),
and the Developer Skill Profiler works **per-GitHub-user across repos**.

### Roadmap items completed (v0.2)

- [x] LLM integration — pluggable multi-provider layer (LM Studio default)
- [x] Commit Message Quality Analyzer (Tool 4)
- [x] Developer Skill Profiler — basic classification (Tool 2)

### Pluggable LLM provider layer

`core/llm.py` — choose a backend with `LLM_PROVIDER`:

| Provider | Backend | SDK |
|----------|---------|-----|
| `local` (default) | LM Studio / any OpenAI-compatible server | `openai` |
| `openai` | OpenAI API | `openai` |
| `gemini` | Google Gemini (OpenAI-compatible endpoint) | `openai` |
| `claude` | Anthropic API (default model `claude-opus-4-8`) | `anthropic` |

The LLM is always optional and degrades gracefully (`available()` / `LLMUnavailable`).
SDKs are lazy-imported. CLI **`test-llm`** pings the configured provider.

### Tool 4 — Commit Message Quality Analyzer

| File | Purpose |
|------|---------|
| `tools/commit_quality/scorer.py` | Rule-based 0-10 score (length, vagueness, verb, context, reference) — pure stdlib |
| `tools/commit_quality/suggester.py` | LLM rewrite from message + diff |
| `tools/commit_quality/reporter.py` | Per-commit / per-contributor / trend / common-patterns aggregation |
| `tools/commit_quality/runner.py` | Orchestration |

CLI **`commit-quality`** prints the repo report; opt-in `--suggest`/prompt adds LLM
rewrites for the worst messages. Added `git_client.commit_diff()` and generic
`db.save_report()` / `load_report()`.

### Tool 2 — Developer Skill Profiler (per-user)

| File | Purpose |
|------|---------|
| `core/github_client.py::GitHubAPI` | PyGithub wrapper — repos, commits-by-author, authored PRs, reviews (rate-limit-capped) |
| `pipeline/fetch_user_activity.py` | Pull + normalize a user's public activity |
| `tools/dev_profiler/classifier.py` | Rule-based type distribution (Bug Fixer / Feature Builder / Refactorer / Reviewer / Documentation Writer / Architect) — pure stdlib |
| `tools/dev_profiler/llm_analyzer.py` | Optional LLM read of PR descriptions |
| `tools/dev_profiler/profile_builder.py` | Assembles the card (reuses Tool 4's scorer for commit-message quality) |
| `tools/dev_profiler/runner.py` | Orchestration |

CLI **`profile <username>`** prints the profile card. Needs `GITHUB_TOKEN`
(degrades to a clear message / cached profile without one).

### Config & tests

- New `.env`: `LLM_PROVIDER`, `LLM_MODEL`, `LOCAL_LLM_BASE_URL`, `ANTHROPIC_API_KEY`,
  `OPENAI_API_KEY`, `GEMINI_API_KEY`, `LLM_MAX_TOKENS`, `LLM_TEMPERATURE`,
  `PROFILE_MAX_REPOS`, `PROFILE_MAX_COMMITS_PER_REPO`, `PROFILE_PR_SAMPLE`.
  Removed the Ollama settings. Fixed the `.env` parser's inline-comment handling.
- New tests: `test_llm.py`, `test_commit_quality.py`, `test_dev_profiler.py` (all
  network-free via an in-process `FakeProvider` and synthetic data). All five suites pass.

### Optional dependencies

- `openai` (local/openai/gemini), `anthropic` (claude), `PyGithub` (profiler).
  None are required for the rule-based features.

### Next up (v0.3 — PR Review)

- ChromaDB embedding pipeline, PR Review Assistant (Tool 3), webhook + PR comment posting.

---

## [v0.1] — Foundation — 2026-06-30

The first milestone: the shared data pipeline plus **Tool 1 — Bug Hotspot
Predictor**, driven by an interactive CLI. Built on the *revised* architecture
(MongoDB + recency-weighted scorer, no XGBoost-as-primary, no GitHub Action).

### Roadmap items completed (v0.1)

- [x] GitHub/git client with MongoDB caching
- [x] Commit classification (bug-fix keyword detection)
- [x] Bug Hotspot Predictor — **recency-weighted scorer** (Tool 1)
- [x] Basic CLI output

### Architecture decisions adopted (from the revised doc)

- **MongoDB** is the primary datastore (replaces SQLite). A JSON-file cache is
  used automatically as a fallback when MongoDB isn't reachable, so the tool runs
  on any machine out of the box.
- **Tool 1 uses a transparent recency-weighted formula, not a trained XGBoost
  classifier** — chosen for explainability and because training on a single small
  repo suffers from label leakage and tiny/imbalanced data.
- **The GitHub Action was dropped**; a single PR path is the plan for later.

### What was built

| Area | File(s) | Purpose |
|------|---------|---------|
| Config | `config/settings.py` | `.env`-driven settings (stdlib `.env` parser, no hard dep) |
| Git access | `core/git_client.py` | GitPython: commit history + per-file LOC metrics |
| GitHub | `core/github_client.py` | Resolve a repo ref → local clone (clones remote URLs once) |
| Storage | `core/db.py` | `MongoStore` (primary) + `JsonStore` (fallback), same interface |
| Orchestration | `core/analysis.py` | End-to-end: clone → cache → classify → features → score → explain |
| Pipeline | `pipeline/classify_commits.py` | Bug-fix detection via word-boundary keyword matching |
| Pipeline | `pipeline/extract_features.py` | Per-file features incl. recency-weighted bug score |
| Pipeline | `pipeline/fetch_commits.py` | Pull + classify + cache commit history |
| Tool 1 | `tools/bug_hotspot/scorer.py` | Weighted risk score (bug/churn/authors/complexity) |
| Tool 1 | `tools/bug_hotspot/explainer.py` | Plain-English "why" for every score |
| CLI | `cli.py` + `scripts/` | Interactive (`input()`-driven) menu interface |
| Tests | `tests/test_bug_hotspot.py` | Classifier, features, scorer, explanations |

### How the hotspot score works

For each file present at HEAD:

```
score = 0.40·bug + 0.25·churn + 0.15·authors + 0.20·complexity
```

- **bug** = Σ over bug-fix commits of `0.5 ^ (age_days / halflife)` (recent bugs
  weigh more; old ones decay). Half-life defaults to 30 days.
- **churn** = changes in the last 30 days.
- **authors** = distinct authors who touched the file.
- **complexity** = lines of code (LOC).

Each component is min-max normalized within the repo, so the score is a *relative*
ranking inside one repository — not a probability.

### Bonus — XGBoost "second opinion" (optional, ahead of schedule)

An optional ML counterpart to the weighted scorer was also built. It stays off
unless a model is trained, and is designed to generalize across languages.

| File | Purpose |
|------|---------|
| `tools/bug_hotspot/dataset.py` | Temporal-snapshot labeling (no leakage) |
| `tools/bug_hotspot/normalize.py` | Per-repo percentile normalization |
| `tools/bug_hotspot/ml_scorer.py` | XGBoost train / evaluate / predict |
| `pipeline/build_training_data.py` | Pool multiple repos → labeled dataset → train |
| `train_repos.txt` | List of repos to train on (with optional language tags) |
| `tests/test_ml_scorer.py` | Normalization, no-leakage labeling, train/predict |

Highlights: language-agnostic features (process metrics + LOC only), temporal
labeling to avoid leakage, cross-repo + held-out-language AUC evaluation, and an
honest `reliable: False` flag when there are too few positive examples. Train once,
reuse for all analyses. When a model exists, `analyze` adds an `ML` column and
flags files where the formula and the model disagree.

### CLI

Interactive menu (run `python cli.py`):

```
1) analyze        rank bug-hotspot files (+ XGBoost second opinion if trained)
2) pull           fetch & cache commit history
3) train          train the XGBoost second-opinion model (from train_repos.txt)
4) setup-indexes  create MongoDB indexes
5) config         show resolved settings
6) quit
```

### Tests

```
python tests/test_bug_hotspot.py     # weighted scorer, classifier, features
python tests/test_ml_scorer.py       # normalization, no-leakage labeling, train/predict
```
Both suites pass. The pure-logic core uses only the standard library, so the
weighted-scorer tests run with nothing installed.

### Dependencies

- **Required for full runs:** GitPython (installed). pymongo / radon are optional —
  the code degrades gracefully (JSON cache; LOC instead of cyclomatic complexity).
- **Optional (ML second opinion):** xgboost, scikit-learn, numpy.

### Known limitations / follow-ups

- The keyword classifier credits **every file in a "fix…" commit** as bug-related,
  so docs/config files (e.g. `README.md`, `.toml`) can show false-positive bug
  history. A targeted fix is planned.
- Hotspot rankings are coarse on very small repos (few commits / bug fixes).
- No hold-out validation yet — planned, to put a real accuracy number on Tool 1.

### Next up (v0.2 — Intelligence Layer)

- Ollama integration (local LLM)
- Commit Message Quality Analyzer (Tool 4)
- Developer Skill Profiler — basic classification (Tool 2)
