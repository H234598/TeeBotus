from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.capabilities import HF_POOL_TEXT_CAPABILITIES
from TeeBotus.llm.litellm_gemini_provider import LiteLLMGeminiStatefulClient
from TeeBotus.llm.hf_pool.provider import HFPoolProvider
from TeeBotus.llm.profiles import (
    LLMProfile,
    LLMRoute,
    LLMRoutingRule,
    build_profiled_text_llm_client,
    load_llm_profiles,
    load_llm_routing,
    select_llm_route,
)
from TeeBotus.llm_client import LLMAPIError, LiteLLMTextClient, normalize_llm_provider
from TeeBotus.runtime.llm_factory import build_runtime_structured_decision_runner, build_runtime_text_llm_client


def test_default_profile_files_define_plan2_provider_profiles() -> None:
    profiles = load_llm_profiles()
    default_profile, routing = load_llm_routing()

    assert default_profile == "local_ollama"
    assert profiles["local_ollama"] == LLMProfile(
        name="local_ollama",
        provider="litellm",
        model="ollama_chat/llama3.2:3b",
        base_url="http://127.0.0.1:11434",
        api_key_env="",
    )
    assert profiles["hf_mistral"] == LLMProfile(
        name="hf_mistral",
        provider="litellm",
        model="huggingface/mistralai/Mistral-7B-Instruct-v0.3",
        api_key_env="HUGGINGFACE_API_KEY",
    )
    assert profiles["hf_pool_default"] == LLMProfile(
        name="hf_pool_default",
        provider="hf_pool",
        model="pool:default#normal_chat",
        api_key_env="",
    )
    assert profiles["hf_pool_structured"].model == "pool:default#structured_decision"
    assert profiles["hf_pool_quality"].model == "pool:default#psychology_explainer"
    assert profiles["hf_pool_bibliothekar"].model == "pool:default#bibliothekar_answer"
    assert profiles["hf_pool_structured"].provider == "hf_pool"
    assert profiles["hf_pool_quality"].provider == "hf_pool"
    assert profiles["hf_pool_bibliothekar"].provider == "hf_pool"
    assert profiles["groq_fast"].api_key_env == "GROQ_API_KEY"
    assert profiles["groq_fast"].provider == "litellm"
    assert profiles["groq_fast"].model.startswith("groq/")
    assert profiles["gemini_flash_stateless"] == LLMProfile(
        name="gemini_flash_stateless",
        provider="litellm_gemini_stateless",
        model="gemini/gemini-3.5-flash",
        api_key_env="GEMINI_API_KEY",
    )
    assert profiles["gemini_flash_stateful"] == LLMProfile(
        name="gemini_flash_stateful",
        provider="litellm_gemini_stateful",
        model="gemini/gemini-3.5-flash",
        api_key_env="GEMINI_API_KEY",
    )
    assert profiles["gemini_flash_paid_stateless"] == LLMProfile(
        name="gemini_flash_paid_stateless",
        provider="litellm_gemini_paid_stateless",
        model="gemini/gemini-3.5-flash",
        api_key_env="GEMINI_API_KEY",
    )
    assert profiles["gemini_flash_paid_stateful"] == LLMProfile(
        name="gemini_flash_paid_stateful",
        provider="litellm_gemini_paid_stateful",
        model="gemini/gemini-3.5-flash",
        api_key_env="GEMINI_API_KEY",
    )
    assert profiles["gemini_2_5_flash_stateless"] == LLMProfile(
        name="gemini_2_5_flash_stateless",
        provider="litellm_gemini_stateless",
        model="gemini/gemini-2.5-flash",
        api_key_env="GEMINI_API_KEY",
    )
    assert profiles["gemini_2_5_flash_stateful"] == LLMProfile(
        name="gemini_2_5_flash_stateful",
        provider="litellm_gemini_stateful",
        model="gemini/gemini-2.5-flash",
        api_key_env="GEMINI_API_KEY",
    )
    assert profiles["gemini_2_5_flash_paid_stateless"] == LLMProfile(
        name="gemini_2_5_flash_paid_stateless",
        provider="litellm_gemini_paid_stateless",
        model="gemini/gemini-2.5-flash",
        api_key_env="GEMINI_API_KEY",
    )
    assert profiles["gemini_2_5_flash_paid_stateful"] == LLMProfile(
        name="gemini_2_5_flash_paid_stateful",
        provider="litellm_gemini_paid_stateful",
        model="gemini/gemini-2.5-flash",
        api_key_env="GEMINI_API_KEY",
    )
    assert profiles["vertex_gemini_flash"] == LLMProfile(
        name="vertex_gemini_flash",
        provider="litellm",
        model="vertex_ai/gemini-3.5-flash",
        api_key_env="GOOGLE_APPLICATION_CREDENTIALS",
    )
    assert profiles["vertex_gemini_2_5_flash"] == LLMProfile(
        name="vertex_gemini_2_5_flash",
        provider="litellm",
        model="vertex_ai/gemini-2.5-flash",
        api_key_env="GOOGLE_APPLICATION_CREDENTIALS",
    )
    assert profiles["openai_premium"].provider == "litellm"
    assert profiles["openai_premium"].model == "openai/gpt-5.5"
    assert profiles["openai_premium"].api_key_env == "OPENAI_API_KEY"
    assert routing["structured_decision"].profile == "hf_pool_structured"
    assert routing["structured_decision"].fallback == "local_ollama"
    assert routing["hard_reasoning"].profile == "openai_premium"
    assert routing["hard_reasoning"].fallback == "gemini_flash_stateful"


