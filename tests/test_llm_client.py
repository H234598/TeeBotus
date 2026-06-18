from __future__ import annotations

import sys
import types
import builtins

import pytest

from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.free_tier import (
    GeminiFreeTierGuard,
    GeminiFreeTierLimits,
    quota_owner_id,
    reset_gemini_free_tier_budget_state,
)
from TeeBotus.llm.gemini_interactions_provider import GeminiInteractionsClient, GeminiInteractionsSettings
from TeeBotus.llm.hf_pool.provider import HFPoolProvider
from TeeBotus.llm_client import LLMAPIError, LLMImage, LLMVoice, LiteLLMSettings, LiteLLMTextClient, build_text_llm_client, normalize_llm_provider


def test_build_text_llm_client_uses_openai_client_by_default() -> None:
    openai_client = object()

    assert build_text_llm_client(instructions=BotInstructions(), openai_client=openai_client) is openai_client


def test_neutral_voice_and_image_payloads_are_plain_capability_types() -> None:
    voice = LLMVoice(audio=b"voice", filename="voice.ogg", content_type="audio/ogg")
    image = LLMImage(data=b"png", filename="bild.png", content_type="image/png")

    assert voice.audio == b"voice"
    assert voice.filename == "voice.ogg"
    assert image.data == b"png"
    assert image.content_type == "image/png"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", "openai"),
        ("OpenAI", "openai"),
        ("lite-llm", "litellm"),
        ("LiteLLM", "litellm"),
        ("ollama", "ollama"),
        ("hf", "huggingface"),
        ("Google", "gemini"),
        ("gemini-stateful", "gemini_interactions"),
        ("Vertex", "vertex_ai"),
        ("google-vertex-ai", "vertex_ai"),
    ],
)
def test_normalize_llm_provider(value: str, expected: str) -> None:
    assert normalize_llm_provider(value) == expected


def test_litellm_text_client_calls_completion_with_instruction_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def completion(**kwargs):
        calls.append(kwargs)
        return {
            "id": "litellm-response",
            "choices": [{"message": {"content": "  Hallo  "}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
        }

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))
    monkeypatch.setenv("HF_TOKEN", "hf-secret")
    instructions = BotInstructions(
        llm_provider="litellm",
        llm_model="huggingface/meta-llama/Llama-3.1-8B-Instruct",
        llm_base_url="https://example.invalid",
        llm_api_key_env="HF_TOKEN",
        openai_max_output_tokens=123,
        openai_timeout_seconds=45,
        openai_system_prompt="System.",
    )

    response = LiteLLMTextClient(api_key="fallback-key").create_reply("Ping", instructions, "resp-old")

    assert response.text == "Hallo"
    assert response.response_id is None
    assert response.model == "huggingface/meta-llama/Llama-3.1-8B-Instruct"
    assert response.usage == {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}
    assert calls == [
        {
            "model": "huggingface/meta-llama/Llama-3.1-8B-Instruct",
            "messages": [
                {"role": "system", "content": "System."},
                {"role": "user", "content": "Ping"},
            ],
            "timeout": 45,
            "max_tokens": 123,
            "api_base": "https://example.invalid",
            "api_key": "hf-secret",
        }
    ]


def test_litellm_text_client_uses_default_key_when_instruction_env_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def completion(**kwargs):
        calls.append(kwargs)
        return {"choices": [{"message": {"content": "Hallo"}}]}

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))
    monkeypatch.delenv("MISSING_PROFILE_KEY", raising=False)

    response = LiteLLMTextClient(api_key="profile-key").create_reply(
        "Ping",
        BotInstructions(llm_model="huggingface/meta-llama/Llama-3.1-8B-Instruct", llm_api_key_env="MISSING_PROFILE_KEY"),
        None,
    )

    assert response.text == "Hallo"
    assert calls[0]["api_key"] == "profile-key"


