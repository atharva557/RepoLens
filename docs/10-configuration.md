# 10 — Configuration reference

All configuration lives in `config/settings.py` — a `Settings` dataclass
loaded by `Settings.load(".env")`. Real environment variables **override**
`.env` values. The `.env` parser is stdlib (no `python-dotenv`): it handles
comments, inline comments on unquoted values, and quoted values. Malformed
numeric values warn and fall back to the default instead of crashing.

Sensible defaults mean the project runs with **no configuration at all**
(JSON store, local LLM probing, no GitHub features).

The keys marked **runtime-editable** below (LLM provider/model/keys +
`GITHUB_TOKEN`) can also be set from the dashboard's Settings drawer, which
calls `PUT /config`: the live process picks them up immediately and
`persist_env()` writes them back to `.env` (seeding it from `.env.example`
first if it doesn't exist), so the CLI and the next server start agree.
Everything else stays file-only on purpose — a dashboard call shouldn't be
able to silently reshape analysis tuning.

## Credentials

| Variable | Default | Effect |
|---|---|---|
| `GITHUB_TOKEN` | *(unset)* | **Runtime-editable.** Enables Tool 2 (profiles), Tool 3 (PR fetch/post), repo header metadata, the recent-PRs list, and the webhook review path; raises the API rate limit 60 → 5,000 req/h. Cloning/pulling public repos and hotspot/commit-quality analysis work without it. |
| `GITHUB_WEBHOOK_SECRET` | *(unset)* | Enables `POST /webhook/github` (HMAC verification key). Unset → webhook returns `503`. |

## LLM provider

| Variable | Default | Effect |
|---|---|---|
| `LLM_PROVIDER` | `local` | **Runtime-editable.** `local` \| `openai` \| `claude` \| `gemini` |
| `LLM_MODEL` | *(per-provider default)* | **Runtime-editable.** `gpt-4o-mini` / `claude-opus-4-8` / `gemini-2.0-flash`; local uses the server's loaded model |
| `LOCAL_LLM_BASE_URL` | `http://localhost:1234/v1` | **Runtime-editable.** LM Studio (or any OpenAI-compatible server) |
| `LOCAL_LLM_AUTOLOAD` | `false` | auto-load a model in LM Studio when the server is up but nothing is loaded (JIT request, `lms load` fallback) |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` | *(unset)* | **Runtime-editable.** key for the matching provider |
| `LLM_MAX_TOKENS` | `512` | generation cap |
| `LLM_TEMPERATURE` | `0.2` | sampling temperature (not sent to Claude — current models reject it) |

## Storage

| Variable | Default | Effect |
|---|---|---|
| `GITPULSE_STORE` | `auto` | `auto` (try Mongo, fall back to JSON) \| `mongo` (require) \| `json` (skip Mongo) |
| `MONGODB_URI` | `mongodb://localhost:27017` | connection string |
| `MONGODB_DB` | `gitpulse` | database name |
| `GITPULSE_CACHE_DIR` | `data/cache` | JSON-store root + clone cache location |
| `CHROMA_PATH` | `data/chroma` | persistent ChromaDB collection (Tool 3) |

## Tool 1 — hotspot scoring

| Variable | Default | Effect |
|---|---|---|
| `BUG_KEYWORDS` | `fix,bug,resolve,patch,hotfix,closes` | comma-separated bug-fix classifier keywords |
| `CHURN_WINDOW_DAYS` | `30` | window for the churn component |
| `HOTSPOT_RECENCY_HALFLIFE_DAYS` | `30` | exponential decay half-life for the bug score |
| `HOTSPOT_LOOKBACK_DAYS` | `90` | *reserved — defined but not currently consumed by the pipeline* |

## Tool 1 — XGBoost second opinion

| Variable | Default | Effect |
|---|---|---|
| `ML_MODEL_PATH` | `data/models/hotspot_xgb.json` | where the trained model lives; absent file = ML off |
| `ML_LABEL_WINDOW_DAYS` | `90` | post-cutoff window that defines a positive label |
| `ML_SNAPSHOTS` | `4` | temporal cutoffs per training repo |
| `ML_MIN_POSITIVES` | `20` | below this many positive examples, training refuses (`reliable: False`) |

## Tool 2 — developer profiler

| Variable | Default | Effect |
|---|---|---|
| `PROFILE_MAX_REPOS` | `15` | public repos scanned per user |
| `PROFILE_MAX_COMMITS_PER_REPO` | `100` | commits fetched per repo |
| `PROFILE_PR_SAMPLE` | `8` | PR descriptions sampled for the LLM summary |
| `PROFILE_CACHE_HOURS` | `24` | age after which a served cached profile is labeled stale (reads are always database-first; GitHub only on explicit refresh) |

## Tool 3 — PR reviewer / similarity

| Variable | Default | Effect |
|---|---|---|
| `SIMILARITY_BACKEND` | `auto` | `auto` \| `chroma` (require) \| `lite` (force stdlib TF-IDF) |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | sentence-transformers model for ChromaIndex |
| `PR_SIMILARITY_TOP_K` | `5` | matches shown in the report |
| `PR_SIMILARITY_WARN` | `0.6` | cosine similarity that triggers a warning |
| `HOTSPOT_TOP_N` | `10` | a PR file inside the top-N hotspots counts as "high risk" |
| `PR_RISK_HIGH` | `0.5` | weighted PR risk score at or above this → HIGH |
| `PR_RISK_MEDIUM` | `0.2` | at or above this → MEDIUM (below → LOW) |

## API / webhook / dashboard

| Variable | Default | Effect |
|---|---|---|
| `GITPULSE_WEBHOOK_POST` | `false` | webhook also posts the Tool 3 report as a PR comment (opt-in; truthy values: `1/true/yes/on`) |
| `GITPULSE_CORS_ORIGINS` | `*` | comma-separated allowed origins for the dashboard (single-user mode) |

## Multi-user identity plane (v2 — see [12-identity-postgres.md](12-identity-postgres.md))

| Variable | Default | Effect |
|---|---|---|
| `MULTIUSER` | `false` | `true` enables `/api/v1/auth` + session-guarded triggers; **requires Postgres** |
| `IDENTITY_BACKEND` | `postgres` | `postgres` \| `memory`. `memory` is a **dev-only** escape hatch — accounts, sessions and stored keys live in process memory and reset on every restart; it exists so login can be demoed before Postgres is set up |
| `DATABASE_URL` | `postgresql://localhost:5432/gitpulse` | Postgres connection string (`IDENTITY_BACKEND=postgres` only). A bad/unreachable value fails startup with the specific fix, password masked |
| `FERNET_KEY` | *(unset)* | encrypts stored GitHub/LLM tokens — required in multiuser mode, never commit |
| `SESSION_SECRET` | *(unset)* | session/CSRF signing |
| `GITHUB_OAUTH_CLIENT_ID` / `GITHUB_OAUTH_CLIENT_SECRET` | *(unset)* | from a registered GitHub OAuth App |
| `DASHBOARD_ORIGIN` | `http://localhost:5173` | the CORS allow-origin (with credentials) in multiuser mode |

## Outbound email — signup verification codes (`core/mailer.py`)

Only used by the two-step signup under `MULTIUSER=true`. **Until `SMTP_HOST`,
`SMTP_USER` and `SMTP_PASSWORD` are all set, the console backend is selected**
and codes are printed to the server console instead of being emailed — so
signup works with no mail account at all. Nothing here is required to run the
app. All three are required together because a host with no login is never a
working config: a half-filled `.env` would otherwise fail every send instead
of falling back.

| Variable | Default | Effect |
|---|---|---|
| `SMTP_HOST` | *(unset)* | e.g. `smtp.gmail.com` |
| `SMTP_PORT` | `587` | `465` = implicit TLS (`SMTP_SSL`), `587` = STARTTLS. A server offering neither fails the send rather than authenticating in the clear |
| `SMTP_USER` | *(unset)* | full address, e.g. `you@gmail.com` |
| `SMTP_PASSWORD` | *(unset)* | Gmail: a 16-character **App Password** (needs 2FA on the account), not the account password. Ends are stripped so a trailing newline in `.env` can't cause a silent auth failure |
| `SMTP_FROM` | `SMTP_USER` | `From:` address — usually has to match the authenticated account |
| `SMTP_TIMEOUT` | `15` | seconds; sends run in a `BackgroundTasks` worker, so this bounds a hung handshake |
| `OTP_TTL_MINS` | `10` | how long a verification code stays valid |
| `APP_NAME` | `RepoLens` | `From:` display name and subject line |

Gmail caps around 500/day and mail from a residential IP often lands in spam.
For real deliverability, swap the transport for a provider's HTTP API — that
is one `send()` method, since the message building is stdlib either way.

## Inspecting the resolved config

- CLI option 9 (`config`) or `GET /config` — all values, secrets masked.
- `GET /test` — live checks: store round-trip, LLM availability, which
  similarity backend would be picked, token/webhook presence, and which mail
  backend is selected (configuration only — nothing is sent).
