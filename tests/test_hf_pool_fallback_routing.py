from __future__ import annotations

import sys
import types

from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.hf_pool.provider import HFPoolProvider
from TeeBotus.llm.litellm_provider import LiteLLMTextClient
from TeeBotus.llm.profiles import LLMRoute
from TeeBotus.runtime.llm_factory import build_runtime_text_llm_client


def test_hf_pool_route_uses_remote_fallback_only_when_explicitly_allowed(monkeypatch):
    def route(*_args, **_kwargs):
        return LLMRoute(
            purpose="structured_decision",
            profile_name="hf_pool_structured",
            provider="hf_pool",
            model="pool:default",
            fallback_profile_name="groq_fast",
            fallback_model="groq/llama-3.1-8b-instant",
            fallback_api_key_env="GROQ_API_KEY",
        )

    monkeypatch.setattr("TeeBotus.runtime.llm_factory.select_llm_route", route)

    blocked = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        purpose="structured_decision",
        env={"GROQ_API_KEY": "groq-secret"},
    )
    allowed = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        purpose="structured_decision",
        allow_remote_fallback=True,
        env={"GROQ_API_KEY": "groq-secret"},
    )

    assert isinstance(blocked, HFPoolProvider)
    assert blocked.fallback_client is None
    assert isinstance(allowed, HFPoolProvider)
    assert isinstance(allowed.fallback_client, LiteLLMTextClient)
    assert allowed.fallback_client.api_key == "groq-secret"
    assert allowed.fallback_client.fallback_api_keys == {}


def test_hf_pool_route_uses_instance_scoped_key_for_openai_fallback(monkeypatch):
    def route(*_args, **_kwargs):
        return LLMRoute(
            purpose="structured_decision",
            profile_name="hf_pool_structured",
            provider="hf_pool",
            model="pool:default",
            fallback_profile_name="openai_premium",
            fallback_model="gpt-4.1-mini",
            fallback_api_key_env="OPENAI_API_KEY",
        )

    monkeypatch.setattr("TeeBotus.runtime.llm_factory.select_llm_route", route)
    client = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        purpose="structured_decision",
        allow_remote_fallback=True,
        instance_name="Demo",
        env={"OPENAI_API_KEY_DEMO": "instance-key"},
    )

    assert isinstance(client, HFPoolProvider)
    assert isinstance(client.fallback_client, LiteLLMTextClient)
    assert client.fallback_client.api_key == "instance-key"


def test_hf_pool_unavailable_uses_configured_fallback_client(monkeypatch):
    calls: list[dict[str, object]] = []

    def completion(**kwargs):
        calls.append(kwargs)
        return {"id": "fallback-ok", "choices": [{"message": {"content": "Fallback Antwort"}}]}

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))
    monkeypatch.setattr(
        "TeeBotus.runtime.llm_factory.select_llm_route",
        lambda *_args, **_kwargs: LLMRoute(
            purpose="structured_decision",
            profile_name="hf_pool_structured",
            provider="hf_pool",
            model="pool:default",
            fallback_profile_name="groq_fast",
            fallback_model="groq/llama-3.1-8b-instant",
            fallback_api_key_env="GROQ_API_KEY",
        ),
    )
    client = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        purpose="structured_decision",
        allow_remote_fallback=True,
        env={"GROQ_API_KEY": "groq-secret"},
    )

    assert isinstance(client, HFPoolProvider)
    response = client.create_reply("Ping", BotInstructions(), None)

    assert response.text == "Fallback Antwort"
    assert response.provider == "litellm"
    assert response.model == "groq/llama-3.1-8b-instant"
    assert calls[0]["model"] == "groq/llama-3.1-8b-instant"
    assert calls[0]["api_key"] == "groq-secret"