def test_runtime_profile_client_uses_gemini_key_ring_for_stateless_gemini_profile(monkeypatch) -> None:
    client = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        profile="gemini_flash_stateless",
        env={
            "GEMINI_API_KEYS_ACCOUNT_1": "a1,a2",
            "GEMINI_API_KEYS_ACCOUNT_2": "b1,b2",
            "GEMINI_API_KEYS_ACCOUNT_3": "c1,c2",
        },
    )

    assert isinstance(client, LiteLLMTextClient)
    assert client.api_key_ring is not None
    assert client.api_key_ring.keys == ("a1", "b1", "c1", "a2", "b2", "c2")


def test_runtime_profile_client_uses_gemini_key_ring_for_stateful_gemini_profile(monkeypatch) -> None:
    client = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        profile="gemini_flash_stateful",
        env={
            "GEMINI_API_KEYS_ACCOUNT_1": "a1,a2",
            "GEMINI_API_KEYS_ACCOUNT_2": "b1,b2",
            "GEMINI_API_KEYS_ACCOUNT_3": "c1,c2",
        },
    )

    assert isinstance(client, LiteLLMGeminiStatefulClient)
    assert client.api_key_ring is not None
    assert client.api_key_ring.keys == ("a1", "b1", "c1", "a2", "b2", "c2")


def test_runtime_profile_client_uses_paid_gemini_profile_without_free_tier_guard(monkeypatch) -> None:
    client = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        profile="gemini_flash_paid_stateful",
        env={
            "GEMINI_API_KEYS_ACCOUNT_1": "a1,a2",
            "GEMINI_API_KEYS_ACCOUNT_2": "b1,b2",
            "TEEBOTUS_GEMINI_FREE_TIER_RPM": "0",
            "TEEBOTUS_GEMINI_FREE_TIER_TPM": "0",
            "TEEBOTUS_GEMINI_FREE_TIER_RPD": "0",
        },
    )

    assert isinstance(client, LiteLLMGeminiStatefulClient)
    assert client.provider == "litellm_gemini_paid_stateful"
    assert client.api_key_ring is not None
    assert client.api_key_ring.keys == ("a1", "b1", "a2", "b2")
    assert client.gemini_free_tier_limits.status_summary() == "off"


def test_runtime_profile_client_uses_gemini_service_tier_env_switch() -> None:
    client = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        profile="gemini_flash_stateless",
        env={
            "GEMINI_API_KEY": "gemini-key",
            "TEEBOTUS_GEMINI_SERVICE_TIER": "Flex",
        },
    )

    assert isinstance(client, LiteLLMTextClient)
    assert client.service_tier == "flex"