def test_litellm_text_client_prefixes_provider_models_from_runtime_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def completion(**kwargs):
        calls.append(kwargs)
        return {"choices": [{"message": {"content": "lokal"}}]}

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))

    response = LiteLLMTextClient(
        provider="ollama",
        model="llama3.1:8b",
        api_base="http://localhost:11434",
    ).create_reply("Ping", BotInstructions(openai_model="gpt-would-be-wrong"), None)

    assert response.text == "lokal"
    assert calls[0]["model"] == "ollama/llama3.1:8b"
    assert calls[0]["api_base"] == "http://localhost:11434"
    assert "api_key" not in calls[0]


def test_litellm_text_client_prefixes_vertex_ai_models_from_runtime_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def completion(**kwargs):
        calls.append(kwargs)
        return {"choices": [{"message": {"content": "vertex"}}]}

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))

    response = LiteLLMTextClient(
        provider="vertex",
        model="gemini-2.5-flash",
    ).create_reply("Ping", BotInstructions(openai_model="gpt-would-be-wrong"), None)

    assert response.text == "vertex"
    assert calls[0]["model"] == "vertex_ai/gemini-2.5-flash"


def test_litellm_text_client_rotates_gemini_key_ring_on_usage_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def completion(**kwargs):
        api_key = str(kwargs.get("api_key") or "")
        calls.append(api_key)
        if api_key == "gemini-a1":
            exc = RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded")
            setattr(exc, "status_code", 429)
            raise exc
        return {"choices": [{"message": {"content": f"ok:{api_key}"}}]}

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))
    client = LiteLLMTextClient(
        LiteLLMSettings(
            provider="gemini",
            model="gemini-2.5-flash",
            api_key_ring=("gemini-a1", "gemini-b1"),
        )
    )
    response = client.create_reply("Ping", BotInstructions(), None)

    assert response.text == "ok:gemini-b1"
    assert calls == ["gemini-a1", "gemini-b1"]


def test_litellm_text_client_rotates_gemini_key_ring_before_free_tier_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_gemini_free_tier_budget_state()
    calls: list[str] = []
    limits = GeminiFreeTierLimits(
        requests_per_minute=100,
        input_tokens_per_minute=60,
        requests_per_day=100,
        reserve_input_tokens=5,
    )
    guard = GeminiFreeTierGuard(limits)
    owner = quota_owner_id(
        api_key="gemini-budget-a",
        provider="gemini",
        model="gemini/gemini-2.5-flash",
    )
    assert guard.reserve(
        quota_owner=owner,
        model="gemini/gemini-2.5-flash",
        estimated_input_tokens=35,
    ).allowed

    def completion(**kwargs):
        api_key = str(kwargs.get("api_key") or "")
        calls.append(api_key)
        return {"choices": [{"message": {"content": f"ok:{api_key}"}}], "usage": {"prompt_tokens": 12}}

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))
    client = LiteLLMTextClient(
        LiteLLMSettings(
            provider="gemini",
            model="gemini-2.5-flash",
            api_key_ring=("gemini-budget-a", "gemini-budget-b"),
            gemini_free_tier_limits=limits,
        )
    )
    response = client.create_reply("Ping", BotInstructions(openai_system_prompt="S."), None)

    assert response.text == "ok:gemini-budget-b"
    assert calls == ["gemini-budget-b"]


def test_litellm_text_client_does_not_rotate_key_ring_on_non_limit_error(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def completion(**kwargs):
        calls.append(str(kwargs.get("api_key") or ""))
        raise RuntimeError("provider exploded")

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))
    client = LiteLLMTextClient(
        LiteLLMSettings(
            provider="gemini",
            model="gemini-2.5-flash",
            api_key_ring=("gemini-nonlimit-a", "gemini-nonlimit-b"),
        )
    )

    with pytest.raises(LLMAPIError):
        client.create_reply("Ping", BotInstructions(), None)

    assert calls == ["gemini-nonlimit-a"]


