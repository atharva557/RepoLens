"""Pluggable LLM provider layer.

Users choose a backend at config time via `LLM_PROVIDER`:

  - local   : LM Studio (or any OpenAI-compatible local server)   [default]
  - openai  : OpenAI API
  - claude  : Anthropic API
  - gemini  : Google Gemini (via its OpenAI-compatible endpoint)

The LLM is always *optional*: callers check `.available()` and degrade
gracefully when no provider is configured or reachable (same philosophy as
MongoDB and the XGBoost model in v0.1).

LM Studio, OpenAI and Gemini all speak the OpenAI chat-completions API, so they
share one client (the `openai` SDK, different base URL + key). Claude uses the
official `anthropic` SDK. Both SDKs are imported lazily, so the rest of GitPulse
runs without them installed.
"""
from __future__ import annotations


class LLMUnavailable(RuntimeError):
    """Raised when a provider is misconfigured or unreachable."""


# --------------------------------------------------------------------------- #
# base + OpenAI-compatible providers (local / openai / gemini)
# --------------------------------------------------------------------------- #
class LLMProvider:
    name = "base"

    def __init__(self, *, model, api_key="", base_url=None,
                 max_tokens=512, temperature=0.2):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.max_tokens = max_tokens
        self.temperature = temperature

    def available(self) -> bool:  # pragma: no cover - overridden
        raise NotImplementedError

    def generate(self, prompt: str, *, system: str | None = None,
                 max_tokens: int | None = None, temperature: float | None = None) -> str:
        raise NotImplementedError

    def describe(self) -> str:
        return f"{self.name} (model={self.model or '<server default>'})"


class _OpenAICompatProvider(LLMProvider):
    """Shared implementation for any OpenAI chat-completions-compatible server."""

    default_base_url: str | None = None

    def __init__(self, **kw):
        super().__init__(**kw)
        if self.base_url is None:
            self.base_url = self.default_base_url

    def _client(self):
        from openai import OpenAI  # lazy import

        return OpenAI(api_key=self.api_key or "not-needed", base_url=self.base_url)

    def available(self) -> bool:
        # cloud providers: a configured key is enough (avoid a surprise network call)
        return bool(self.api_key)

    def generate(self, prompt, *, system=None, max_tokens=None, temperature=None):
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        try:
            resp = self._client().chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens or self.max_tokens,
                temperature=self.temperature if temperature is None else temperature,
            )
        except Exception as exc:  # pragma: no cover - network dependent
            raise LLMUnavailable(f"{self.name} request failed: {exc}") from exc
        return (resp.choices[0].message.content or "").strip()


class LocalProvider(_OpenAICompatProvider):
    name = "local (LM Studio)"
    default_base_url = "http://localhost:1234/v1"

    def available(self) -> bool:
        # local server: actually ping it (no API key to check)
        try:
            self._client().models.list()
            return True
        except Exception:
            return False


class OpenAIProvider(_OpenAICompatProvider):
    name = "openai"
    default_base_url = None  # SDK default (api.openai.com)


class GeminiProvider(_OpenAICompatProvider):
    name = "gemini"
    default_base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"


# --------------------------------------------------------------------------- #
# Claude provider (official anthropic SDK)
# --------------------------------------------------------------------------- #
class ClaudeProvider(LLMProvider):
    name = "claude"

    def available(self) -> bool:
        return bool(self.api_key)

    def generate(self, prompt, *, system=None, max_tokens=None, temperature=None):
        import anthropic  # lazy import

        client = anthropic.Anthropic(api_key=self.api_key)
        kwargs = dict(
            model=self.model,
            max_tokens=max_tokens or self.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        if system:
            kwargs["system"] = system
        # NOTE: current Claude models reject `temperature`, so we don't send it.
        try:
            resp = client.messages.create(**kwargs)
        except Exception as exc:  # pragma: no cover - network dependent
            raise LLMUnavailable(f"claude request failed: {exc}") from exc
        return "".join(
            getattr(b, "text", "") for b in resp.content
            if getattr(b, "type", None) == "text"
        ).strip()


# --------------------------------------------------------------------------- #
# test stub
# --------------------------------------------------------------------------- #
class FakeProvider(LLMProvider):
    """In-process stub for tests — never touches the network."""

    name = "fake"

    def __init__(self, response="FAKE RESPONSE", available=True, **kw):
        super().__init__(model=kw.pop("model", "fake-1"), **kw)
        self._response = response
        self._available = available
        self.calls: list[dict] = []

    def available(self) -> bool:
        return self._available

    def generate(self, prompt, *, system=None, max_tokens=None, temperature=None):
        if not self._available:
            raise LLMUnavailable("fake provider unavailable")
        self.calls.append({"prompt": prompt, "system": system})
        return self._response


# default model per provider (used when LLM_MODEL is unset)
_DEFAULT_MODELS = {
    "local": "local-model",          # LM Studio uses whatever model is loaded
    "openai": "gpt-4o-mini",
    "claude": "claude-opus-4-8",     # latest Claude (override via LLM_MODEL)
    "gemini": "gemini-2.0-flash",
}


def get_llm(settings) -> LLMProvider:
    """Construct the configured provider. Does not import any SDK yet."""
    provider = (getattr(settings, "llm_provider", "local") or "local").lower()
    model = getattr(settings, "llm_model", "") or _DEFAULT_MODELS.get(provider, "")
    common = dict(
        model=model,
        max_tokens=getattr(settings, "llm_max_tokens", 512),
        temperature=getattr(settings, "llm_temperature", 0.2),
    )
    if provider == "local":
        return LocalProvider(base_url=settings.local_llm_base_url, api_key="", **common)
    if provider == "openai":
        return OpenAIProvider(api_key=settings.openai_api_key, **common)
    if provider == "claude":
        return ClaudeProvider(api_key=settings.anthropic_api_key, **common)
    if provider == "gemini":
        return GeminiProvider(api_key=settings.gemini_api_key, **common)
    raise LLMUnavailable(
        f"unknown LLM_PROVIDER '{provider}' (use: local | openai | claude | gemini)"
    )