def test_runtime_profile_client_prefers_instance_gemini_flex_flag() -> None:
    client = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        profile="gemini_flash_stateful",
        env={
            "GEMINI_API_KEY": "gemini-key",
            "TEEBOTUS_GEMINI_FLEX_SERVICE_TIER_DEMO": "yes",
        },
        instance_name="Demo",
    )

    assert isinstance(client, LiteLLMGeminiStatefulClient)
    assert client.service_tier == "flex"


def test_runtime_profile_client_instance_service_tier_off_overrides_global_flex() -> None:
    client = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        profile="gemini_flash_stateful",
        env={
            "GEMINI_API_KEY": "gemini-key",
            "TEEBOTUS_GEMINI_SERVICE_TIER": "flex",
            "TEEBOTUS_GEMINI_SERVICE_TIER_DEMO": "off",
        },
        instance_name="Demo",
    )

    assert isinstance(client, LiteLLMGeminiStatefulClient)
    assert client.service_tier == ""


def test_normalize_llm_provider_accepts_hf_pool_aliases() -> None:
    assert normalize_llm_provider("hf_pool") == "hf_pool"
    assert normalize_llm_provider("hfpool") == "hf_pool"
    assert normalize_llm_provider("huggingface-pool") == "hf_pool"


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
    assert route.fallback_base_url == ""


def test_route_selection_keeps_local_fallback_base_url() -> None:
    profiles = {
        "groq_fast": LLMProfile("groq_fast", "litellm", "groq/llama-3.1-8b-instant", api_key_env="GROQ_API_KEY"),
        "local_ollama": LLMProfile("local_ollama", "litellm", "ollama_chat/llama3.1:8b", "http://127.0.0.1:11557"),
    }
    routing = {
        "cheap_fast": LLMRoutingRule(
            purpose="cheap_fast",
            profile="groq_fast",
            fallback="local_ollama",
        )
    }

    route = select_llm_route("cheap_fast", profiles=profiles, routing=routing)

    assert route.profile_name == "groq_fast"
    assert route.fallback_profile_name == "local_ollama"
    assert route.fallback_models == ("ollama_chat/llama3.1:8b",)
    assert route.fallback_base_url == "http://127.0.0.1:11557"


def test_route_selection_treats_ambiguous_litellm_fallback_profiles_as_remote() -> None:
    profiles = {
        "local_ollama": LLMProfile("local_ollama", "litellm", "ollama_chat/llama3.1:8b", "http://127.0.0.1:11434"),
        "unprefixed_openai": LLMProfile("unprefixed_openai", "litellm", "gpt-4.1-mini", api_key_env="OPENAI_API_KEY"),
    }
    routing = {
        "hard_reasoning": LLMRoutingRule(
            purpose="hard_reasoning",
            profile="local_ollama",
            fallback="unprefixed_openai",
        )
    }

    blocked = select_llm_route("hard_reasoning", profiles=profiles, routing=routing)
    allowed = select_llm_route("hard_reasoning", profiles=profiles, routing=routing, allow_remote_fallback=True)

    assert blocked.fallback_models == ()
    assert blocked.fallback_profile_name == ""
    assert allowed.fallback_profile_name == "unprefixed_openai"
    assert allowed.fallback_models == ("gpt-4.1-mini",)
    assert allowed.fallback_api_key_env == "OPENAI_API_KEY"


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


