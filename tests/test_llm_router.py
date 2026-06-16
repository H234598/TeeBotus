from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.profiles import (
    LLMProfile,
    LLMRoutingRule,
    build_profiled_text_llm_client,
    load_llm_profiles,
    load_llm_routing,
    select_llm_route,
)
from TeeBotus.llm_client import LLMAPIError, LiteLLMTextClient
from TeeBotus.runtime.llm_factory import build_runtime_text_llm_client


def test_default_profile_files_define_plan2_provider_profiles() -> None:
    profiles = load_llm_profiles()
    default_profile, routing = load_llm_routing()

    assert default_profile == "local_ollama"
    assert profiles["local_ollama"] == LLMProfile(
        name="local_ollama",
        provider="litellm",
        model="ollama_chat/llama3.1:8b",
        base_url="http://127.0.0.1:11434",
        api_key_env="",
    )
    assert profiles["hf_mistral"] == LLMProfile(
        name="hf_mistral",
        provider="litellm",
        model="huggingface/mistralai/Mistral-7B-Instruct-v0.3",
        api_key_env="HUGGINGFACE_API_KEY",
    )
    assert profiles["groq_fast"].api_key_env == "GROQ_API_KEY"
    assert profiles["groq_fast"].provider == "litellm"
    assert profiles["groq_fast"].model.startswith("groq/")
    assert profiles["gemini_flash"] == LLMProfile(
        name="gemini_flash",
        provider="litellm",
        model="gemini/gemini-2.5-flash",
        api_key_env="GEMINI_API_KEY",
    )
    assert profiles["openai_premium"].provider == "openai"
    assert profiles["openai_premium"].api_key_env == "OPENAI_API_KEY"
    assert routing["structured_decision"].profile == "local_ollama"
    assert routing["structured_decision"].fallback == "groq_fast"
    assert routing["hard_reasoning"].profile == "openai_premium"
    assert routing["hard_reasoning"].fallback == "gemini_flash"


def test_route_selection_blocks_remote_fallback_by_default() -> None:
    profiles = {
        "local_ollama": LLMProfile("local_ollama", "litellm", "ollama_chat/llama3.1:8b", "http://127.0.0.1:11434"),
        "groq_fast": LLMProfile("groq_fast", "litellm", "groq/llama-3.1-8b-instant", api_key_env="GROQ_API_KEY"),
    }
    routing = {
        "structured_decision": LLMRoutingRule(
            purpose="structured_decision",
            profile="local_ollama",
            fallback="groq_fast",
        )
    }

    route = select_llm_route("structured_decision", profiles=profiles, routing=routing)

    assert route.profile_name == "local_ollama"
    assert route.model == "ollama_chat/llama3.1:8b"
    assert route.fallback_models == ()
    assert route.fallback_profile_name == ""


def test_route_selection_can_enable_explicit_remote_fallback() -> None:
    profiles = {
        "local_ollama": LLMProfile("local_ollama", "litellm", "ollama_chat/llama3.1:8b", "http://127.0.0.1:11434"),
        "groq_fast": LLMProfile("groq_fast", "litellm", "groq/llama-3.1-8b-instant", api_key_env="GROQ_API_KEY"),
    }
    routing = {
        "structured_decision": LLMRoutingRule(
            purpose="structured_decision",
            profile="local_ollama",
            fallback="groq_fast",
        )
    }

    route = select_llm_route(
        "structured_decision",
        profiles=profiles,
        routing=routing,
        allow_remote_fallback=True,
    )

    assert route.fallback_profile_name == "groq_fast"
    assert route.fallback_models == ("groq/llama-3.1-8b-instant",)
    assert route.fallback_api_key_env == "GROQ_API_KEY"


