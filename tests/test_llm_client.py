from __future__ import annotations

import sys
import types
import builtins

import pytest

from TeeBotus.instructions import BotInstructions
from TeeBotus.llm_client import LLMAPIError, LLMImage, LLMVoice, LiteLLMTextClient, build_text_llm_client, normalize_llm_provider


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
    ],
)
def test_normalize_llm_provider(value: str, expected: str) -> None:
    assert normalize_llm_provider(value) == expected


def test_litellm_text_client_calls_completion_with_instruction_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def completion(**kwargs):
        calls.append(kwargs)
        return {"id": "litellm-response", "choices": [{"message": {"content": "  Hallo  "}}]}

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
    assert response.response_id == "litellm-response"
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


def test_litellm_provider_alias_requires_explicit_model() -> None:
    with pytest.raises(LLMAPIError, match="requires llm_model"):
        LiteLLMTextClient(provider="ollama").create_reply("Ping", BotInstructions(openai_model="gpt-would-be-wrong"), None)


def test_build_text_llm_client_uses_runtime_provider_override() -> None:
    client = build_text_llm_client(
        instructions=BotInstructions(llm_provider="openai", llm_model="ignored"),
        openai_client=None,
        provider="huggingface",
        model="meta-llama/Llama-3.1-8B-Instruct",
        api_key="hf-key",
    )

    assert isinstance(client, LiteLLMTextClient)
    assert client.provider == "huggingface"
    assert client.model == "meta-llama/Llama-3.1-8B-Instruct"
    assert client.api_key == "hf-key"


def test_litellm_text_client_requires_installed_litellm(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "litellm":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(LLMAPIError, match="LiteLLM is not installed"):
        LiteLLMTextClient().create_reply("Ping", BotInstructions(llm_model="ollama/llama3"), None)