def test_llm_loaders_skip_non_string_names_and_references(monkeypatch, tmp_path: Path) -> None:
    profiles_path = tmp_path / "profiles.yaml"
    routing_path = tmp_path / "routing.yaml"
    profiles_path.write_text("profiles: {}\n", encoding="utf-8")
    routing_path.write_text("default_profile: local_ollama\npurposes: {}\n", encoding="utf-8")

    import TeeBotus.llm.profiles as profile_module

    def fake_loader(path):
        if Path(path) == profiles_path:
            return {
                "profiles": {
                    "local_ollama": {
                        "provider": "litellm",
                        "model": "ollama_chat/llama3.2:3b",
                        "base_url": "http://127.0.0.1:11434",
                    },
                    123: {
                        "provider": "litellm",
                        "model": "ollama_chat/ignored:latest",
                    },
                    "bad_model_type": {
                        "provider": "litellm",
                        "model": 123,
                    },
                }
            }
        if Path(path) == routing_path:
            return {
                "default_profile": 123,
                "purposes": {
                    "normal_chat": {"profile": "local_ollama"},
                    "bad_profile_type": {"profile": 456},
                    "bad_fallback_type": {"profile": "local_ollama", "fallback": ["local_ollama"]},
                    456: {"profile": "local_ollama"},
                },
            }
        return {}

    monkeypatch.setattr(profile_module, "_load_yaml_mapping", fake_loader)

    profiles = load_llm_profiles(profiles_path)
    default_profile, routing = load_llm_routing(routing_path)

    assert default_profile == ""
    assert set(profiles) == {"local_ollama"}
    assert set(routing) == {"normal_chat", "bad_fallback_type"}
    assert routing["bad_fallback_type"].fallback == ""


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


def test_profiled_text_client_passes_gemini_service_tier_from_profile() -> None:
    profiles = {
        "gemini_flex": LLMProfile(
            "gemini_flex",
            "litellm",
            "gemini/gemini-2.5-flash",
            api_key_env="GEMINI_API_KEY",
            service_tier="flex",
        ),
    }
    routing = {"normal_chat": LLMRoutingRule("normal_chat", "gemini_flex")}

    client = build_profiled_text_llm_client(
        purpose="normal_chat",
        instructions=BotInstructions(),
        openai_client=None,
        profiles=profiles,
        routing=routing,
        env={"GEMINI_API_KEY": "gemini-secret"},
    )

    assert isinstance(client, LiteLLMTextClient)
    assert client.service_tier == "flex"


def test_profiled_text_client_does_not_reuse_instruction_remote_fallbacks_when_route_blocks_them() -> None:
    client = build_profiled_text_llm_client(
        purpose="normal_chat",
        instructions=BotInstructions(llm_fallback_models=("groq/llama-3.3-70b-versatile",)),
        openai_client=None,
        profiles={
            "local_ollama": LLMProfile(
                "local_ollama",
                "litellm",
                "ollama_chat/llama3.1:8b",
                "http://127.0.0.1:11434",
            ),
        },
        routing={"normal_chat": LLMRoutingRule("normal_chat", "local_ollama")},
    )

    assert isinstance(client, LiteLLMTextClient)
    assert client.fallback_models == ()
    assert client.use_instruction_fallback_models is False


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
    assert client.model == "ollama_chat/llama3.2:3b"
    assert client.api_base == "http://127.0.0.1:11434"
    assert client.fallback_models == ("ollama_chat/qwen2.5:7b",)
    assert client.api_key == "runtime-key"
    assert client.timeout == 180
    assert client.max_tokens == 700
    assert client.temperature == 0.4


def test_runtime_text_client_profile_uses_runtime_base_url_override() -> None:
    client = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        profile="local_ollama",
        api_base="http://127.0.0.1:11555/api",
    )

    assert isinstance(client, LiteLLMTextClient)
    assert client.model == "ollama_chat/llama3.2:3b"
    assert client.api_base == "http://127.0.0.1:11555/api"


def test_runtime_text_client_direct_provider_overrides_instruction_profile() -> None:
    client = build_runtime_text_llm_client(
        instructions=BotInstructions(llm_profile="hf_mistral"),
        openai_client=None,
        provider="litellm",
        model="ollama_chat/llama3.1:8b",
        api_base="http://127.0.0.1:11434",
    )

    assert isinstance(client, LiteLLMTextClient)
    assert client.provider == "litellm"
    assert client.model == "ollama_chat/llama3.1:8b"
    assert client.api_base == "http://127.0.0.1:11434"


def test_runtime_text_client_builds_hf_pool_provider_for_explicit_profile() -> None:
    client = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        profile="hf_pool_default",
    )

    assert isinstance(client, HFPoolProvider)
    assert client.pool_name == "default"
    assert client.purpose == "normal_chat"
    assert client.model_selector == "pool:default#normal_chat"
    assert client.capabilities is HF_POOL_TEXT_CAPABILITIES


