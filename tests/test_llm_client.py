from __future__ import annotations

import hashlib
import sys
import types
import builtins
from decimal import Decimal
from fractions import Fraction

import pytest

from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.free_tier import (
    GeminiFreeTierGuard,
    GeminiFreeTierLimits,
    estimate_litellm_input_tokens,
    quota_owner_id,
    reset_gemini_free_tier_budget_state,
)
from TeeBotus.llm.gemini_interactions_provider import GeminiInteractionsClient, GeminiInteractionsSettings
from TeeBotus.llm.hf_pool.provider import HFPoolProvider
from TeeBotus.llm import litellm_provider
from TeeBotus.llm.litellm_gemini_provider import LiteLLMGeminiStatefulClient, LiteLLMGeminiStatefulSettings
from TeeBotus.llm_client import (
    LLMAPIError,
    LLMImage,
    LLMVoice,
    LiteLLMSettings,
    LiteLLMTextClient,
    build_text_llm_client,
    normalize_llm_provider,
    parse_fallback_models,
)


def test_build_text_llm_client_routes_default_openai_text_through_litellm() -> None:
    openai_client = object()
    client = build_text_llm_client(instructions=BotInstructions(), openai_client=openai_client)

    assert isinstance(client, LiteLLMTextClient)
    assert client.provider == "litellm"
    assert client.model == "openai/gpt-5.5"


def test_gemini_rest_is_not_supported_as_text_llm_provider() -> None:
    with pytest.raises(LLMAPIError, match="Unsupported LLM provider: gemini_rest"):
        build_text_llm_client(
            instructions=BotInstructions(),
            openai_client=None,
            provider="gemini_rest",
            model="gemini/gemini-2.5-flash",
            api_key="gemini-key",
        )


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
        ("gemini-stateful", "litellm_gemini_stateful"),
        ("litellm-gemini-stateless", "litellm_gemini_stateless"),
        ("litellm-gemini-stateful", "litellm_gemini_stateful"),
        ("litellm-gemini-paid-stateless", "litellm_gemini_paid_stateless"),
        ("litellm-gemini-paid-statefull", "litellm_gemini_paid_stateful"),
        ("Vertex", "vertex_ai"),
        ("google-vertex-ai", "vertex_ai"),
    ],
)
def test_normalize_llm_provider(value: str, expected: str) -> None:
    assert normalize_llm_provider(value) == expected


def test_parse_fallback_models_accepts_sequence_values() -> None:
    assert parse_fallback_models([" groq/llama ", "", "ollama/llama3.1:8b"]) == (
        "groq/llama",
        "ollama/llama3.1:8b",
    )


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


def test_litellm_text_client_extracts_text_from_content_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    def completion(**_kwargs):
        return {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "Text", "text": "  Hallo  "},
                            {"type": "image_url", "image_url": {"url": "https://example.invalid/bild.png"}},
                            {"type": "OUTPUT_TEXT", "text": "Welt  "},
                            {"type": "text", "text": {"value": "verschachtelt"}},
                            {"type": "text", "content": {"text": "Content-Feld"}},
                        ]
                    }
                }
            ],
        }

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))

    response = LiteLLMTextClient(provider="litellm", model="openai/gpt-test").create_reply(
        "Ping",
        BotInstructions(openai_system_prompt="System."),
        None,
    )

    assert response.text == "Hallo\nWelt\nverschachtelt\nContent-Feld"


def test_litellm_text_client_uses_first_nonempty_choice_text(monkeypatch: pytest.MonkeyPatch) -> None:
    def completion(**_kwargs):
        return {
            "choices": [
                {"message": {"content": "   "}},
                {"message": {"content": "  zweite Antwort  "}},
            ],
        }

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))

    response = LiteLLMTextClient(provider="litellm", model="openai/gpt-test").create_reply(
        "Ping",
        BotInstructions(openai_system_prompt="System."),
        None,
    )

    assert response.text == "zweite Antwort"


def test_litellm_text_client_extracts_choice_level_text(monkeypatch: pytest.MonkeyPatch) -> None:
    def completion(**_kwargs):
        return {"choices": [{"text": "  Completion-Antwort  "}]}

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))

    response = LiteLLMTextClient(provider="litellm", model="openai/gpt-test").create_reply(
        "Ping",
        BotInstructions(openai_system_prompt="System."),
        None,
    )

    assert response.text == "Completion-Antwort"


def test_litellm_text_client_extracts_text_from_attr_objects_with_unusual_getitem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class AttrOnly:
        def __init__(self, **fields: object) -> None:
            self.__dict__.update(fields)

        def __getitem__(self, _key: str) -> object:
            raise IndexError("SDK object has no mapping item")

    def completion(**_kwargs):
        return AttrOnly(choices=[AttrOnly(message=AttrOnly(content="  Objekt-Antwort  "))])

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))

    response = LiteLLMTextClient(provider="litellm", model="openai/gpt-test").create_reply(
        "Ping",
        BotInstructions(openai_system_prompt="System."),
        None,
    )

    assert response.text == "Objekt-Antwort"


def test_litellm_text_client_extracts_text_from_attr_content_object(monkeypatch: pytest.MonkeyPatch) -> None:
    class AttrContent:
        text = "  Content-Objekt  "

        def __getitem__(self, _key: str) -> object:
            raise ValueError("SDK object has no mapping item")

    def completion(**_kwargs):
        return {"choices": [{"message": {"content": AttrContent()}}]}

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))

    response = LiteLLMTextClient(provider="litellm", model="openai/gpt-test").create_reply(
        "Ping",
        BotInstructions(openai_system_prompt="System."),
        None,
    )

    assert response.text == "Content-Objekt"


def test_litellm_text_client_does_not_emit_unstructured_content_object_repr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class OpaqueContent:
        def __repr__(self) -> str:
            return "<OpaqueContent should-not-leak>"

    def completion(**_kwargs):
        return {"choices": [{"message": {"content": OpaqueContent()}}]}

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))

    with pytest.raises(LLMAPIError) as error:
        LiteLLMTextClient(provider="litellm", model="openai/gpt-test").create_reply(
            "Ping",
            BotInstructions(openai_system_prompt="System."),
            None,
        )

    assert "should-not-leak" not in str(error.value)
    assert "empty text" in str(error.value)


def test_litellm_gemini_stateless_provider_reports_response_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response(dict):
        _hidden_params = {"response_cost": 0.0042}

    def completion(**kwargs):
        return Response(
            {
                "choices": [{"message": {"content": f"ok:{kwargs['model']}"}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
            }
        )

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))
    client = LiteLLMTextClient(
        LiteLLMSettings(
            provider="litellm-gemini-stateless",
            model="gemini-3.5-flash",
            gemini_free_tier_limits=GeminiFreeTierLimits(enabled=False),
        )
    )

    response = client.create_reply("Ping", BotInstructions(openai_system_prompt="System."), None)

    assert response.provider == "litellm_gemini_stateless"
    assert response.model == "gemini/gemini-3.5-flash"
    assert response.usage["response_cost"] == 0.0042


