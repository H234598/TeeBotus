from __future__ import annotations

import sys
import types

import pytest

from TeeBotus.instructions import BotInstructions
from TeeBotus.llm_client import LLMAPIError, LiteLLMTextClient


def test_plan2_litellm_provider_acceptance_uses_fake_completion_without_network(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def completion(**kwargs):
        calls.append(kwargs)
        return {"id": "fake-litellm-id", "choices": [{"message": {"content": "Fake LiteLLM Antwort"}}]}

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))
    instructions = BotInstructions(
        llm_provider="litellm",
        llm_model="ollama_chat/llama3.1:8b",
        llm_base_url="http://127.0.0.1:11434",
        llm_timeout_seconds=120,
        llm_max_output_tokens=300,
        llm_temperature=0.2,
    )

    response = LiteLLMTextClient(api_key="runtime-key").create_reply("Ping", instructions, "resp-old")

    assert response.text == "Fake LiteLLM Antwort"
    assert response.response_id == "fake-litellm-id"
    assert response.provider == "litellm"
    assert response.model == "ollama_chat/llama3.1:8b"
    assert calls == [
        {
            "model": "ollama_chat/llama3.1:8b",
            "messages": [
                {"role": "system", "content": instructions.openai_instructions_text()},
                {"role": "user", "content": "Ping"},
            ],
            "timeout": 120,
            "max_tokens": 300,
            "temperature": 0.2,
            "api_base": "http://127.0.0.1:11434",
            "api_key": "runtime-key",
        }
    ]


def test_litellm_provider_requires_explicit_model_instead_of_openai_legacy_fallback(monkeypatch) -> None:
    def completion(**_kwargs):
        raise AssertionError("LiteLLM must not be called without an explicit llm_model")

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))
    client = LiteLLMTextClient(provider="litellm", model="")

    with pytest.raises(LLMAPIError, match="requires llm_model"):
        client.create_reply("Ping", BotInstructions(openai_model="gpt-legacy"), None)


def test_litellm_provider_redacts_url_credentials_and_secret_assignments(monkeypatch) -> None:
    runtime_key = "runtime-secret-key"

    def completion(**_kwargs):
        raise RuntimeError(
            "failed api_key=plain-secret password=hunter2 "
            "base_url=http://user:plain-password@127.0.0.1:11434/api "
            f"provider key {runtime_key}"
        )

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))
    client = LiteLLMTextClient(provider="litellm", model="ollama_chat/llama3.1:8b", api_key=runtime_key)

    with pytest.raises(LLMAPIError) as exc_info:
        client.create_reply("Ping", BotInstructions(), None)

    message = str(exc_info.value)
    assert "plain-secret" not in message
    assert "hunter2" not in message
    assert "plain-password" not in message
    assert runtime_key not in message
    assert "api_key=<redacted>" in message
    assert "password=<redacted>" in message
    assert "http://<redacted>@127.0.0.1:11434/api" in message
