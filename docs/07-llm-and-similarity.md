# 07 — LLM provider layer & similarity engine

Two pluggable subsystems share the same philosophy: one small interface,
multiple backends, runtime selection, graceful fallback, and every run
announces what it picked.

## LLM provider layer (`core/llm.py`)

The LLM is **always optional**. Every rule-based feature works without one;
the LLM only adds commit-message rewrites (Tool 4), profile summaries
(Tool 2), PR diff summaries (Tool 3), and repo insight bullets (dashboard).

### Providers

Selected by `LLM_PROVIDER` in `.env`; constructed by `get_llm(settings)`
(which imports no SDK — SDKs load lazily on first use):

| `LLM_PROVIDER` | Class | Backend | Default model | Auth |
|---|---|---|---|---|
| `local` (default) | `LocalProvider` | LM Studio or any OpenAI-compatible server at `LOCAL_LLM_BASE_URL` | whatever the server has loaded | none |
| `openai` | `OpenAIProvider` | OpenAI API | `gpt-4o-mini` | `OPENAI_API_KEY` |
| `claude` | `ClaudeProvider` | Anthropic API (official `anthropic` SDK) | `claude-opus-4-8` | `ANTHROPIC_API_KEY` |
| `gemini` | `GeminiProvider` | Gemini via its OpenAI-compatible endpoint | `gemini-2.0-flash` | `GEMINI_API_KEY` |

LM Studio, OpenAI and Gemini all speak the OpenAI chat-completions protocol,
so they share one implementation (`_OpenAICompatProvider` — same `openai` SDK,
different base URL and key). Claude uses the `anthropic` SDK. `LLM_MODEL`
overrides the default model for any provider.

### The interface

```python
llm = get_llm(settings)
llm.available()    # cloud: is a key configured? local: actually ping the server
llm.generate(prompt, system=..., max_tokens=..., temperature=...)  # -> str
llm.describe()     # "claude (model=claude-opus-4-8)" — for status output
```

Two availability semantics on purpose: cloud providers just check for a key
(no surprise network calls at startup); the local provider genuinely pings
`GET /models` since there is no key to check. Failures raise
`LLMUnavailable`, which callers catch to skip the feature with a clear
message. CLI option 7 (`test-llm`) and `GET /test` surface all of this.

**A reachable server is not a usable one.** LM Studio answers `/models` happily
with nothing loaded, and then every `generate()` dies with *"No models loaded"*.
So `LocalProvider.available()` additionally verifies that a chat model is
actually loaded and that `LLM_MODEL` names a model that exists — otherwise it
reports unavailable and prints exactly what is wrong. Two traps it catches:

- `LLM_MODEL` must be LM Studio's **exact id, publisher prefix included**
  (`google/gemma-4-e4b`, not `gemma-4-e4b`). A near-miss id would otherwise let
  autoload silently load a *different* model.
- A downloaded-but-not-loaded model is not usable unless `LOCAL_LLM_AUTOLOAD=true`.

Servers that are not LM Studio (no `/api/v0` endpoint — Ollama, llama.cpp) skip
this check and simply trust the ping.

### LM Studio model autoload (opt-in)

With `LOCAL_LLM_AUTOLOAD=true`, the local provider fixes the most common
failure mode — *server running, no model loaded* — by loading one itself:

1. It queries LM Studio's native REST API (`/api/v0/models`, the only
   endpoint that reports downloaded-vs-loaded state) with stdlib urllib.
2. It picks a model: `LLM_MODEL` if that id is downloaded, else an
   already-loaded chat model, else the first downloaded one
   (`pick_local_model()` — pure and unit-tested).
3. If the pick isn't loaded, it triggers LM Studio's **just-in-time load**
   with a 1-token completion request, falling back to the `lms load` CLI
   when JIT loading is disabled server-side.

Every step announces itself with `[llm] autoload:` lines, the resolved model
id replaces the `local-model` placeholder (so `describe()` shows what will
actually run), and every failure degrades to "unavailable" — never a crash.
The toggle defaults to **off**, which is exactly the old behavior.

`FakeProvider` is the in-process test stub: canned response, records every
prompt, can simulate unavailability — this is how all LLM-adjacent code is
tested without a network.

## Similarity engine (`core/embeddings.py`)

Used by Tool 3 to compare a PR diff against the repo's past bug-fix diffs.
One interface, two backends:

```python
index = open_similarity_index(settings, collection="bugdiffs_owner_repo")
index.build(docs, fingerprint=fp)   # docs: [{"id", "text", "meta"}, ...]
index.query(text, k=5)              # -> [{"id", "score" (0..1 cosine), "meta"}, ...]
```

### `ChromaIndex` — preferred

`sentence-transformers` (`EMBEDDING_MODEL`, default `all-MiniLM-L6-v2`)
embeds each diff; vectors live in a **persistent ChromaDB collection**
(`CHROMA_PATH`, default `data/chroma`, cosine space). Real semantic
similarity — two diffs doing the same thing in different words score high.

**Per-repo collections, reused by fingerprint.** Each repo gets its own
collection (`collection_name(repo_key)` → `bugdiffs_<slug>`): a single shared
collection meant two concurrent reviews of *different* repos silently
corrupted each other's scores. A collection also carries its corpus
**fingerprint** — a cheap identity (`corpus_fingerprint`: count + first/last
qualifying SHA, computed without extracting any diffs). Before rebuilding,
`try_reuse(fingerprint)` adopts the persisted collection when the fingerprint
still matches, skipping both the git-show loop and the re-embedding that used
to run on every single review. `build(docs, fingerprint=...)` stamps the new
fingerprint into the collection metadata.

### `LiteIndex` — stdlib fallback

Pure-Python **TF-IDF cosine** index. Tokenizes diffs into identifiers and
numbers, weights by tf-idf, and computes exact cosine against every doc
(fine at Tool 3's corpus size, ≤ 400 diffs). Zero dependencies, so Tool 3
works on a fresh machine with nothing installed. It accepts the same
`build(docs, fingerprint=...)` signature but rebuilds in memory each time —
the fingerprint reuse is a Chroma-only optimization (nothing persists).

### Selection

`SIMILARITY_BACKEND` = `auto` (default: try Chroma, fall back to Lite),
`chroma` (hard requirement), or `lite` (skip the heavy deps). Every run
prints a `[backend] similarity: ...` line stating which index produced the
scores and whether it was the primary choice or a fallback — similarity
numbers are never ambiguous about their provenance.