def test_runtime_text_client_uses_hf_pool_model_selector_purpose_for_explicit_profile() -> None:
    client = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        profile="hf_pool_structured",
    )

    assert isinstance(client, HFPoolProvider)
    assert client.pool_name == "default"
    assert client.purpose == "structured_decision"
    assert client.model_selector == "pool:default#structured_decision"


def test_runtime_text_client_purpose_overrides_instruction_profile() -> None:
    client = build_runtime_text_llm_client(
        instructions=BotInstructions(llm_profile="hf_mistral"),
        openai_client=None,
        purpose="structured_decision",
    )

    assert isinstance(client, HFPoolProvider)
    assert client.pool_name == "default"
    assert client.purpose == "structured_decision"
    assert client.model_selector == "pool:default#structured_decision"
    assert isinstance(client.fallback_client, LiteLLMTextClient)
    assert client.fallback_client.provider == "litellm"
    assert client.fallback_client.model == "ollama_chat/llama3.2:3b"


def test_runtime_text_client_call_uses_runtime_generation_overrides(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def completion(**kwargs):
        calls.append(kwargs)
        return {"id": "runtime-overrides", "choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))
    client = build_runtime_text_llm_client(
        instructions=BotInstructions(
            llm_provider="openai",
            llm_model="ignored",
            llm_timeout_seconds=5,
            llm_max_output_tokens=10,
            llm_temperature=0.9,
        ),
        openai_client=None,
        profile="local_ollama",
        timeout="180",
        max_tokens="700",
        temperature="0.4",
    )

    assert isinstance(client, LiteLLMTextClient)
    response = client.create_reply(
        "Ping",
        BotInstructions(
            llm_timeout_seconds=5,
            llm_max_output_tokens=10,
            llm_temperature=0.9,
            openai_timeout_seconds=6,
            openai_max_output_tokens=11,
        ),
        None,
    )

    assert response.text == "ok"
    assert calls[0]["timeout"] == 180
    assert calls[0]["max_tokens"] == 700
    assert calls[0]["temperature"] == 0.4


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


def test_runtime_fallback_filter_blocks_unprefixed_gemini_for_gemini_provider_alias() -> None:
    from TeeBotus.runtime.llm_factory import filter_runtime_fallback_models

    blocked = filter_runtime_fallback_models(
        provider="gemini_paid_interactions",
        fallback_models="gemini-2.5-flash, ollama_chat/qwen2.5:7b",
        allow_remote_fallback=False,
    )
    allowed = filter_runtime_fallback_models(
        provider="gemini_paid_interactions",
        fallback_models="gemini-2.5-flash, ollama_chat/qwen2.5:7b",
        allow_remote_fallback=True,
    )

    assert blocked == ("ollama_chat/qwen2.5:7b",)
    assert allowed == ("gemini-2.5-flash", "ollama_chat/qwen2.5:7b")


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
    assert client.model == "ollama_chat/llama3.2:3b"


def test_runtime_text_client_uses_purpose_router_when_no_direct_runtime_provider() -> None:
    client = build_runtime_text_llm_client(
        instructions=BotInstructions(llm_provider="openai", llm_model="ignored-default"),
        openai_client=None,
        purpose="Structured Decision",
    )

    assert isinstance(client, HFPoolProvider)
    assert client.pool_name == "default"
    assert client.purpose == "structured_decision"
    assert isinstance(client.fallback_client, LiteLLMTextClient)
    assert client.fallback_client.provider == "litellm"
    assert client.fallback_client.model == "ollama_chat/llama3.2:3b"
    assert client.fallback_client.api_base == "http://127.0.0.1:11434"
    assert client.fallback_client.fallback_models == ()


def test_runtime_text_client_purpose_router_uses_local_fallback_by_default() -> None:
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

    assert isinstance(blocked, HFPoolProvider)
    assert isinstance(blocked.fallback_client, LiteLLMTextClient)
    assert blocked.fallback_client.model == "ollama_chat/llama3.2:3b"
    assert isinstance(allowed, HFPoolProvider)
    assert isinstance(allowed.fallback_client, LiteLLMTextClient)
    assert allowed.fallback_client.model == "ollama_chat/llama3.2:3b"


def test_runtime_text_client_purpose_route_uses_runtime_base_url_override() -> None:
    client = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        purpose="structured_decision",
        api_base="http://127.0.0.1:11556/api",
    )

    assert isinstance(client, HFPoolProvider)
    assert isinstance(client.fallback_client, LiteLLMTextClient)
    assert client.fallback_client.model == "ollama_chat/llama3.2:3b"
    assert client.fallback_client.api_base == "http://127.0.0.1:11556/api"


def test_runtime_text_client_route_builder_filters_remote_fallback_defensively(monkeypatch) -> None:
    monkeypatch.setattr(
        "TeeBotus.runtime.llm_factory.select_llm_route",
        lambda *_args, **_kwargs: LLMRoute(
            purpose="structured_decision",
            profile_name="local_ollama",
            provider="litellm",
            model="ollama_chat/llama3.1:8b",
            base_url="http://127.0.0.1:11434",
            fallback_profile_name="groq_fast",
            fallback_model="groq/llama-3.1-8b-instant",
            fallback_api_key_env="GROQ_API_KEY",
        ),
    )

    blocked = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        purpose="structured_decision",
    )
    allowed = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        purpose="structured_decision",
        allow_remote_fallback=True,
    )

    assert isinstance(blocked, LiteLLMTextClient)
    assert blocked.fallback_models == ()
    assert isinstance(allowed, LiteLLMTextClient)
    assert allowed.fallback_models == ("groq/llama-3.1-8b-instant",)


