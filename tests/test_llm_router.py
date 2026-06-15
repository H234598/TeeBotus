from __future__ import annotations

from pathlib import Path

from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.profiles import (
    LLMProfile,
    LLMRoutingRule,
    build_profiled_text_llm_client,
    load_llm_profiles,
    load_llm_routing,
    select_llm_route,
)
from TeeBotus.llm_client import LiteLLMTextClient


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
    assert profiles["groq_fast"].api_key_env == "GROQ_API_KEY"
    assert routing["structured_decision"].profile == "local_ollama"
    assert routing["structured_decision"].fallback == "groq_fast"


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