def test_route_selection_normalizes_purpose_names() -> None:
    profiles = {
        "local_ollama": LLMProfile("local_ollama", "litellm", "ollama_chat/llama3.1:8b", "http://127.0.0.1:11434"),
        "groq_fast": LLMProfile("groq_fast", "litellm", "groq/llama-3.1-8b-instant", api_key_env="GROQ_API_KEY"),
    }
    routing = {
        "structured_decision": LLMRoutingRule(
            purpose="structured_decision",
            profile="local_ollama",
            fallback="groq_fast",
        )
    }

    space_route = select_llm_route("Structured Decision", profiles=profiles, routing=routing)
    dash_route = select_llm_route("structured-decision", profiles=profiles, routing=routing)

    assert space_route.purpose == "structured_decision"
    assert space_route.profile_name == "local_ollama"
    assert dash_route.purpose == "structured_decision"
    assert dash_route.profile_name == "local_ollama"


def test_load_llm_routing_normalizes_purpose_keys(tmp_path: Path) -> None:
    routing_path = tmp_path / "routing.yaml"
    routing_path.write_text(
        """
        default_profile: local_ollama
        purposes:
          structured-decision:
            profile: local_ollama
        """,
        encoding="utf-8",
    )

    default_profile, routing = load_llm_routing(routing_path)

    assert default_profile == "local_ollama"
    assert "structured_decision" in routing
    assert routing["structured_decision"].purpose == "structured_decision"


def test_profiled_text_client_builds_litellm_client_from_route(monkeypatch) -> None:
    profiles = {
        "hf_mistral": LLMProfile("hf_mistral", "litellm", "huggingface/mistralai/Mistral-7B-Instruct-v0.3", api_key_env="HF_TOKEN"),
    }
    routing = {"normal_chat": LLMRoutingRule("normal_chat", "hf_mistral")}

    client = build_profiled_text_llm_client(
        purpose="normal_chat",
        instructions=BotInstructions(openai_model="gpt-ignored"),
        openai_client=None,
        profiles=profiles,
        routing=routing,
        env={"HF_TOKEN": "hf-secret"},
    )

    assert isinstance(client, LiteLLMTextClient)
    assert client.provider == "litellm"
    assert client.model == "huggingface/mistralai/Mistral-7B-Instruct-v0.3"
    assert client.api_key == "hf-secret"


def test_runtime_text_client_uses_explicit_profile_over_direct_openai_default() -> None:
    client = build_runtime_text_llm_client(
        instructions=BotInstructions(llm_provider="openai", llm_model="ignored"),
        openai_client=None,
        profile="local_ollama",
        fallback_models="ollama_chat/qwen2.5:7b",
        api_key="runtime-key",
        timeout="180",
        max_tokens="700",
        temperature="0.4",
    )

    assert isinstance(client, LiteLLMTextClient)
    assert client.provider == "litellm"
    assert client.model == "ollama_chat/llama3.1:8b"
    assert client.api_base == "http://127.0.0.1:11434"
    assert client.fallback_models == ("ollama_chat/qwen2.5:7b",)
    assert client.api_key == "runtime-key"
    assert client.timeout == 180
    assert client.max_tokens == 700
    assert client.temperature == 0.4


def test_runtime_text_client_profile_filters_remote_fallback_without_explicit_allow() -> None:
    blocked = build_runtime_text_llm_client(
        instructions=BotInstructions(llm_provider="openai", llm_model="ignored"),
        openai_client=None,
        profile="local_ollama",
        fallback_models="groq/llama-3.3-70b-versatile, ollama_chat/qwen2.5:7b",
    )
    allowed = build_runtime_text_llm_client(
        instructions=BotInstructions(llm_provider="openai", llm_model="ignored"),
        openai_client=None,
        profile="local_ollama",
        fallback_models="groq/llama-3.3-70b-versatile, ollama_chat/qwen2.5:7b",
        allow_remote_fallback="yes",
    )

    assert isinstance(blocked, LiteLLMTextClient)
    assert blocked.fallback_models == ("ollama_chat/qwen2.5:7b",)
    assert isinstance(allowed, LiteLLMTextClient)
    assert allowed.fallback_models == ("groq/llama-3.3-70b-versatile", "ollama_chat/qwen2.5:7b")