def test_litellm_text_client_tries_fallback_models(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def completion(**kwargs):
        model = str(kwargs["model"])
        calls.append(model)
        if model == "ollama/broken":
            raise RuntimeError("down")
        return {"choices": [{"message": {"content": f"ok:{model}"}}]}

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))

    response = LiteLLMTextClient(
        provider="ollama",
        model="broken",
        fallback_models=("llama3.1:8b", "ollama/llama3.1:8b"),
    ).create_reply("Ping", BotInstructions(), None)

    assert calls == ["ollama/broken", "ollama/llama3.1:8b"]
    assert response.text == "ok:ollama/llama3.1:8b"
    assert response.model == "ollama/llama3.1:8b"


def test_litellm_text_client_keeps_explicit_cross_provider_fallback_prefixes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def completion(**kwargs):
        model = str(kwargs["model"])
        calls.append(model)
        if model == "ollama/broken":
            raise RuntimeError("down")
        return {"choices": [{"message": {"content": f"ok:{model}"}}]}

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))

    response = LiteLLMTextClient(
        provider="ollama",
        model="broken",
        fallback_models=("groq/llama-3.3-70b-versatile", "openai/gpt-4.1-mini"),
    ).create_reply("Ping", BotInstructions(), None)

    assert calls == ["ollama/broken", "groq/llama-3.3-70b-versatile"]
    assert response.model == "groq/llama-3.3-70b-versatile"


def test_litellm_text_client_redacts_provider_errors_from_logs_and_exception(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    def completion(**_kwargs):
        raise RuntimeError("provider rejected api_key=hf-test-secret and bearer sk-test-secret123456")

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))
    client = LiteLLMTextClient(
        provider="huggingface",
        model="meta-llama/Llama-3.1-8B-Instruct",
        api_key="hf-test-secret",
    )

    with caplog.at_level("WARNING", logger="TeeBotus.llm.litellm_provider"):
        with pytest.raises(LLMAPIError) as error:
            client.create_reply("Ping", BotInstructions(), None)

    error_text = str(error.value)
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    combined = error_text + "\n" + log_text

    assert "provider=huggingface" in combined
    assert "model=huggingface/meta-llama/Llama-3.1-8B-Instruct" in combined
    assert "hf-test-secret" not in combined
    assert "sk-test-secret123456" not in combined
    assert "<redacted>" in combined


def test_litellm_text_client_redacts_common_provider_key_shapes(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    tokens = [
        "hf_" + "A" * 16,
        "gsk_" + "B" * 16,
        "AIza" + "C" * 24,
        "github_" + "pat_" + "D" * 24,
        "gh" + "p_" + "E" * 16,
        "gl" + "pat-" + "F" * 16,
        "sy" + "t_" + "G" * 16,
        "xox" + "b-" + "H" * 16,
    ]

    def completion(**_kwargs):
        raise RuntimeError("provider leaked " + " ".join(tokens))

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))
    client = LiteLLMTextClient(
        provider="groq",
        model="llama-3.1-8b-instant",
        api_key="gsk_" + "I" * 16,
    )

    with caplog.at_level("WARNING", logger="TeeBotus.llm.litellm_provider"):
        with pytest.raises(LLMAPIError) as error:
            client.create_reply("Ping", BotInstructions(), None)

    combined = str(error.value) + "\n" + "\n".join(record.getMessage() for record in caplog.records)
    for token in tokens:
        assert token not in combined
    assert "provider=groq" in combined
    assert "model=groq/llama-3.1-8b-instant" in combined
    assert "hf_<redacted>" in combined
    assert "gsk_<redacted>" in combined
    assert "AIza<redacted>" in combined
    assert "github_pat_<redacted>" in combined
    assert "gh_<redacted>" in combined
    assert "glpat-<redacted>" in combined
    assert "syt_<redacted>" in combined
    assert "xox-<redacted>" in combined