def test_runtime_text_client_purpose_router_uses_local_fallback_when_hf_pool_unavailable(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def completion(**kwargs):
        model = str(kwargs["model"])
        calls.append((model, str(kwargs.get("api_key") or "")))
        return {"id": "fallback-ok", "choices": [{"message": {"content": "Fallback Antwort"}}]}

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))
    client = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        purpose="structured_decision",
    )

    assert isinstance(client, HFPoolProvider)
    response = client.create_reply("Ping", BotInstructions(), None)

    assert response.text == "Fallback Antwort"
    assert calls == [("ollama_chat/llama3.2:3b", "")]


def test_runtime_text_client_route_passes_fallback_profile_base_url(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def completion(**kwargs):
        model = str(kwargs["model"])
        calls.append((model, str(kwargs.get("api_base") or "")))
        if model == "groq/primary":
            raise RuntimeError("primary down")
        return {"id": "fallback-ok", "choices": [{"message": {"content": "Fallback Antwort"}}]}

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))
    monkeypatch.setattr(
        "TeeBotus.runtime.llm_factory.select_llm_route",
        lambda *_args, **_kwargs: LLMRoute(
            purpose="cheap_fast",
            profile_name="groq_fast",
            provider="litellm",
            model="groq/primary",
            fallback_profile_name="local_ollama",
            fallback_model="ollama_chat/llama3.1:8b",
            fallback_base_url="http://127.0.0.1:11557/api",
        ),
    )

    client = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        purpose="cheap_fast",
    )

    assert isinstance(client, LiteLLMTextClient)
    response = client.create_reply("Ping", BotInstructions(), None)

    assert response.text == "Fallback Antwort"
    assert calls == [("groq/primary", ""), ("ollama_chat/llama3.1:8b", "http://127.0.0.1:11557/api")]


def test_runtime_text_client_route_rejects_unsafe_fallback_ollama_base_url_before_call(monkeypatch) -> None:
    def completion(**_kwargs):
        raise AssertionError("unsafe fallback Ollama api_base must not reach LiteLLM")

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))
    monkeypatch.setattr(
        "TeeBotus.runtime.llm_factory.select_llm_route",
        lambda *_args, **_kwargs: LLMRoute(
            purpose="cheap_fast",
            profile_name="groq_fast",
            provider="litellm",
            model="groq/primary",
            fallback_profile_name="local_ollama",
            fallback_model="ollama_chat/llama3.1:8b",
            fallback_base_url="http://user:secret@ollama.example:11434/api?token=plain",
        ),
    )

    client = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        purpose="cheap_fast",
    )

    assert isinstance(client, LiteLLMTextClient)
    with pytest.raises(LLMAPIError, match="Unsafe Ollama api_base: credentials are not allowed"):
        client.create_reply("Ping", BotInstructions(), None)


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


