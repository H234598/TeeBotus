from __future__ import annotations

from pathlib import Path

import pytest

from TeeBotus.runtime.config import (
    RuntimeConfigError,
    build_account_run_configs,
    build_runtime_config,
    resolve_channels,
    resolve_openai_key,
    resolve_selected_instances,
    resolve_matrix_accounts,
    resolve_llm_setting,
    resolve_signal_accounts,
    resolve_telegram_tokens,
)


def test_channels_default_to_telegram_signal_and_matrix():
    assert resolve_channels({}) == ("telegram", "signal", "matrix")
    assert resolve_channels({}, cli_channels="telegram") == ("telegram",)


def test_duplicate_channels_raise_instead_of_starting_adapter_twice():
    with pytest.raises(RuntimeConfigError):
        resolve_channels({}, cli_channels="telegram,telegram")


def test_openai_key_resolution_allows_shared_instance_key():
    env = {"OPENAI_API_KEY_DEPRESSIONSBOT": "sk-shared"}

    assert resolve_openai_key("Depressionsbot", "telegram", 1, env) == "sk-shared"
    assert resolve_openai_key("Depressionsbot", "signal", 1, env) == "sk-shared"


def test_openai_key_resolution_prefers_channel_slot_key():
    env = {
        "OPENAI_API_KEY_DEPRESSIONSBOT": "sk-shared",
        "OPENAI_API_KEY_DEPRESSIONSBOT_SIGNAL_1": "sk-signal",
    }

    assert resolve_openai_key("Depressionsbot", "signal", 1, env) == "sk-signal"


def test_openai_key_resolution_accepts_channel_wide_key_before_instance_slot_key():
    env = {
        "OPENAI_API_KEY_DEPRESSIONSBOT_SIGNAL": "sk-signal-channel",
        "OPENAI_API_KEY_DEPRESSIONSBOT_1": "sk-instance-slot",
    }

    assert resolve_openai_key("Depressionsbot", "signal", 1, env) == "sk-signal-channel"


def test_llm_setting_resolution_prefers_channel_slot_over_instance() -> None:
    env = {
        "TEEBOTUS_LLM_PROVIDER_DEPRESSIONSBOT": "ollama",
        "TEEBOTUS_LLM_ENABLED_DEPRESSIONSBOT": "false",
        "TEEBOTUS_LLM_PROVIDER_DEPRESSIONSBOT_SIGNAL": "huggingface",
        "TEEBOTUS_LLM_PROVIDER_DEPRESSIONSBOT_SIGNAL_2": "groq",
        "TEEBOTUS_LLM_MODEL_DEPRESSIONSBOT": "llama3.1:8b",
        "TEEBOTUS_LLM_FALLBACK_MODELS_DEPRESSIONSBOT": "groq/llama-3.3-70b-versatile,openai/gpt-4.1-mini",
        "TEEBOTUS_LLM_API_KEY": "global-key",
        "TEEBOTUS_LLM_API_KEY_DEPRESSIONSBOT_SIGNAL": "signal-key",
        "TEEBOTUS_LLM_BASE_URL_DEPRESSIONSBOT": "http://localhost:11434",
        "TEEBOTUS_LLM_PROFILE_DEPRESSIONSBOT": "local_ollama",
        "TEEBOTUS_LLM_PURPOSE_DEPRESSIONSBOT": "structured_decision",
        "TEEBOTUS_LLM_ALLOW_REMOTE_FALLBACK_DEPRESSIONSBOT_SIGNAL": "yes",
        "TEEBOTUS_LLM_TIMEOUT_SECONDS_DEPRESSIONSBOT": "180",
        "TEEBOTUS_LLM_MAX_OUTPUT_TOKENS_DEPRESSIONSBOT": "700",
        "TEEBOTUS_LLM_TEMPERATURE_DEPRESSIONSBOT": "0.7",
        "TEEBOTUS_LLM_SERVICE_TIER_DEPRESSIONSBOT": "flex",
    }

    assert resolve_llm_setting("Depressionsbot", "signal", 2, "PROVIDER", env) == "groq"
    assert resolve_llm_setting("Depressionsbot", "telegram", 1, "ENABLED", env) == "false"
    assert resolve_llm_setting("Depressionsbot", "signal", 1, "PROVIDER", env) == "huggingface"
    assert resolve_llm_setting("Depressionsbot", "telegram", 1, "PROVIDER", env) == "ollama"
    assert resolve_llm_setting("Depressionsbot", "telegram", 1, "MODEL", env) == "llama3.1:8b"
    assert resolve_llm_setting("Depressionsbot", "telegram", 1, "FALLBACK_MODELS", env) == "groq/llama-3.3-70b-versatile,openai/gpt-4.1-mini"
    assert resolve_llm_setting("Depressionsbot", "signal", 1, "API_KEY", env) == "signal-key"
    assert resolve_llm_setting("Depressionsbot", "matrix", 1, "API_KEY", env) == "global-key"
    assert resolve_llm_setting("Depressionsbot", "telegram", 1, "BASE_URL", env) == "http://localhost:11434"
    assert resolve_llm_setting("Depressionsbot", "telegram", 1, "PROFILE", env) == "local_ollama"
    assert resolve_llm_setting("Depressionsbot", "telegram", 1, "PURPOSE", env) == "structured_decision"
    assert resolve_llm_setting("Depressionsbot", "signal", 1, "ALLOW_REMOTE_FALLBACK", env) == "yes"
    assert resolve_llm_setting("Depressionsbot", "telegram", 1, "TIMEOUT_SECONDS", env) == "180"
    assert resolve_llm_setting("Depressionsbot", "telegram", 1, "MAX_OUTPUT_TOKENS", env) == "700"
    assert resolve_llm_setting("Depressionsbot", "telegram", 1, "TEMPERATURE", env) == "0.7"