def test_litellm_provider_alias_requires_explicit_model() -> None:
    with pytest.raises(LLMAPIError, match="requires llm_model"):
        LiteLLMTextClient(provider="ollama").create_reply("Ping", BotInstructions(openai_model="gpt-would-be-wrong"), None)


def test_build_text_llm_client_uses_runtime_provider_override() -> None:
    client = build_text_llm_client(
        instructions=BotInstructions(llm_provider="openai", llm_model="ignored"),
        openai_client=None,
        provider="huggingface",
        model="meta-llama/Llama-3.1-8B-Instruct",
        fallback_models="Qwen/Qwen2.5-7B-Instruct, mistralai/Mistral-7B-Instruct-v0.3",
        api_key="hf-key",
    )

    assert isinstance(client, LiteLLMTextClient)
    assert client.provider == "huggingface"
    assert client.model == "meta-llama/Llama-3.1-8B-Instruct"
    assert client.fallback_models == ("Qwen/Qwen2.5-7B-Instruct", "mistralai/Mistral-7B-Instruct-v0.3")
    assert client.api_key == "hf-key"


def test_build_text_llm_client_can_build_gemini_interactions_client() -> None:
    client = build_text_llm_client(
        instructions=BotInstructions(llm_provider="openai", llm_model="ignored"),
        openai_client=None,
        provider="gemini_interactions",
        model="gemini/gemini-3.5-flash",
        api_key="gemini-key",
        service_tier="flex",
        gemini_free_tier_limits=GeminiFreeTierLimits(enabled=False),
    )

    assert isinstance(client, GeminiInteractionsClient)
    assert client.provider == "gemini_interactions"
    assert client.model == "gemini-3.5-flash"
    assert client.store is True
    assert client.service_tier == "flex"
    assert client.capabilities.previous_response_id is True


def test_gemini_interactions_client_sends_stateful_request(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []
    keys: list[str] = []

    class Interaction:
        output_text = "  Hallo Gemini  "
        id = "interaction-1"
        usage = {"input_tokens": 3, "output_tokens": 2}

    class Interactions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return Interaction()

    class Client:
        def __init__(self, *, api_key):
            keys.append(api_key)
            self.interactions = Interactions()

    import google.genai as genai

    monkeypatch.setattr(genai, "Client", Client)
    client = GeminiInteractionsClient(
        GeminiInteractionsSettings(
            model="gemini/gemini-3.5-flash",
            api_key="gemini-key",
            service_tier="flex",
            gemini_free_tier_limits=GeminiFreeTierLimits(enabled=False),
        )
    )

    response = client.create_reply("Ping", BotInstructions(openai_system_prompt="System.", openai_max_output_tokens=77), "prev-1")

    assert response.text == "Hallo Gemini"
    assert response.response_id == "interaction-1"
    assert response.provider == "gemini_interactions"
    assert response.model == "gemini/gemini-3.5-flash"
    assert response.service_tier == "flex"
    assert response.usage == {"input_tokens": 3, "output_tokens": 2}
    assert keys == ["gemini-key"]
    assert calls == [
        {
            "input": "Ping",
            "model": "gemini-3.5-flash",
            "store": True,
            "system_instruction": "System.",
            "generation_config": {"max_output_tokens": 77},
            "response_modalities": ["text"],
            "timeout": 90,
            "previous_interaction_id": "prev-1",
            "service_tier": "flex",
        }
    ]


def test_build_text_llm_client_passes_env_to_hf_pool_provider() -> None:
    env = {"HF_TOKEN_MAIN": "hf-secret", "TEEBOTUS_HF_POOL_LIVE": "0"}

    client = build_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        provider="hf_pool",
        model="pool:default#normal_chat",
        env=env,
    )

    assert isinstance(client, HFPoolProvider)
    assert client.env is env


def test_litellm_text_client_requires_installed_litellm(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "litellm":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(LLMAPIError, match="LiteLLM is not installed"):
        LiteLLMTextClient().create_reply("Ping", BotInstructions(llm_model="ollama/llama3"), None)
