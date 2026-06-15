from __future__ import annotations

import sys
import types

from TeeBotus.instructions import BotInstructions
from TeeBotus.llm_client import LiteLLMTextClient


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