def test_litellm_text_client_keeps_object_usage_token_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    class Usage:
        input_tokens = 4
        output_tokens = 3
        input_token_count = 4
        output_token_count = 3
        total_token_count = 7
        total_tokens = 7
        cached_tokens = 2
        total_cached_tokens = 2
        reasoning_tokens = 1
        prompt_tokens_details = {"cached_tokens": 2}
        completion_tokens_details = {"reasoning_tokens": 1}

    def completion(**kwargs):
        return {
            "choices": [{"message": {"content": f"ok:{kwargs['model']}"}}],
            "usage": Usage(),
        }

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))
    client = LiteLLMTextClient(
        LiteLLMSettings(
            provider="litellm-gemini-stateless",
            model="gemini-3.5-flash",
            gemini_free_tier_limits=GeminiFreeTierLimits(enabled=False),
        )
    )

    response = client.create_reply("Ping", BotInstructions(openai_system_prompt="System."), None)

    assert response.usage == {
        "input_tokens": 4,
        "output_tokens": 3,
        "input_token_count": 4,
        "output_token_count": 3,
        "total_token_count": 7,
        "total_tokens": 7,
        "cached_tokens": 2,
        "total_cached_tokens": 2,
        "reasoning_tokens": 1,
        "prompt_tokens_details": {"cached_tokens": 2},
        "completion_tokens_details": {"reasoning_tokens": 1},
    }


def test_litellm_text_client_ignores_broken_optional_usage_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    class Usage:
        input_tokens = 4
        total_tokens = 7

        @property
        def model_dump(self) -> object:
            raise RuntimeError("model_dump property unavailable")

        @property
        def output_tokens(self) -> object:
            raise RuntimeError("output_tokens property unavailable")

    def completion(**kwargs):
        return {
            "choices": [{"message": {"content": f"ok:{kwargs['model']}"}}],
            "usage": Usage(),
        }

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))
    client = LiteLLMTextClient(
        LiteLLMSettings(
            provider="litellm-gemini-stateless",
            model="gemini-3.5-flash",
            gemini_free_tier_limits=GeminiFreeTierLimits(enabled=False),
        )
    )

    response = client.create_reply("Ping", BotInstructions(openai_system_prompt="System."), None)

    assert response.text == "ok:gemini/gemini-3.5-flash"
    assert response.usage == {"input_tokens": 4, "total_tokens": 7}


def test_litellm_compact_usage_log_keeps_cache_and_reasoning_counts() -> None:
    assert litellm_provider._compact_usage_for_log(
        {
            "input_tokens": 4,
            "input_token_count": 4,
            "output_tokens": 3,
            "output_token_count": 3,
            "total_token_count": 7,
            "cache_read_input_tokens": 2,
            "cache_creation_input_tokens": 1,
            "reasoning_tokens": 5,
            "response_cost": 0.0012,
            "prompt_tokens_details": {"cached_tokens": 2},
        }
    ) == {
        "input_tokens": 4,
        "input_token_count": 4,
        "output_tokens": 3,
        "output_token_count": 3,
        "total_token_count": 7,
        "cache_read_input_tokens": 2,
        "cache_creation_input_tokens": 1,
        "reasoning_tokens": 5,
        "response_cost": 0.0012,
    }


def test_litellm_gemini_paid_stateless_disables_free_tier_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def completion(**kwargs):
        calls.append(str(kwargs.get("api_key") or ""))
        return {
            "choices": [{"message": {"content": "paid ok"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        }

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))
    client = LiteLLMTextClient(
        LiteLLMSettings(
            provider="litellm-gemini-paid-stateless",
            model="gemini-3.5-flash",
            api_key_ring=("paid-a",),
            gemini_free_tier_limits=GeminiFreeTierLimits(
                enabled=True,
                requests_per_minute=0,
                input_tokens_per_minute=0,
                requests_per_day=0,
            ),
        )
    )

    response = client.create_reply("Ping", BotInstructions(openai_system_prompt="System."), None)

    assert response.text == "paid ok"
    assert response.provider == "litellm_gemini_paid_stateless"
    assert client.gemini_free_tier_limits.status_summary() == "off"
    assert calls == ["paid-a"]


def test_litellm_paid_gemini_fallback_disables_explicit_free_tier_limits() -> None:
    client = LiteLLMTextClient(
        LiteLLMSettings(
            provider="litellm-gemini-paid-stateless",
            model="openai/gpt-primary",
            fallback_models=("gemini/gemini-3.5-flash",),
            gemini_free_tier_limits=GeminiFreeTierLimits(
                enabled=True,
                requests_per_minute=0,
                input_tokens_per_minute=0,
                requests_per_day=0,
            ),
        )
    )

    assert client.gemini_free_tier_limits.status_summary() == "off"


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


def test_quota_owner_id_does_not_use_plain_sha256_api_key_fingerprint() -> None:
    api_key = "gemini-budget-secret-key"

    owner = quota_owner_id(api_key=api_key, provider="google_gemini", model="gemini/gemini-2.5-flash")
    repeated = quota_owner_id(api_key=api_key, provider="google_gemini", model="gemini/gemini-2.5-flash")
    plain_sha256_prefix = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]

    assert owner == repeated
    assert owner.startswith("google_gemini:gemini/gemini-2.5-flash:")
    assert api_key not in owner
    assert plain_sha256_prefix not in owner


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
        provider="google_gemini",
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


def test_litellm_text_client_uses_gemini_key_ring_only_for_gemini_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, str]] = []

    def completion(**kwargs):
        model = str(kwargs["model"])
        api_key = str(kwargs.get("api_key") or "")
        service_tier = str(kwargs.get("service_tier") or "")
        calls.append((model, api_key, service_tier))
        if model == "openai/gpt-test":
            raise RuntimeError("primary unavailable")
        return {"choices": [{"message": {"content": f"ok:{api_key}"}}]}

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))

    response = LiteLLMTextClient(
        LiteLLMSettings(
            provider="litellm",
            model="openai/gpt-test",
            api_key="openai-key",
            fallback_models=("gemini/gemini-3.5-flash",),
            fallback_api_keys={"gemini/gemini-3.5-flash": "single-gemini-key"},
            api_key_ring=("gemini-ring-a", "gemini-ring-b"),
            service_tier="flex",
        )
    ).create_reply("Ping", BotInstructions(), None)

    assert response.text == "ok:gemini-ring-a"
    assert response.model == "gemini/gemini-3.5-flash"
    assert calls == [
        ("openai/gpt-test", "openai-key", ""),
        ("gemini/gemini-3.5-flash", "gemini-ring-a", "flex"),
    ]


