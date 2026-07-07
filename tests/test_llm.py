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
    pick_local_model,
)


def _settings(**over):
    base = dict(
        llm_provider="local",
        llm_model="",
        local_llm_base_url="http://localhost:1234/v1",
        local_llm_autoload=False,
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


def test_pick_local_model():
    models = [
        {"id": "embed-1", "type": "embeddings", "state": "loaded"},
        {"id": "qwen", "type": "llm", "state": "not-loaded"},
        {"id": "gemma", "type": "llm", "state": "loaded"},
    ]
    # a downloaded preferred model wins, reporting its own load state
    assert pick_local_model(models, "qwen") == ("qwen", False)
    # no preference -> an already-loaded chat model
    assert pick_local_model(models) == ("gemma", True)
    # unknown preference falls back to the loaded model
    assert pick_local_model(models, "nope") == ("gemma", True)
    # embeddings models are never picked
    assert pick_local_model([{"id": "e", "type": "embeddings", "state": "loaded"}]) == (None, False)
    assert pick_local_model([]) == (None, False)
    print("  ok: pick_local_model preference order")


def test_local_autoload_flow():
    # the factory wires the setting through (default off)
    assert get_llm(_settings(local_llm_autoload=True)).autoload is True
    assert get_llm(_settings()).autoload is False

    # an already-loaded model resolves the placeholder id without a load call
    llm = get_llm(_settings(local_llm_autoload=True))
    llm._downloaded_models = lambda: [{"id": "gemma", "type": "llm", "state": "loaded"}]

    def _no_load(_mid):
        raise AssertionError("no load expected for an already-loaded model")

    llm._jit_load = _no_load
    assert llm._ensure_model() is True
    assert llm.model == "gemma"
    # ...and the result is cached: a dead server no longer matters
    llm._downloaded_models = _no_load
    assert llm._ensure_model() is True

    # an unloaded model triggers a JIT load and adopts the id
    llm = get_llm(_settings(local_llm_autoload=True, llm_model="qwen"))
    calls = []
    llm._downloaded_models = lambda: [{"id": "qwen", "type": "llm", "state": "not-loaded"}]
    llm._jit_load = lambda mid: calls.append(mid) or True
    assert llm._ensure_model() is True
    assert calls == ["qwen"] and llm.model == "qwen"

    # JIT refused (disabled server-side) -> lms CLI fallback
    llm = get_llm(_settings(local_llm_autoload=True))
    llm._downloaded_models = lambda: [{"id": "m", "type": "llm", "state": "not-loaded"}]
    llm._jit_load = lambda mid: False
    llm._cli_load = lambda mid: True
    assert llm._ensure_model() is True

    # both load paths fail -> unavailable, no crash
    llm = get_llm(_settings(local_llm_autoload=True))
    llm._downloaded_models = lambda: [{"id": "m", "type": "llm", "state": "not-loaded"}]
    llm._jit_load = lambda mid: False
    llm._cli_load = lambda mid: False
    assert llm._ensure_model() is False

    # server down / no /api/v0 -> graceful False
    llm = get_llm(_settings(local_llm_autoload=True))

    def _boom():
        raise OSError("connection refused")

    llm._downloaded_models = _boom
    assert llm._ensure_model() is False

    # nothing downloaded -> graceful False
    llm = get_llm(_settings(local_llm_autoload=True))
    llm._downloaded_models = lambda: []
    assert llm._ensure_model() is False
    print("  ok: local autoload flow (resolve, load, fallback, degrade)")


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