def test_runtime_text_client_returns_none_when_runtime_llm_is_disabled() -> None:
    client = build_runtime_text_llm_client(
        instructions=BotInstructions(llm_provider="openai", llm_model="ignored"),
        openai_client=object(),
        enabled="false",
        profile="local_ollama",
        provider="litellm",
        model="ollama_chat/llama3.1:8b",
    )

    assert client is None


def test_runtime_text_client_respects_instruction_llm_disabled_without_override() -> None:
    client = build_runtime_text_llm_client(
        instructions=BotInstructions(llm_enabled=False, llm_profile="local_ollama"),
        openai_client=object(),
    )

    assert client is None


def test_runtime_text_client_runtime_enabled_overrides_instruction_llm_disabled() -> None:
    client = build_runtime_text_llm_client(
        instructions=BotInstructions(llm_enabled=False, llm_profile="local_ollama"),
        openai_client=None,
        enabled="true",
    )

    assert isinstance(client, LiteLLMTextClient)
    assert client.model == "ollama_chat/llama3.1:8b"


def test_runtime_text_client_uses_purpose_router_when_no_direct_runtime_provider() -> None:
    client = build_runtime_text_llm_client(
        instructions=BotInstructions(llm_provider="openai", llm_model="ignored-default"),
        openai_client=None,
        purpose="Structured Decision",
    )

    assert isinstance(client, LiteLLMTextClient)
    assert client.provider == "litellm"
    assert client.model == "ollama_chat/llama3.1:8b"
    assert client.api_base == "http://127.0.0.1:11434"
    assert client.fallback_models == ()


def test_runtime_text_client_purpose_router_requires_explicit_remote_fallback() -> None:
    blocked = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        purpose="structured_decision",
    )
    allowed = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        purpose="structured_decision",
        allow_remote_fallback="yes",
    )

    assert isinstance(blocked, LiteLLMTextClient)
    assert blocked.fallback_models == ()
    assert isinstance(allowed, LiteLLMTextClient)
    assert allowed.fallback_models == ("groq/llama-3.1-8b-instant",)


def test_runtime_text_client_purpose_router_passes_fallback_profile_api_key(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def completion(**kwargs):
        model = str(kwargs["model"])
        calls.append((model, str(kwargs.get("api_key") or "")))
        if model == "ollama_chat/llama3.1:8b":
            raise RuntimeError("primary down")
        return {"id": "fallback-ok", "choices": [{"message": {"content": "Fallback Antwort"}}]}

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))
    client = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        purpose="structured_decision",
        allow_remote_fallback=True,
        env={"GROQ_API_KEY": "groq-secret"},
    )

    assert isinstance(client, LiteLLMTextClient)
    response = client.create_reply("Ping", BotInstructions(), None)

    assert response.text == "Fallback Antwort"
    assert calls == [("ollama_chat/llama3.1:8b", ""), ("groq/llama-3.1-8b-instant", "groq-secret")]


def test_runtime_text_client_direct_runtime_provider_overrides_purpose_router() -> None:
    client = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        purpose="structured_decision",
        provider="litellm",
        model="ollama_chat/qwen2.5:7b",
    )

    assert isinstance(client, LiteLLMTextClient)
    assert client.model == "ollama_chat/qwen2.5:7b"


def test_runtime_text_client_direct_provider_filters_remote_fallback_without_explicit_allow() -> None:
    blocked = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        provider="ollama",
        model="broken",
        fallback_models="groq/llama-3.3-70b-versatile,ollama_chat/qwen2.5:7b,openai/gpt-4.1-mini",
    )
    allowed = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        provider="ollama",
        model="broken",
        fallback_models="groq/llama-3.3-70b-versatile,ollama_chat/qwen2.5:7b,openai/gpt-4.1-mini",
        allow_remote_fallback=True,
    )

    assert isinstance(blocked, LiteLLMTextClient)
    assert blocked.fallback_models == ("ollama_chat/qwen2.5:7b",)
    assert isinstance(allowed, LiteLLMTextClient)
    assert allowed.fallback_models == (
        "groq/llama-3.3-70b-versatile",
        "ollama_chat/qwen2.5:7b",
        "openai/gpt-4.1-mini",
    )