def test_signal_account_resolution_pairs_services_and_numbers():
    env = {
        "SIGNAL_BOT_SERVICES_DEPRESSIONSBOT": "127.0.0.1:8080,127.0.0.1:8081",
        "SIGNAL_BOT_PHONE_NUMBERS_DEPRESSIONSBOT": "+491,+492",
    }

    assert resolve_signal_accounts("Depressionsbot", env) == (("127.0.0.1:8080", "+491"), ("127.0.0.1:8081", "+492"))


def test_matrix_account_resolution_pairs_homeserver_user_and_token():
    env = {
        "MATRIX_BOT_HOMESERVERS_DEPRESSIONSBOT": "https://matrix-a.example,https://matrix-b.example",
        "MATRIX_BOT_USER_IDS_DEPRESSIONSBOT": "@a:example,@b:example",
        "MATRIX_BOT_ACCESS_TOKENS_DEPRESSIONSBOT": "token-a,token-b",
        "MATRIX_BOT_DEVICE_IDS_DEPRESSIONSBOT": "dev-a,dev-b",
    }

    assert resolve_matrix_accounts("Depressionsbot", env) == (
        ("https://matrix-a.example", "@a:example", "token-a", "dev-a"),
        ("https://matrix-b.example", "@b:example", "token-b", "dev-b"),
    )


def test_build_account_configs_for_telegram_signal_and_matrix():
    env = {
        "TELEGRAM_BOT_TOKEN_DEPRESSIONSBOT": "telegram-token",
        "SIGNAL_BOT_SERVICE_DEPRESSIONSBOT": "127.0.0.1:8080",
        "SIGNAL_BOT_PHONE_NUMBER_DEPRESSIONSBOT": "+491",
        "MATRIX_BOT_HOMESERVER_DEPRESSIONSBOT": "https://matrix.example",
        "MATRIX_BOT_USER_ID_DEPRESSIONSBOT": "@bot:example",
        "MATRIX_BOT_ACCESS_TOKEN_DEPRESSIONSBOT": "matrix-token",
        "OPENAI_API_KEY_DEPRESSIONSBOT": "sk-shared",
        "TEEBOTUS_LLM_ENABLED_DEPRESSIONSBOT": "false",
        "TEEBOTUS_LLM_PROVIDER_DEPRESSIONSBOT": "ollama",
        "TEEBOTUS_LLM_MODEL_DEPRESSIONSBOT": "llama3.1:8b",
        "TEEBOTUS_LLM_FALLBACK_MODELS_DEPRESSIONSBOT": "groq/llama-3.3-70b-versatile,openai/gpt-4.1-mini",
        "TEEBOTUS_LLM_API_KEY_DEPRESSIONSBOT": "ollama-key",
        "TEEBOTUS_LLM_BASE_URL_DEPRESSIONSBOT": "http://localhost:11434",
        "TEEBOTUS_LLM_PROFILE_DEPRESSIONSBOT": "local_ollama",
        "TEEBOTUS_LLM_PURPOSE_DEPRESSIONSBOT": "structured_decision",
        "TEEBOTUS_LLM_ALLOW_REMOTE_FALLBACK_DEPRESSIONSBOT": "yes",
        "TEEBOTUS_LLM_TIMEOUT_SECONDS_DEPRESSIONSBOT": "180",
        "TEEBOTUS_LLM_MAX_OUTPUT_TOKENS_DEPRESSIONSBOT": "700",
        "TEEBOTUS_LLM_TEMPERATURE_DEPRESSIONSBOT": "0.7",
        "TEEBOTUS_LLM_SERVICE_TIER_DEPRESSIONSBOT": "flex",
    }

    accounts = build_account_run_configs("Depressionsbot", ("telegram", "signal", "matrix"), env)

    assert [account.channel for account in accounts] == ["telegram", "signal", "matrix"]
    assert {account.openai_api_key for account in accounts} == {"sk-shared"}
    assert {account.llm_enabled for account in accounts} == {"false"}
    assert {account.llm_provider for account in accounts} == {"ollama"}
    assert {account.llm_model for account in accounts} == {"llama3.1:8b"}
    assert {account.llm_fallback_models for account in accounts} == {"groq/llama-3.3-70b-versatile,openai/gpt-4.1-mini"}
    assert {account.llm_api_key for account in accounts} == {"ollama-key"}
    assert {account.llm_base_url for account in accounts} == {"http://localhost:11434"}
    assert {account.llm_profile for account in accounts} == {"local_ollama"}
    assert {account.llm_purpose for account in accounts} == {"structured_decision"}
    assert {account.llm_allow_remote_fallback for account in accounts} == {"yes"}
    assert {account.llm_timeout_seconds for account in accounts} == {"180"}
    assert {account.llm_max_output_tokens for account in accounts} == {"700"}
    assert {account.llm_temperature for account in accounts} == {"0.7"}
    assert {account.llm_service_tier for account in accounts} == {"flex"}