def test_runtime_text_client_uses_instruction_provider_and_model_without_runtime_overrides() -> None:
    client = build_runtime_text_llm_client(
        instructions=BotInstructions(
            llm_provider="litellm",
            llm_model="ollama_chat/qwen2.5:7b",
            llm_fallback_models=("groq/llama-3.3-70b-versatile", "ollama_chat/llama3.1:8b"),
        ),
        openai_client=None,
    )

    assert isinstance(client, LiteLLMTextClient)
    assert client.provider == "litellm"
    assert client.model == "ollama_chat/qwen2.5:7b"
    assert client.fallback_models == ("ollama_chat/llama3.1:8b",)


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


def test_runtime_text_client_routes_openai_profile_through_litellm() -> None:
    captured: list[str] = []

    class FakeOpenAIClient:
        def __init__(self, api_key: str) -> None:
            captured.append(api_key)

    client = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        profile="openai_premium",
        env={"OPENAI_API_KEY": "profile-openai-key"},
        openai_client_factory=FakeOpenAIClient,
    )

    assert isinstance(client, LiteLLMTextClient)
    assert captured == []
    assert client.provider == "litellm"
    assert client.model == "openai/gpt-5.5"
    assert client.api_key == "profile-openai-key"


def test_runtime_text_client_routes_openai_route_through_litellm() -> None:
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

    assert isinstance(client, LiteLLMTextClient)
    assert client.provider == "litellm"
    assert client.model == "openai/gpt-5.5"
    assert openai_client.calls == []


def test_runtime_text_client_routes_direct_runtime_openai_provider_through_litellm() -> None:
    captured: list[str] = []

    class FakeOpenAIClient:
        def __init__(self, api_key: str) -> None:
            captured.append(api_key)

        def create_reply(self, *_args, **_kwargs):
            return object()

    client = build_runtime_text_llm_client(
        instructions=BotInstructions(openai_enabled=True),
        openai_client=None,
        provider="openai",
        api_key="runtime-openai-key",
        openai_client_factory=FakeOpenAIClient,
    )

    assert isinstance(client, LiteLLMTextClient)
    assert captured == []
    assert client.provider == "litellm"
    assert client.model == "openai/gpt-5.5"
    assert client.api_key == "runtime-openai-key"


def test_runtime_text_client_applies_direct_openai_runtime_model_to_litellm() -> None:
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.models: list[str] = []

        def create_reply(self, _user_text, instructions, _previous_response_id=None):
            self.models.append(instructions.openai_model)
            return object()

    openai_client = FakeOpenAIClient()
    client = build_runtime_text_llm_client(
        instructions=BotInstructions(openai_model="gpt-legacy"),
        openai_client=openai_client,
        provider="openai",
        model="gpt-runtime",
    )

    assert isinstance(client, LiteLLMTextClient)
    assert client.provider == "litellm"
    assert client.model == "openai/gpt-runtime"
    assert openai_client.models == []


def test_runtime_text_client_routes_legacy_default_openai_key_through_litellm() -> None:
    captured: list[str] = []

    class FakeOpenAIClient:
        def __init__(self, api_key: str) -> None:
            captured.append(api_key)

        def create_reply(self, *_args, **_kwargs):
            return object()

    client = build_runtime_text_llm_client(
        instructions=BotInstructions(openai_enabled=True),
        openai_client=None,
        default_api_key="legacy-openai-key",
        openai_client_factory=FakeOpenAIClient,
    )

    assert isinstance(client, LiteLLMTextClient)
    assert captured == []
    assert client.provider == "litellm"
    assert client.model == "openai/gpt-5.5"
    assert client.api_key == "legacy-openai-key"