def test_runtime_text_client_generic_litellm_blocks_ambiguous_unprefixed_fallbacks() -> None:
    blocked = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        provider="litellm",
        model="ollama_chat/llama3.1:8b",
        fallback_models="gpt-4.1-mini,ollama_chat/qwen2.5:7b,mistralai/Mistral-7B-Instruct-v0.3",
    )
    allowed = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        provider="litellm",
        model="ollama_chat/llama3.1:8b",
        fallback_models="gpt-4.1-mini,ollama_chat/qwen2.5:7b,mistralai/Mistral-7B-Instruct-v0.3",
        allow_remote_fallback=True,
    )

    assert isinstance(blocked, LiteLLMTextClient)
    assert blocked.fallback_models == ("ollama_chat/qwen2.5:7b",)
    assert isinstance(allowed, LiteLLMTextClient)
    assert allowed.fallback_models == (
        "gpt-4.1-mini",
        "ollama_chat/qwen2.5:7b",
        "mistralai/Mistral-7B-Instruct-v0.3",
    )


def test_runtime_text_client_filtered_remote_instruction_fallback_is_not_reused(monkeypatch) -> None:
    calls: list[str] = []

    def completion(**kwargs):
        calls.append(str(kwargs["model"]))
        raise RuntimeError("primary down")

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))
    client = build_runtime_text_llm_client(
        instructions=BotInstructions(llm_fallback_models=("groq/llama-3.3-70b-versatile",)),
        openai_client=None,
        provider="ollama",
        model="broken",
    )

    assert isinstance(client, LiteLLMTextClient)
    with pytest.raises(LLMAPIError):
        client.create_reply("Ping", BotInstructions(llm_fallback_models=("groq/llama-3.3-70b-versatile",)), None)

    assert calls == ["ollama/broken"]


def test_runtime_text_client_builds_openai_client_for_openai_profile_env_key() -> None:
    captured: list[str] = []

    class FakeOpenAIClient:
        def __init__(self, api_key: str) -> None:
            captured.append(api_key)
            self.calls: list[str] = []

        def create_reply(self, _user_text, instructions, _previous_response_id=None):
            self.calls.append(instructions.openai_model)
            return object()

    client = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        profile="openai_premium",
        env={"OPENAI_API_KEY": "profile-openai-key"},
        openai_client_factory=FakeOpenAIClient,
    )

    assert captured == ["profile-openai-key"]
    client.create_reply("Ping", BotInstructions(openai_model="gpt-ignored"), None)
    assert client.client.calls == ["gpt-5.5"]


def test_runtime_text_client_applies_openai_route_model_to_legacy_client() -> None:
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def create_reply(self, _user_text, instructions, _previous_response_id=None):
            self.calls.append(instructions.openai_model)
            return object()

    openai_client = FakeOpenAIClient()
    client = build_runtime_text_llm_client(
        instructions=BotInstructions(openai_model="gpt-legacy"),
        openai_client=openai_client,
        purpose="hard_reasoning",
    )

    client.create_reply("Ping", BotInstructions(openai_model="gpt-legacy"), None)

    assert client.client is openai_client
    assert openai_client.calls == ["gpt-5.5"]


def test_simple_yaml_fallback_parser_handles_plan2_shape(tmp_path: Path, monkeypatch) -> None:
    profiles_path = tmp_path / "profiles.yaml"
    profiles_path.write_text(
        """
        profiles:
          local_ollama:
            provider: litellm
            model: ollama_chat/llama3.1:8b
            base_url: http://127.0.0.1:11434
            api_key_env: ""
        """,
        encoding="utf-8",
    )

    import TeeBotus.llm.profiles as profile_module

    monkeypatch.setattr(profile_module, "yaml", None, raising=False)
    monkeypatch.setitem(__import__("sys").modules, "yaml", None)

    profiles = load_llm_profiles(profiles_path)

    assert profiles["local_ollama"].model == "ollama_chat/llama3.1:8b"
    assert profiles["local_ollama"].base_url == "http://127.0.0.1:11434"
