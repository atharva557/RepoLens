"""Tests for the pluggable LLM provider layer.

Covers the provider factory (which class + config you get per LLM_PROVIDER) and
the FakeProvider stub. No network calls and no provider SDKs required — the
factory constructs providers without importing any SDK, and FakeProvider is
in-process.

    python tests/test_llm.py
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.llm import (
    ClaudeProvider,
    FakeProvider,
    GeminiProvider,
    LLMUnavailable,
    LocalProvider,
    OpenAIProvider,
    get_llm,
)


def _settings(**over):
    base = dict(
        llm_provider="local",
        llm_model="",
        local_llm_base_url="http://localhost:1234/v1",
        anthropic_api_key="",
        openai_api_key="",
        gemini_api_key="",
        llm_max_tokens=512,
        llm_temperature=0.2,
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_factory_selects_provider_classes():
    assert isinstance(get_llm(_settings(llm_provider="local")), LocalProvider)
    assert isinstance(get_llm(_settings(llm_provider="openai")), OpenAIProvider)
    assert isinstance(get_llm(_settings(llm_provider="claude")), ClaudeProvider)
    assert isinstance(get_llm(_settings(llm_provider="gemini")), GeminiProvider)
    print("  ok: factory selects provider classes")


def test_factory_applies_defaults_and_config():
    local = get_llm(_settings(llm_provider="local"))
    assert local.model == "local-model"
    assert local.base_url == "http://localhost:1234/v1"

    claude = get_llm(_settings(llm_provider="claude", anthropic_api_key="sk-x"))
    assert claude.model == "claude-opus-4-8"     # latest Claude default
    assert claude.api_key == "sk-x"
    assert claude.available() is True

    # explicit LLM_MODEL overrides the per-provider default
    openai = get_llm(_settings(llm_provider="openai", llm_model="gpt-4o"))
    assert openai.model == "gpt-4o"

    gemini = get_llm(_settings(llm_provider="gemini"))
    assert gemini.base_url.startswith("https://generativelanguage.googleapis.com")
    print("  ok: factory applies defaults and config")


def test_cloud_availability_requires_key():
    assert get_llm(_settings(llm_provider="openai")).available() is False
    assert get_llm(_settings(llm_provider="openai", openai_api_key="k")).available() is True
    print("  ok: cloud availability requires a key")


def test_unknown_provider_raises():
    try:
        get_llm(_settings(llm_provider="bogus"))
    except LLMUnavailable as exc:
        assert "bogus" in str(exc)
        print("  ok: unknown provider raises")
        return
    raise AssertionError("expected LLMUnavailable")


def test_fake_provider():
    fake = FakeProvider(response="hello")
    assert fake.available() is True
    assert fake.generate("p", system="s") == "hello"
    assert fake.calls and fake.calls[0]["prompt"] == "p"

    down = FakeProvider(available=False)
    assert down.available() is False
    try:
        down.generate("p")
    except LLMUnavailable:
        print("  ok: fake provider (available + unavailable paths)")
        return
    raise AssertionError("expected LLMUnavailable from unavailable fake")


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    print(f"running {len(fns)} test(s)...")
    for fn in fns:
        fn()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    _run_all()
