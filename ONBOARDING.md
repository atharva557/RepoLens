# Welcome to RepoLens! 🚀

Welcome to the team! This onboarding document is designed to get you up to speed with **RepoLens** (formerly GitPulse). Here you'll find everything you need to understand how the project is structured, what each file does, and the philosophy behind our design choices.

## 1. What is RepoLens?

RepoLens is a GitHub Analytics & Intelligence Platform. It analyzes a repository's git history to answer practical questions for maintainers, such as:
- *Which files are most likely to break next?*
- *What kind of code does a specific developer write?*
- *Is this pull request risky?*
- *Are our commit messages useful?*

The platform consists of **four main analysis tools** built on a **shared data pipeline**, which can be accessed via an **interactive CLI** or a **FastAPI web backend**, with results persisted in **MongoDB**.

---

## 2. Directory Structure & What Each File Does

Here is a breakdown of the repository structure and the purpose of the key files and directories.

### 🌐 Interfaces
- **`cli.py`**: The interactive command-line interface. You can run `python cli.py` on a bare machine to interact with all the tools.
- **`api/`**: Contains the FastAPI web backend.
  - `main.py`: The entry point for the FastAPI application. It defines the routes for triggering jobs and fetching reports.
  - `auth.py`: Handles API authentication and security.
  - `jobs.py`: Manages background tasks (since analysis can take time).
  - `webhook.py`: Listens to GitHub webhooks (e.g., auto-running PR reviews when a new PR is opened).

### 🛠️ The Four Analysis Tools (`tools/`)
Each tool answers a specific question and lives in its own subdirectory:
- **`bug_hotspot/`**: Predicts which files will break next using a recency-weighted risk score (and an optional XGBoost model).
- **`dev_profiler/`**: Classifies a user's GitHub activity into profiles like "Bug Fixer", "Refactorer", etc.
- **`pr_reviewer/`**: Analyzes pull requests for risk by checking for hotspot modifications, missing tests, and diff similarity to past bugs.
- **`commit_quality/`**: Scores commit messages (0-10) based on length, context, and imperatives, with an optional LLM rewrite feature.

### ⚙️ Shared Pipeline (`pipeline/`)
The shared data pipeline that feeds the tools. It fetches, classifies, and extracts features from the Git history.
- `fetch_commits.py`: Pulls commit history and per-file stats.
- `classify_commits.py`: Detects bug-fix commits using keyword detection (the SZZ algorithm starting point).
- `extract_features.py`: Aggregates features per file for the models.
- `build_bug_index.py` & `build_training_data.py`: Utilities for preparing data for the ML/similarity models.

### 🧠 Core Services (`core/`)
The foundational services used across the app:
- `git_client.py`: Wrapper around GitPython for local repository operations.
- `github_client.py`: Wrapper around PyGithub for interacting with the GitHub API.
- `db.py`: Database connection logic. Supports MongoDB with a transparent fallback to local JSON files.
- `llm.py`: Pluggable LLM interface supporting LM Studio, OpenAI, Claude, and Gemini.
- `embeddings.py`: Handles vector embeddings (using ChromaDB or a TF-IDF fallback) for diff similarity.
- `identity.py`: Manages the multi-user identity plane.

### 📁 Other Important Folders
- **`config/`** (`settings.py`, `.env`): Handles environment variables, feature flags, and tunable weights.
- **`frontend/`**: The React dashboard.
- **`scripts/`**: Helper scripts for setup, pulling repos, and running analyses.
- **`tests/`**: Over 100 network-free tests for validating functionality.
- **`.env.example`**: The template for environment variables.

---

## 3. Key Design Decisions (The "Why")

To understand *why* the codebase is written this way, you need to understand our core philosophies: **Explainability** and **Graceful Degradation**.

1. **Explainable Formulas over Black-Box ML (Bug Hotspots):**
   *Why is our formula primary and XGBoost secondary?*
   - **The Small Data Problem**: Most individual repositories don't have enough commit history to train a robust ML model. Training XGBoost on a single repo leads to massive label leakage and memorization rather than actual learning.
   - **Explainability**: Our founding principle is explainability over black-box accuracy. A maintainer needs to know *why* a file is risky. Our primary hotspot score uses a transparent, tunable formula (weighting recent bugs, churn, authors, and complexity) so we can always say, "This file is a hotspot because it had 4 bugs in the last 30 days."
   - **The Role of XGBoost**: We only use XGBoost as an *optional second opinion*. To avoid the small-data problem, it is trained on *pooled* cross-repo data with strict temporal labeling. It's there to catch complex patterns the formula might miss, but it's not the primary source of truth.

2. **Graceful Degradation Everywhere:**
   *Why?* We want the tool to be usable out-of-the-box by anyone, anywhere. Every heavy dependency has a fallback:
   - **Storage:** If MongoDB is unreachable, `db.py` silently falls back to a JSON file cache.
   - **LLMs:** LLMs (OpenAI, Claude, local LM Studio) are *strictly optional*. Every rule-based feature works without them; LLMs only add enhancements like summaries and rewrites.
   - **Similarity:** If `sentence-transformers` and ChromaDB aren't installed, we fall back to a standard TF-IDF cosine index.

3. **MongoDB over SQLite:**
   *Why?* Our analysis reports are highly nested and document-shaped (e.g., a PR review contains a list of files, risk scores, summaries). This maps perfectly to NoSQL/MongoDB rather than relational tables.

4. **Precise Bug Attribution:**
   *Why?* A commit message might say "Fix issue", but if it also bumps a version in `package.json` or edits a `README.md`, those files shouldn't be penalized as "buggy". Our pipeline actively filters non-source files from being credited with bug history.

---

## 4. Getting Started

1. Review `.env.example` and create your own `.env` file to configure your local environment.
2. **CLI Experience**: Run `python cli.py` to experience the core analytical tools in your terminal.
3. **API Experience**: Check out `run.bat` or run the FastAPI server via `uvicorn api.main:app` (or similar).
4. **Deep Dive**: Read through `PROJECT_OVERVIEW.md` and `TECHNICAL_DEEP_DIVE.md` for a more granular look at the data flow, the exact formula for hotspot scoring, and the ML architecture.

If you have any questions, don't hesitate to explore the tests or ask the team. Happy coding! 🎉