def test_litellm_text_client_does_not_use_gemini_ring_for_explicit_openai_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, str]] = []

    def completion(**kwargs):
        model = str(kwargs["model"])
        api_key = str(kwargs.get("api_key") or "")
        service_tier = str(kwargs.get("service_tier") or "")
        calls.append((model, api_key, service_tier))
        if model == "gemini/gemini-3.5-flash":
            raise RuntimeError("primary unavailable")
        return {"choices": [{"message": {"content": f"ok:{api_key}"}}]}

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))

    response = LiteLLMTextClient(
        LiteLLMSettings(
            provider="litellm_gemini_stateless",
            model="gemini/gemini-3.5-flash",
            api_key="single-gemini-key",
            fallback_models=("openai/gpt-test",),
            fallback_api_keys={"openai/gpt-test": "openai-key"},
            api_key_ring=("gemini-ring-a", "gemini-ring-b"),
            service_tier="flex",
        )
    ).create_reply("Ping", BotInstructions(), None)

    assert response.text == "ok:openai-key"
    assert response.model == "openai/gpt-test"
    assert calls == [
        ("gemini/gemini-3.5-flash", "gemini-ring-a", "flex"),
        ("openai/gpt-test", "openai-key", ""),
    ]


def test_litellm_text_client_normalizes_fallback_api_key_model_names(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, str]] = []

    def completion(**kwargs):
        model = str(kwargs["model"])
        api_key = str(kwargs.get("api_key") or "")
        api_base = str(kwargs.get("api_base") or "")
        calls.append((model, api_key, api_base))
        if model == "groq/primary-down":
            raise RuntimeError("primary unavailable")
        return {"choices": [{"message": {"content": f"ok:{api_key}"}}]}

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))

    response = LiteLLMTextClient(
        LiteLLMSettings(
            provider="groq",
            model="primary-down",
            api_key="primary-key",
            fallback_models=("fallback-ok",),
            fallback_api_keys={"fallback-ok": "fallback-key"},
            fallback_api_bases={"fallback-ok": "https://groq.example/v1"},
        )
    ).create_reply("Ping", BotInstructions(), None)

    assert response.text == "ok:fallback-key"
    assert response.model == "groq/fallback-ok"
    assert calls == [
        ("groq/primary-down", "primary-key", ""),
        ("groq/fallback-ok", "fallback-key", "https://groq.example/v1"),
    ]


def test_litellm_text_client_does_not_reuse_primary_credentials_for_cross_provider_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, str]] = []

    def completion(**kwargs):
        model = str(kwargs["model"])
        api_key = str(kwargs.get("api_key") or "")
        api_base = str(kwargs.get("api_base") or "")
        calls.append((model, api_key, api_base))
        if model == "openai/gpt-primary":
            raise RuntimeError("primary unavailable")
        return {"choices": [{"message": {"content": f"ok:{model}"}}]}

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))

    response = LiteLLMTextClient(
        LiteLLMSettings(
            provider="litellm",
            model="openai/gpt-primary",
            api_key="openai-key",
            api_base="https://openai.example/v1",
            fallback_models=("groq/llama-3.1-8b-instant",),
        )
    ).create_reply("Ping", BotInstructions(), None)

    assert response.model == "groq/llama-3.1-8b-instant"
    assert calls == [
        ("openai/gpt-primary", "openai-key", "https://openai.example/v1"),
        ("groq/llama-3.1-8b-instant", "", ""),
    ]


def test_litellm_text_client_reuses_primary_credentials_for_same_provider_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, str]] = []

    def completion(**kwargs):
        model = str(kwargs["model"])
        api_key = str(kwargs.get("api_key") or "")
        api_base = str(kwargs.get("api_base") or "")
        calls.append((model, api_key, api_base))
        if model == "groq/primary-down":
            raise RuntimeError("primary unavailable")
        return {"choices": [{"message": {"content": f"ok:{api_key}"}}]}

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))

    response = LiteLLMTextClient(
        LiteLLMSettings(
            provider="groq",
            model="primary-down",
            api_key="primary-key",
            api_base="https://groq.example/v1",
            fallback_models=("fallback-ok",),
        )
    ).create_reply("Ping", BotInstructions(), None)

    assert response.text == "ok:primary-key"
    assert response.model == "groq/fallback-ok"
    assert calls == [
        ("groq/primary-down", "primary-key", "https://groq.example/v1"),
        ("groq/fallback-ok", "primary-key", "https://groq.example/v1"),
    ]


def test_litellm_model_gemini_detection_prefers_explicit_model_prefix() -> None:
    assert litellm_provider._model_uses_gemini_api(
        provider="litellm_gemini_stateless",
        model="gemini-3.5-flash",
    )
    assert litellm_provider._model_uses_google_gemini(
        provider="litellm_gemini_stateless",
        model="gemini-3.5-flash",
    )
    assert not litellm_provider._model_uses_gemini_api(
        provider="litellm_gemini_stateless",
        model="openai/gpt-test",
    )
    assert not litellm_provider._model_uses_google_gemini(
        provider="litellm_gemini_stateless",
        model="openai/gpt-test",
    )
    assert not litellm_provider._model_uses_gemini_api(
        provider="litellm_gemini_stateless",
        model="vertex_ai/gemini-3.5-flash",
    )
    assert litellm_provider._model_uses_google_gemini(
        provider="litellm_gemini_stateless",
        model="vertex_ai/gemini-3.5-flash",
    )


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


def test_litellm_text_client_keeps_mixed_case_explicit_model_prefixes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def completion(**kwargs):
        model = str(kwargs["model"])
        calls.append(model)
        if model == "groq/primary-down":
            raise RuntimeError("down")
        return {"choices": [{"message": {"content": f"ok:{model}"}}]}

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))

    response = LiteLLMTextClient(
        provider="groq",
        model="primary-down",
        fallback_models=("OpenAI/gpt-4.1-mini",),
    ).create_reply("Ping", BotInstructions(), None)

    assert response.model == "openai/gpt-4.1-mini"
    assert calls == ["groq/primary-down", "openai/gpt-4.1-mini"]


def test_litellm_text_client_redacts_provider_errors_from_logs_and_exception(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    def completion(**_kwargs):
        raise RuntimeError(
            "provider rejected api_key=hf-test-secret bearer sk-test-secret123456 "
            "api_key_env=GEMINI_API_KEY fallback_api_key_env=plain-secret "
            "total_tokens=4096 input_token_count=512 max_tokens=800 session_token=123456 refresh_tokens=123456"
        )

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
    assert "api_key_env=GEMINI_API_KEY" in combined
    assert "total_tokens=4096" in combined
    assert "input_token_count=512" in combined
    assert "max_tokens=800" in combined
    assert "hf-test-secret" not in combined
    assert "sk-test-secret123456" not in combined
    assert "plain-secret" not in combined
    assert "session_token=123456" not in combined
    assert "session_token=<redacted>" in combined
    assert "refresh_tokens=123456" not in combined
    assert "refresh_tokens=<redacted>" in combined
    assert "fallback_api_key_env=<redacted>" in combined
    assert "<redacted>" in combined


def test_litellm_text_client_redacts_url_credentials_in_provider_errors(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def completion(**_kwargs):
        raise RuntimeError(
            "provider rejected api_base=user:pass@example.invalid "
            "base_url=admin:s3cr3t@internal.invalid "
            "target=foo:bar@localhost "
            "https://urluser:urlpass@example.invalid/v1"
        )

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))
    client = LiteLLMTextClient(
        provider="huggingface",
        model="meta-llama/Llama-3.1-8B-Instruct",
    )

    with caplog.at_level("WARNING", logger="TeeBotus.llm.litellm_provider"):
        with pytest.raises(LLMAPIError) as error:
            client.create_reply("Ping", BotInstructions(), None)

    combined = str(error.value) + "\n" + "\n".join(record.getMessage() for record in caplog.records)

    assert "user:pass" not in combined
    assert "admin:s3cr3t" not in combined
    assert "foo:bar" not in combined
    assert "urluser:urlpass" not in combined
    assert "api_base=<redacted>@example.invalid" in combined
    assert "base_url=<redacted>@internal.invalid" in combined
    assert "target=<redacted>@localhost" in combined
    assert "https://<redacted>@example.invalid/v1" in combined