def test_runtime_discovers_instances(tmp_path: Path):
    (tmp_path / "Depressionsbot").mkdir()
    (tmp_path / "Depressionsbot" / "Bot_Verhalten.md").write_text("# Bot", encoding="utf-8")
    env = {
        "TELEGRAM_BOT_INSTANCES_DIR": str(tmp_path),
        "TELEGRAM_BOT_TOKEN_DEPRESSIONSBOT": "token",
        "OPENAI_API_KEY_DEPRESSIONSBOT": "sk",
    }

    config = build_runtime_config(env, cli_channels="telegram")

    assert config.selected_instances == ("Depressionsbot",)
    assert config.instances[0].accounts[0].telegram_token == "token"


def test_teebotus_instance_takes_precedence_over_telegram_bot_instance(tmp_path: Path):
    selected = resolve_selected_instances(
        tmp_path,
        {"TEEBOTUS_INSTANCE": "NewBot", "TELEGRAM_BOT_INSTANCE": "OldBot"},
    )

    assert selected == ("NewBot",)


def test_signal_single_service_and_phone_must_be_configured_together():
    env = {"SIGNAL_BOT_PHONE_NUMBER_DEPRESSIONSBOT": "+491"}

    with pytest.raises(RuntimeConfigError):
        resolve_signal_accounts("Depressionsbot", env)


def test_duplicate_telegram_tokens_raise_instead_of_collapsing_slots():
    env = {"TELEGRAM_BOT_TOKENS_DEPRESSIONSBOT": "same,same"}

    with pytest.raises(RuntimeConfigError):
        resolve_telegram_tokens("Depressionsbot", env)


def test_duplicate_signal_phone_numbers_raise_instead_of_collapsing_slots():
    env = {
        "SIGNAL_BOT_SERVICES_DEPRESSIONSBOT": "svc-a,svc-b",
        "SIGNAL_BOT_PHONE_NUMBERS_DEPRESSIONSBOT": "+491,+491",
    }

    with pytest.raises(RuntimeConfigError):
        resolve_signal_accounts("Depressionsbot", env)


def test_duplicate_signal_services_raise_instead_of_collapsing_slots():
    env = {
        "SIGNAL_BOT_SERVICES_DEPRESSIONSBOT": "svc-a,svc-a",
        "SIGNAL_BOT_PHONE_NUMBERS_DEPRESSIONSBOT": "+491,+492",
    }

    with pytest.raises(RuntimeConfigError):
        resolve_signal_accounts("Depressionsbot", env)


def test_matrix_single_config_requires_homeserver_user_and_token():
    env = {"MATRIX_BOT_USER_ID_DEPRESSIONSBOT": "@bot:example"}

    with pytest.raises(RuntimeConfigError):
        resolve_matrix_accounts("Depressionsbot", env)


def test_duplicate_matrix_user_ids_raise_instead_of_collapsing_slots():
    env = {
        "MATRIX_BOT_HOMESERVERS_DEPRESSIONSBOT": "https://a.example,https://b.example",
        "MATRIX_BOT_USER_IDS_DEPRESSIONSBOT": "@bot:example,@bot:example",
        "MATRIX_BOT_ACCESS_TOKENS_DEPRESSIONSBOT": "token-a,token-b",
    }

    with pytest.raises(RuntimeConfigError):
        resolve_matrix_accounts("Depressionsbot", env)