def test_runtime_structured_decision_runner_respects_disabled_flag() -> None:
    assert build_runtime_structured_decision_runner(enabled="off") is None


def test_runtime_structured_decision_runner_follows_instruction_llm_enabled(monkeypatch) -> None:
    import TeeBotus.decisions.pydantic_agent as pydantic_agent

    calls: list[str] = []

    def fake_builder(purpose: str, **_kwargs):
        calls.append(purpose)

        def runner(_prompt: str, _schema: type[object]) -> object:
            return object()

        return runner

    monkeypatch.setattr(pydantic_agent, "build_router_pydantic_ai_model_runner", fake_builder)

    disabled = build_runtime_structured_decision_runner(instructions=BotInstructions(llm_enabled=False))
    explicit = build_runtime_structured_decision_runner(
        instructions=BotInstructions(llm_enabled=False, structured_decision_enabled=True)
    )

    assert disabled is None
    assert explicit is not None
    assert calls == ["structured_decision"]


def test_runtime_structured_decision_runner_treats_runtime_llm_route_as_enabled(monkeypatch) -> None:
    import TeeBotus.decisions.pydantic_agent as pydantic_agent

    calls: list[str] = []

    def fake_builder(purpose: str, **_kwargs):
        calls.append(purpose)

        def runner(_prompt: str, _schema: type[object]) -> object:
            return object()

        return runner

    monkeypatch.setattr(pydantic_agent, "build_router_pydantic_ai_model_runner", fake_builder)

    runner = build_runtime_structured_decision_runner(
        instructions=BotInstructions(llm_enabled=False),
        runtime_llm_configured=True,
    )

    assert runner is not None
    assert calls == ["structured_decision"]


def test_runtime_structured_decision_runner_guards_provider_errors(monkeypatch) -> None:
    import TeeBotus.decisions.pydantic_agent as pydantic_agent

    calls: list[dict[str, object]] = []

    def fake_builder(purpose: str, *, allow_remote_fallback: bool, **_kwargs):
        calls.append({"purpose": purpose, "allow_remote_fallback": allow_remote_fallback})

        def runner(_prompt: str, _schema: type[object]) -> object:
            raise RuntimeError("provider unavailable")

        setattr(runner, "llm_provider", "hf_pool")
        setattr(runner, "model_name", "pool:default#structured_decision")
        return runner

    monkeypatch.setattr(pydantic_agent, "build_router_pydantic_ai_model_runner", fake_builder)

    runner = build_runtime_structured_decision_runner(allow_remote_fallback="yes")

    assert runner is not None
    assert runner("Prompt", object) is None
    assert getattr(runner, "llm_provider") == "hf_pool"
    assert getattr(runner, "model_name") == "pool:default#structured_decision"
    assert calls == [{"purpose": "structured_decision", "allow_remote_fallback": True}]


def test_runtime_structured_decision_runner_respects_max_output_retries_env(monkeypatch) -> None:
    import TeeBotus.ai_structures.pydantic_ai_adapter as adapter
    import TeeBotus.decisions.pydantic_agent as pydantic_agent

    calls: list[dict[str, object]] = []

    def fake_builder(
        model: str, *, output_retries: int | None = None, **_kwargs: object
    ) -> object:
        calls.append({"model": model, "output_retries": output_retries})

        def runner(_prompt: str, _schema: type[object]) -> object:
            return object()

        return runner

    def fake_selector(_purpose: str, allow_remote_fallback: bool = False):
        assert allow_remote_fallback is False
        from types import SimpleNamespace

        return SimpleNamespace(
            model="mocked-structured-model",
            base_url="",
            fallback_model="",
            fallback_base_url="",
            purpose="structured_decision",
            fallback_profile_name="",
        )

    monkeypatch.setattr(adapter, "build_pydantic_ai_model_runner", fake_builder)
    pydantic_agent.build_router_pydantic_ai_model_runner(
        route_selector=fake_selector,
        env={"TEEBOTUS_STRUCTURED_DECISION_MAX_OUTPUT_RETRIES": "2"}
    )

    assert calls
    assert calls[0]["output_retries"] == 2


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