def test_litellm_text_client_safe_api_base_log_handles_invalid_port(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[dict[str, object]] = []

    def completion(**kwargs):
        calls.append(kwargs)
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))
    client = LiteLLMTextClient(
        provider="huggingface",
        model="meta-llama/Llama-3.1-8B-Instruct",
        api_base="https://user:pass@example.invalid:bad/v1",
    )

    with caplog.at_level("INFO", logger="TeeBotus.llm.litellm_provider"):
        response = client.create_reply("Ping", BotInstructions(), None)

    log_text = "\n".join(record.getMessage() for record in caplog.records)

    assert response.text == "ok"
    assert calls[0]["api_base"] == "https://user:pass@example.invalid:bad/v1"
    assert "user:pass" not in log_text
    assert "https://<redacted>@example.invalid:bad/v1" in log_text


def test_litellm_text_client_safe_api_base_log_redacts_schemeless_credentials(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[dict[str, object]] = []

    def completion(**kwargs):
        calls.append(kwargs)
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))
    client = LiteLLMTextClient(
        provider="huggingface",
        model="meta-llama/Llama-3.1-8B-Instruct",
        api_base="user:pass@example.invalid/v1",
    )

    with caplog.at_level("INFO", logger="TeeBotus.llm.litellm_provider"):
        response = client.create_reply("Ping", BotInstructions(), None)

    log_text = "\n".join(record.getMessage() for record in caplog.records)

    assert response.text == "ok"
    assert calls[0]["api_base"] == "user:pass@example.invalid/v1"
    assert "user:pass" not in log_text
    assert "<redacted>@example.invalid/v1" in log_text


def test_litellm_text_client_redacts_bare_schemeless_url_credentials_in_errors(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def completion(**_kwargs):
        raise RuntimeError("provider leaked proxy user:pass@example.invalid/v1")

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))
    client = LiteLLMTextClient(
        provider="huggingface",
        model="meta-llama/Llama-3.1-8B-Instruct",
    )

    with caplog.at_level("WARNING", logger="TeeBotus.llm.litellm_provider"):
        with pytest.raises(LLMAPIError) as error:
            client.create_reply("Ping", BotInstructions(), None)

    combined = str(error.value) + "\n" + "\n".join(record.getMessage() for record in caplog.records)

    assert "user:pass" not in combined
    assert "<redacted>@example.invalid/v1" in combined


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

    assert isinstance(client, LiteLLMGeminiStatefulClient)
    assert client.provider == "litellm_gemini_stateful"
    assert client.model == "gemini/gemini-3.5-flash"
    assert client.store is True
    assert client.service_tier == "flex"
    assert client.capabilities.previous_response_id is True


def test_build_text_llm_client_can_build_paid_gemini_stateful_client() -> None:
    client = build_text_llm_client(
        instructions=BotInstructions(llm_provider="openai", llm_model="ignored"),
        openai_client=None,
        provider="litellm-gemini-paid-statefull",
        model="gemini/gemini-3.5-flash",
        api_key="gemini-key",
        gemini_free_tier_limits=GeminiFreeTierLimits(
            enabled=True,
            requests_per_minute=0,
            input_tokens_per_minute=0,
            requests_per_day=0,
        ),
    )

    assert isinstance(client, LiteLLMGeminiStatefulClient)
    assert client.provider == "litellm_gemini_paid_stateful"
    assert client.gemini_free_tier_limits.status_summary() == "off"
    assert client.capabilities.previous_response_id is True


def test_gemini_stateful_client_uses_default_timeout_for_invalid_direct_setting() -> None:
    client = LiteLLMGeminiStatefulClient(
        LiteLLMGeminiStatefulSettings(
            model="gemini/gemini-3.5-flash",
            api_key="gemini-key",
            timeout="slow",  # type: ignore[arg-type]
            gemini_free_tier_limits=GeminiFreeTierLimits(enabled=False),
        )
    )

    assert client.timeout == 90


def test_gemini_stateful_client_normalizes_mixed_case_model_prefixes() -> None:
    mixed_gemini = LiteLLMGeminiStatefulClient(
        LiteLLMGeminiStatefulSettings(
            model="Gemini/Gemini-3.5-Flash",
            api_key="gemini-key",
            gemini_free_tier_limits=GeminiFreeTierLimits(enabled=False),
        )
    )
    mixed_models = LiteLLMGeminiStatefulClient(
        LiteLLMGeminiStatefulSettings(
            model="Models/gemini-3.5-flash",
            api_key="gemini-key",
            gemini_free_tier_limits=GeminiFreeTierLimits(enabled=False),
        )
    )

    assert mixed_gemini.model == "gemini/Gemini-3.5-Flash"
    assert mixed_models.model == "gemini/gemini-3.5-flash"


def test_gemini_stateful_client_uses_central_paid_alias_scope() -> None:
    client = LiteLLMGeminiStatefulClient(
        LiteLLMGeminiStatefulSettings(
            provider="gemini_paid_stateless_litellm",
            model="gemini/gemini-3.5-flash",
            api_key="gemini-key",
            gemini_free_tier_limits=GeminiFreeTierLimits(
                enabled=True,
                requests_per_minute=0,
                input_tokens_per_minute=0,
                requests_per_day=0,
            ),
        )
    )

    assert client.provider == "litellm_gemini_paid_stateful"
    assert client.gemini_free_tier_limits.status_summary() == "off"
    assert client.capabilities.previous_response_id is True


def test_gemini_interactions_client_sends_stateful_request(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []
    keys: list[str] = []

    class Interaction:
        output_text = "  Hallo Gemini  "
        id = "interaction-1"
        usage = {"input_tokens": 3, "output_tokens": 2}
        _hidden_params = {"response_cost": 0.0009}

    def create_interaction(**kwargs):
        keys.append(kwargs.get("api_key"))
        calls.append(kwargs)
        return Interaction()

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(create_interaction=create_interaction))
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
    assert response.provider == "litellm_gemini_stateful"
    assert response.model == "gemini/gemini-3.5-flash"
    assert response.service_tier == "flex"
    assert response.usage == {"input_tokens": 3, "output_tokens": 2, "response_cost": 0.0009}
    assert keys == ["gemini-key"]
    assert calls == [
        {
            "input": "Ping",
            "model": "gemini/gemini-3.5-flash",
            "store": True,
            "system_instruction": "System.",
            "generation_config": {"max_output_tokens": 77},
            "api_key": "gemini-key",
            "timeout": 90,
            "previous_interaction_id": "prev-1",
            "service_tier": "flex",
        }
    ]


def test_gemini_interactions_client_uses_google_api_key_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    keys: list[str] = []

    class Interaction:
        output_text = "ok"
        id = "interaction-google-key"
        usage = {"input_tokens": 3, "output_tokens": 2}

    def create_interaction(**kwargs):
        keys.append(str(kwargs.get("api_key") or ""))
        return Interaction()

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(create_interaction=create_interaction))
    monkeypatch.setenv("GOOGLE_API_KEY", "google-env-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client = GeminiInteractionsClient(
        GeminiInteractionsSettings(
            model="gemini/gemini-3.5-flash",
            gemini_free_tier_limits=GeminiFreeTierLimits(enabled=False),
        )
    )

    response = client.create_reply("Ping", BotInstructions(openai_system_prompt="System."), None)

    assert response.text == "ok"
    assert keys == ["google-env-key"]


def test_gemini_interactions_client_ignores_invalid_generation_config_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    class Interaction:
        output_text = "ok"
        id = "interaction-config"
        usage = {"input_tokens": 3, "output_tokens": 2}

    def create_interaction(**kwargs):
        calls.append(kwargs)
        return Interaction()

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(create_interaction=create_interaction))
    client = GeminiInteractionsClient(
        GeminiInteractionsSettings(
            model="gemini/gemini-3.5-flash",
            api_key="gemini-key",
            temperature="inf",  # type: ignore[arg-type]
            max_tokens=-1,  # type: ignore[arg-type]
            gemini_free_tier_limits=GeminiFreeTierLimits(enabled=False),
        )
    )

    response = client.create_reply(
        "Ping",
        BotInstructions(
            openai_system_prompt="System.",
            llm_temperature=0.3,
            llm_max_output_tokens=44,
            openai_max_output_tokens=77,
        ),
        None,
    )

    assert response.text == "ok"
    assert calls[0]["generation_config"] == {"temperature": 0.3, "max_output_tokens": 44}


def test_gemini_interactions_client_ignores_broken_optional_interaction_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    class Usage:
        input_tokens = 5
        input_token_count = 5
        input_tokens_by_modality = [{"modality": "TEXT", "token_count": 5}]
        output_token_count = 3
        output_tokens_by_modality = [{"modality": "TEXT", "token_count": 3}]
        total_token_count = 8
        total_tokens = 8
        cached_tokens = 2
        total_cached_tokens = 2
        cached_tokens_by_modality = [{"modality": "TEXT", "token_count": 2}]
        cache_read_input_tokens = 1
        cache_creation_input_tokens = 1
        reasoning_tokens = 1
        total_reasoning_tokens = 1
        total_tool_use_tokens = 2
        tool_use_tokens_by_modality = [{"modality": "TEXT", "token_count": 2}]
        prompt_tokens_details = {"cached_tokens": 2}
        completion_tokens_details = {"reasoning_tokens": 1}

        @property
        def model_dump(self) -> object:
            raise RuntimeError("model_dump property unavailable")

        @property
        def output_tokens(self) -> object:
            raise RuntimeError("output_tokens property unavailable")

    class Interaction:
        id = "interaction-safe"
        outputs = [types.SimpleNamespace(text="  Fallback-Output  ")]
        usage = Usage()

        @property
        def output_text(self) -> object:
            raise RuntimeError("output_text property unavailable")

        def __getitem__(self, _key: str) -> object:
            raise IndexError("SDK object has no mapping item")

    def create_interaction(**_kwargs):
        return Interaction()

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(create_interaction=create_interaction))
    client = GeminiInteractionsClient(
        GeminiInteractionsSettings(
            model="gemini/gemini-3.5-flash",
            api_key="gemini-key",
            gemini_free_tier_limits=GeminiFreeTierLimits(enabled=False),
        )
    )

    response = client.create_reply("Ping", BotInstructions(openai_system_prompt="System."), None)

    assert response.text == "Fallback-Output"
    assert response.response_id == "interaction-safe"
    assert response.usage == {
        "input_tokens": 5,
        "input_token_count": 5,
        "input_tokens_by_modality": [{"modality": "TEXT", "token_count": 5}],
        "output_token_count": 3,
        "output_tokens_by_modality": [{"modality": "TEXT", "token_count": 3}],
        "total_token_count": 8,
        "total_tokens": 8,
        "cached_tokens": 2,
        "total_cached_tokens": 2,
        "cached_tokens_by_modality": [{"modality": "TEXT", "token_count": 2}],
        "cache_read_input_tokens": 1,
        "cache_creation_input_tokens": 1,
        "reasoning_tokens": 1,
        "total_reasoning_tokens": 1,
        "total_tool_use_tokens": 2,
        "tool_use_tokens_by_modality": [{"modality": "TEXT", "token_count": 2}],
        "prompt_tokens_details": {"cached_tokens": 2},
        "completion_tokens_details": {"reasoning_tokens": 1},
    }


def test_gemini_interactions_client_falls_back_to_usage_attrs_after_empty_model_dump(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Usage:
        input_tokens = 6
        total_tokens = 9

        def model_dump(self) -> dict[str, object]:
            return {}

    class Interaction:
        output_text = "ok"
        usage = Usage()

    def create_interaction(**_kwargs):
        return Interaction()

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(create_interaction=create_interaction))
    client = GeminiInteractionsClient(
        GeminiInteractionsSettings(
            model="gemini/gemini-3.5-flash",
            api_key="gemini-key",
            gemini_free_tier_limits=GeminiFreeTierLimits(enabled=False),
        )
    )

    response = client.create_reply("Ping", BotInstructions(openai_system_prompt="System."), None)

    assert response.text == "ok"
    assert response.usage == {"input_tokens": 6, "total_tokens": 9}


def test_gemini_interactions_client_falls_back_to_usage_attrs_after_null_model_dump(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Usage:
        input_tokens = 6
        total_tokens = 9

        def model_dump(self) -> dict[str, object]:
            return {"input_tokens": None, "total_tokens": None}

    class Interaction:
        output_text = "ok"
        usage = Usage()

    def create_interaction(**_kwargs):
        return Interaction()

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(create_interaction=create_interaction))
    client = GeminiInteractionsClient(
        GeminiInteractionsSettings(
            model="gemini/gemini-3.5-flash",
            api_key="gemini-key",
            gemini_free_tier_limits=GeminiFreeTierLimits(enabled=False),
        )
    )

    response = client.create_reply("Ping", BotInstructions(openai_system_prompt="System."), None)

    assert response.text == "ok"
    assert response.usage == {"input_tokens": 6, "total_tokens": 9}


def test_gemini_interactions_client_merges_usage_attrs_after_partial_model_dump(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Usage:
        input_tokens = 6
        output_tokens = 3
        total_tokens = 9

        def model_dump(self) -> dict[str, object]:
            return {"input_tokens": None, "total_tokens": 9}

    class Interaction:
        output_text = "ok"
        usage = Usage()

    def create_interaction(**_kwargs):
        return Interaction()

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(create_interaction=create_interaction))
    client = GeminiInteractionsClient(
        GeminiInteractionsSettings(
            model="gemini/gemini-3.5-flash",
            api_key="gemini-key",
            gemini_free_tier_limits=GeminiFreeTierLimits(enabled=False),
        )
    )

    response = client.create_reply("Ping", BotInstructions(openai_system_prompt="System."), None)

    assert response.text == "ok"
    assert response.usage == {"total_tokens": 9, "input_tokens": 6, "output_tokens": 3}


def test_gemini_interactions_client_extracts_choice_content_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    class Interaction:
        id = "interaction-parts"
        choices = [
            {
                "message": {
                    "content": [
                        {"type": "Text", "text": "  Hallo  "},
                        {"type": "image_url", "image_url": {"url": "https://example.invalid/bild.png"}},
                        {"type": "output_text", "text": {"value": "Gemini"}},
                        {"type": "text", "content": {"text": "Stateful"}},
                    ]
                }
            }
        ]
        usage = {"input_tokens": 5, "output_tokens": 4}

    def create_interaction(**_kwargs):
        return Interaction()

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(create_interaction=create_interaction))
    client = GeminiInteractionsClient(
        GeminiInteractionsSettings(
            model="gemini/gemini-3.5-flash",
            api_key="gemini-key",
            gemini_free_tier_limits=GeminiFreeTierLimits(enabled=False),
        )
    )

    response = client.create_reply("Ping", BotInstructions(openai_system_prompt="System."), None)

    assert response.text == "Hallo\nGemini\nStateful"
    assert response.response_id == "interaction-parts"
    assert response.usage == {"input_tokens": 5, "output_tokens": 4}


def test_gemini_interactions_client_extracts_output_text_content_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    class Interaction:
        id = "interaction-output-text-parts"
        output_text = [
            {"type": "text", "text": "  Top  "},
            {"type": "image_url", "image_url": {"url": "https://example.invalid/bild.png"}},
            {"type": "output_text", "content": {"text": "Level"}},
        ]
        usage = {"input_tokens": 5, "output_tokens": 4}

    def create_interaction(**_kwargs):
        return Interaction()

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(create_interaction=create_interaction))
    client = GeminiInteractionsClient(
        GeminiInteractionsSettings(
            model="gemini/gemini-3.5-flash",
            api_key="gemini-key",
            gemini_free_tier_limits=GeminiFreeTierLimits(enabled=False),
        )
    )

    response = client.create_reply("Ping", BotInstructions(openai_system_prompt="System."), None)

    assert response.text == "Top\nLevel"
    assert response.response_id == "interaction-output-text-parts"
    assert response.usage == {"input_tokens": 5, "output_tokens": 4}


def test_gemini_interactions_client_extracts_output_content_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    class Interaction:
        id = "interaction-output-parts"
        outputs = [{"text": {"value": "  Output-Teil  "}}]
        usage = {"input_tokens": 5, "output_tokens": 4}

    def create_interaction(**_kwargs):
        return Interaction()

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(create_interaction=create_interaction))
    client = GeminiInteractionsClient(
        GeminiInteractionsSettings(
            model="gemini/gemini-3.5-flash",
            api_key="gemini-key",
            gemini_free_tier_limits=GeminiFreeTierLimits(enabled=False),
        )
    )

    response = client.create_reply("Ping", BotInstructions(openai_system_prompt="System."), None)

    assert response.text == "Output-Teil"
    assert response.response_id == "interaction-output-parts"
    assert response.usage == {"input_tokens": 5, "output_tokens": 4}


def test_gemini_interactions_client_extracts_root_model_outputs(monkeypatch: pytest.MonkeyPatch) -> None:
    class Interaction:
        id = "interaction-root-output"
        outputs = [
            types.SimpleNamespace(root=types.SimpleNamespace(type="text", text="  Root-Text  ")),
            types.SimpleNamespace(root={"type": "image", "uri": "https://example.invalid/bild.png"}),
            types.SimpleNamespace(root={"type": "output_text", "text": {"value": "Output"}}),
        ]
        usage = {"input_tokens": 5, "output_tokens": 4}

    def create_interaction(**_kwargs):
        return Interaction()

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(create_interaction=create_interaction))
    client = GeminiInteractionsClient(
        GeminiInteractionsSettings(
            model="gemini/gemini-3.5-flash",
            api_key="gemini-key",
            gemini_free_tier_limits=GeminiFreeTierLimits(enabled=False),
        )
    )

    response = client.create_reply("Ping", BotInstructions(openai_system_prompt="System."), None)

    assert response.text == "Root-Text\nOutput"
    assert response.response_id == "interaction-root-output"
    assert response.usage == {"input_tokens": 5, "output_tokens": 4}


def test_gemini_interactions_client_extracts_step_content_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    class Interaction:
        id = "interaction-step-parts"
        steps = [
            types.SimpleNamespace(root=types.SimpleNamespace(type="text", text="Root-Step-Top")),
            {
                "content": [
                    {"type": "text", "text": "Step"},
                    {"type": "image_url", "image_url": {"url": "https://example.invalid/bild.png"}},
                ],
                "output": [
                    {"text": {"content": {"text": "verschachtelt"}}},
                    types.SimpleNamespace(root={"type": "text", "text": "Root-Step"}),
                ],
            }
        ]
        usage = {"input_tokens": 5, "output_tokens": 4}

    def create_interaction(**_kwargs):
        return Interaction()

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(create_interaction=create_interaction))
    client = GeminiInteractionsClient(
        GeminiInteractionsSettings(
            model="gemini/gemini-3.5-flash",
            api_key="gemini-key",
            gemini_free_tier_limits=GeminiFreeTierLimits(enabled=False),
        )
    )

    response = client.create_reply("Ping", BotInstructions(openai_system_prompt="System."), None)

    assert response.text == "Root-Step-Top\nStep\nverschachtelt\nRoot-Step"
    assert response.response_id == "interaction-step-parts"
    assert response.usage == {"input_tokens": 5, "output_tokens": 4}


def test_gemini_interactions_client_drops_previous_interaction_on_key_failover(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []
    keys: list[str] = []

    class Interaction:
        output_text = "  Hallo vom zweiten Key  "
        id = "interaction-2"
        usage = {"input_tokens": 4, "output_tokens": 3}

    def create_interaction(**kwargs):
        api_key = str(kwargs.get("api_key") or "")
        keys.append(api_key)
        calls.append(kwargs)
        if api_key == "gemini-a":
            raise RuntimeError("quota exceeded")
        return Interaction()

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(create_interaction=create_interaction))
    reset_gemini_free_tier_budget_state()
    client = GeminiInteractionsClient(
        GeminiInteractionsSettings(
            model="gemini/gemini-3.5-flash",
            api_key_ring=("gemini-a", "gemini-b"),
            gemini_free_tier_limits=GeminiFreeTierLimits(enabled=False),
        )
    )

    response = client.create_reply("Ping", BotInstructions(openai_system_prompt="System."), "prev-from-gemini-a")

    assert response.text == "Hallo vom zweiten Key"
    assert response.response_id == "interaction-2"
    assert keys == ["gemini-a", "gemini-b"]
    assert calls[0]["previous_interaction_id"] == "prev-from-gemini-a"
    assert "previous_interaction_id" not in calls[1]


def test_gemini_interactions_client_adjusts_free_tier_from_modality_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_gemini_free_tier_budget_state()
    calls: list[str] = []
    instructions = BotInstructions(openai_system_prompt="System.")
    user_text = "Ping " * 24
    estimated = estimate_litellm_input_tokens(
        (
            {"role": "system", "content": instructions.openai_instructions_text()},
            {"role": "user", "content": user_text},
        )
    )

    class Interaction:
        output_text = "ok"
        usage = {"input_tokens_by_modality": [{"modality": "TEXT", "tokens": 1}]}

    def create_interaction(**kwargs):
        calls.append(str(kwargs.get("api_key") or ""))
        return Interaction()

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(create_interaction=create_interaction))
    client = GeminiInteractionsClient(
        GeminiInteractionsSettings(
            model="gemini/gemini-3.5-flash",
            api_key="gemini-budget-one",
            gemini_free_tier_limits=GeminiFreeTierLimits(
                requests_per_minute=10,
                input_tokens_per_minute=estimated + 5,
                requests_per_day=10,
                reserve_input_tokens=0,
            ),
        )
    )

    first = client.create_reply(user_text, instructions, None)
    second = client.create_reply(user_text, instructions, None)

    assert first.text == "ok"
    assert second.text == "ok"
    assert calls == ["gemini-budget-one", "gemini-budget-one"]


def test_gemini_interactions_client_ignores_nonfinite_input_usage_for_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_gemini_free_tier_budget_state()
    calls: list[str] = []
    instructions = BotInstructions(openai_system_prompt="System.")
    user_text = "Ping " * 24
    estimated = estimate_litellm_input_tokens(
        (
            {"role": "system", "content": instructions.openai_instructions_text()},
            {"role": "user", "content": user_text},
        )
    )

    class Interaction:
        output_text = "ok"
        usage = {"input_tokens": float("inf"), "input_tokens_by_modality": [{"modality": "TEXT", "tokens": 1}]}

    def create_interaction(**kwargs):
        calls.append(str(kwargs.get("api_key") or ""))
        return Interaction()

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(create_interaction=create_interaction))
    client = GeminiInteractionsClient(
        GeminiInteractionsSettings(
            model="gemini/gemini-3.5-flash",
            api_key="gemini-budget-one",
            gemini_free_tier_limits=GeminiFreeTierLimits(
                requests_per_minute=10,
                input_tokens_per_minute=estimated + 5,
                requests_per_day=10,
                reserve_input_tokens=0,
            ),
        )
    )

    first = client.create_reply(user_text, instructions, None)
    second = client.create_reply(user_text, instructions, None)

    assert first.text == "ok"
    assert second.text == "ok"
    assert calls == ["gemini-budget-one", "gemini-budget-one"]


def test_gemini_interactions_client_ignores_bool_input_usage_for_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_gemini_free_tier_budget_state()
    calls: list[str] = []
    instructions = BotInstructions(openai_system_prompt="System.")
    user_text = "Ping " * 24
    estimated = estimate_litellm_input_tokens(
        (
            {"role": "system", "content": instructions.openai_instructions_text()},
            {"role": "user", "content": user_text},
        )
    )

    class Interaction:
        output_text = "ok"
        usage = {"input_tokens": True, "input_tokens_by_modality": [{"modality": "TEXT", "tokens": 20}]}

    def create_interaction(**kwargs):
        calls.append(str(kwargs.get("api_key") or ""))
        return Interaction()

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(create_interaction=create_interaction))
    client = GeminiInteractionsClient(
        GeminiInteractionsSettings(
            model="gemini/gemini-3.5-flash",
            api_key="gemini-budget-one",
            gemini_free_tier_limits=GeminiFreeTierLimits(
                requests_per_minute=10,
                input_tokens_per_minute=estimated + 10,
                requests_per_day=10,
                reserve_input_tokens=0,
            ),
        )
    )

    first = client.create_reply(user_text, instructions, None)
    with pytest.raises(LLMAPIError, match="TPM free-tier budget would be exceeded"):
        client.create_reply(user_text, instructions, None)

    assert first.text == "ok"
    assert calls == ["gemini-budget-one"]


def test_gemini_interactions_client_ignores_fractional_input_usage_for_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_gemini_free_tier_budget_state()
    calls: list[str] = []
    instructions = BotInstructions(openai_system_prompt="System.")
    user_text = "Ping " * 24
    estimated = estimate_litellm_input_tokens(
        (
            {"role": "system", "content": instructions.openai_instructions_text()},
            {"role": "user", "content": user_text},
        )
    )

    class Interaction:
        output_text = "ok"
        usage = {"input_tokens": 1.7, "input_tokens_by_modality": [{"modality": "TEXT", "tokens": 20}]}

    def create_interaction(**kwargs):
        calls.append(str(kwargs.get("api_key") or ""))
        return Interaction()

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(create_interaction=create_interaction))
    client = GeminiInteractionsClient(
        GeminiInteractionsSettings(
            model="gemini/gemini-3.5-flash",
            api_key="gemini-budget-one",
            gemini_free_tier_limits=GeminiFreeTierLimits(
                requests_per_minute=10,
                input_tokens_per_minute=estimated + 10,
                requests_per_day=10,
                reserve_input_tokens=0,
            ),
        )
    )

    first = client.create_reply(user_text, instructions, None)
    with pytest.raises(LLMAPIError, match="TPM free-tier budget would be exceeded"):
        client.create_reply(user_text, instructions, None)

    assert first.text == "ok"
    assert calls == ["gemini-budget-one"]


def test_gemini_interactions_client_ignores_decimal_fractional_input_usage_for_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_gemini_free_tier_budget_state()
    calls: list[str] = []
    instructions = BotInstructions(openai_system_prompt="System.")
    user_text = "Ping " * 24
    estimated = estimate_litellm_input_tokens(
        (
            {"role": "system", "content": instructions.openai_instructions_text()},
            {"role": "user", "content": user_text},
        )
    )

    class Interaction:
        output_text = "ok"
        usage = {"input_tokens": Decimal("1.7"), "input_tokens_by_modality": [{"modality": "TEXT", "tokens": 20}]}

    def create_interaction(**kwargs):
        calls.append(str(kwargs.get("api_key") or ""))
        return Interaction()

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(create_interaction=create_interaction))
    client = GeminiInteractionsClient(
        GeminiInteractionsSettings(
            model="gemini/gemini-3.5-flash",
            api_key="gemini-budget-one",
            gemini_free_tier_limits=GeminiFreeTierLimits(
                requests_per_minute=10,
                input_tokens_per_minute=estimated + 10,
                requests_per_day=10,
                reserve_input_tokens=0,
            ),
        )
    )

    first = client.create_reply(user_text, instructions, None)
    with pytest.raises(LLMAPIError, match="TPM free-tier budget would be exceeded"):
        client.create_reply(user_text, instructions, None)

    assert first.text == "ok"
    assert calls == ["gemini-budget-one"]


def test_gemini_interactions_client_ignores_fraction_input_usage_for_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_gemini_free_tier_budget_state()
    calls: list[str] = []
    instructions = BotInstructions(openai_system_prompt="System.")
    user_text = "Ping " * 24
    estimated = estimate_litellm_input_tokens(
        (
            {"role": "system", "content": instructions.openai_instructions_text()},
            {"role": "user", "content": user_text},
        )
    )

    class Interaction:
        output_text = "ok"
        usage = {"input_tokens": Fraction(3, 2), "input_tokens_by_modality": [{"modality": "TEXT", "tokens": 20}]}

    def create_interaction(**kwargs):
        calls.append(str(kwargs.get("api_key") or ""))
        return Interaction()

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(create_interaction=create_interaction))
    client = GeminiInteractionsClient(
        GeminiInteractionsSettings(
            model="gemini/gemini-3.5-flash",
            api_key="gemini-budget-one",
            gemini_free_tier_limits=GeminiFreeTierLimits(
                requests_per_minute=10,
                input_tokens_per_minute=estimated + 10,
                requests_per_day=10,
                reserve_input_tokens=0,
            ),
        )
    )

    first = client.create_reply(user_text, instructions, None)
    with pytest.raises(LLMAPIError, match="TPM free-tier budget would be exceeded"):
        client.create_reply(user_text, instructions, None)

    assert first.text == "ok"
    assert calls == ["gemini-budget-one"]


def test_gemini_interactions_client_ignores_bytes_input_usage_for_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_gemini_free_tier_budget_state()
    calls: list[str] = []
    instructions = BotInstructions(openai_system_prompt="System.")
    user_text = "Ping " * 24
    estimated = estimate_litellm_input_tokens(
        (
            {"role": "system", "content": instructions.openai_instructions_text()},
            {"role": "user", "content": user_text},
        )
    )

    class Interaction:
        output_text = "ok"
        usage = {"input_tokens": b"1", "input_tokens_by_modality": [{"modality": "TEXT", "tokens": 20}]}

    def create_interaction(**kwargs):
        calls.append(str(kwargs.get("api_key") or ""))
        return Interaction()

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(create_interaction=create_interaction))
    client = GeminiInteractionsClient(
        GeminiInteractionsSettings(
            model="gemini/gemini-3.5-flash",
            api_key="gemini-budget-one",
            gemini_free_tier_limits=GeminiFreeTierLimits(
                requests_per_minute=10,
                input_tokens_per_minute=estimated + 10,
                requests_per_day=10,
                reserve_input_tokens=0,
            ),
        )
    )

    first = client.create_reply(user_text, instructions, None)
    with pytest.raises(LLMAPIError, match="TPM free-tier budget would be exceeded"):
        client.create_reply(user_text, instructions, None)

    assert first.text == "ok"
    assert calls == ["gemini-budget-one"]


def test_gemini_interactions_client_sums_modality_mapping_usage_for_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_gemini_free_tier_budget_state()
    calls: list[str] = []
    instructions = BotInstructions(openai_system_prompt="System.")
    user_text = "Ping " * 24
    estimated = estimate_litellm_input_tokens(
        (
            {"role": "system", "content": instructions.openai_instructions_text()},
            {"role": "user", "content": user_text},
        )
    )

    class Interaction:
        output_text = "ok"
        usage = {"input_tokens_by_modality": {"TEXT": 20, "IMAGE": 5}}

    def create_interaction(**kwargs):
        calls.append(str(kwargs.get("api_key") or ""))
        return Interaction()

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(create_interaction=create_interaction))
    client = GeminiInteractionsClient(
        GeminiInteractionsSettings(
            model="gemini/gemini-3.5-flash",
            api_key="gemini-budget-one",
            gemini_free_tier_limits=GeminiFreeTierLimits(
                requests_per_minute=10,
                input_tokens_per_minute=estimated + 15,
                requests_per_day=10,
                reserve_input_tokens=0,
            ),
        )
    )

    first = client.create_reply(user_text, instructions, None)
    with pytest.raises(LLMAPIError, match="TPM free-tier budget would be exceeded"):
        client.create_reply(user_text, instructions, None)

    assert first.text == "ok"
    assert calls == ["gemini-budget-one"]


def test_gemini_interactions_client_does_not_try_next_key_on_non_limit_error(monkeypatch: pytest.MonkeyPatch) -> None:
    keys: list[str] = []

    def create_interaction(**kwargs):
        api_key = str(kwargs.get("api_key") or "")
        keys.append(api_key)
        raise RuntimeError("provider rejected request body")

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(create_interaction=create_interaction))
    client = GeminiInteractionsClient(
        GeminiInteractionsSettings(
            model="gemini/gemini-3.5-flash",
            api_key_ring=("gemini-nonlimit-a", "gemini-nonlimit-b"),
            gemini_free_tier_limits=GeminiFreeTierLimits(enabled=False),
        )
    )

    with pytest.raises(LLMAPIError, match="provider rejected request body"):
        client.create_reply("Ping", BotInstructions(openai_system_prompt="System."), None)

    assert keys == ["gemini-nonlimit-a"]


def test_gemini_interactions_client_does_not_try_next_key_on_empty_text(monkeypatch: pytest.MonkeyPatch) -> None:
    keys: list[str] = []

    class Interaction:
        output_text = "   "

    def create_interaction(**kwargs):
        keys.append(str(kwargs.get("api_key") or ""))
        return Interaction()

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(create_interaction=create_interaction))
    client = GeminiInteractionsClient(
        GeminiInteractionsSettings(
            model="gemini/gemini-3.5-flash",
            api_key_ring=("gemini-empty-a", "gemini-empty-b"),
            gemini_free_tier_limits=GeminiFreeTierLimits(enabled=False),
        )
    )

    with pytest.raises(LLMAPIError, match="empty text"):
        client.create_reply("Ping", BotInstructions(openai_system_prompt="System."), None)

    assert keys == ["gemini-empty-a"]


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
