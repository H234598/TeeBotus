from __future__ import annotations

from pathlib import Path

import pytest

from TeeBotus.runtime.config import (
    RuntimeConfigError,
    build_account_run_configs,
    build_runtime_config,
    resolve_channels,
    resolve_instances_dir,
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


def test_runtime_config_marks_only_concrete_channel_selection_as_explicit(tmp_path: Path):
    (tmp_path / "Depressionsbot").mkdir()
    (tmp_path / "Depressionsbot" / "Bot_Verhalten.md").write_text("# Bot", encoding="utf-8")
    base_env = {
        "TELEGRAM_BOT_INSTANCES_DIR": str(tmp_path),
        "TEEBOTUS_INSTANCE": "Depressionsbot",
        "TELEGRAM_BOT_TOKEN_DEPRESSIONSBOT": "telegram-token",
    }

    assert build_runtime_config(base_env).channels_explicit is False
    assert build_runtime_config({**base_env, "TEEBOTUS_CHANNELS": "auto"}).channels_explicit is False
    assert build_runtime_config(base_env, cli_channels="all").channels_explicit is False
    assert build_runtime_config({**base_env, "TEEBOTUS_CHANNELS": "telegram,signal"}).channels_explicit is True
    assert build_runtime_config(base_env, cli_channels="telegram").channels_explicit is True


def test_telegram_token_resolution_merges_plural_single_and_numbered_instance_values():
    env = {
        "TELEGRAM_BOT_TOKENS_DEPRESSIONSBOT": "token-a, token-b",
        "TELEGRAM_BOT_TOKEN_DEPRESSIONSBOT_3": "token-c",
        "TELEGRAM_BOT_TOKEN": "global-token",
    }

    assert resolve_telegram_tokens("Depressionsbot", env) == ("token-a", "token-b", "token-c")


def test_telegram_token_resolution_rejects_numbered_slot_conflict():
    env = {
        "TELEGRAM_BOT_TOKENS_DEPRESSIONSBOT": "token-a, token-b",
        "TELEGRAM_BOT_TOKEN_DEPRESSIONSBOT_2": "token-c",
    }

    with pytest.raises(RuntimeConfigError, match="conflicts with already configured slot 2"):
        resolve_telegram_tokens("Depressionsbot", env)


def test_telegram_token_resolution_rejects_numbered_slot_gap():
    env = {
        "TELEGRAM_BOT_TOKEN_DEPRESSIONSBOT": "token-a",
        "TELEGRAM_BOT_TOKEN_DEPRESSIONSBOT_3": "token-c",
    }

    with pytest.raises(RuntimeConfigError, match="missing numbered slot"):
        resolve_telegram_tokens("Depressionsbot", env)


def test_telegram_token_resolution_rejects_numbered_slot_zero():
    env = {
        "TELEGRAM_BOT_TOKEN_DEPRESSIONSBOT": "token-a",
        "TELEGRAM_BOT_TOKEN_DEPRESSIONSBOT_0": "token-zero",
    }

    with pytest.raises(RuntimeConfigError, match="invalid slot number 0"):
        resolve_telegram_tokens("Depressionsbot", env)


def test_telegram_token_resolution_rejects_numbered_slot_leading_zero():
    env = {
        "TELEGRAM_BOT_TOKEN_DEPRESSIONSBOT": "token-a",
        "TELEGRAM_BOT_TOKEN_DEPRESSIONSBOT_02": "token-b",
    }

    with pytest.raises(RuntimeConfigError, match="remove leading zeroes"):
        resolve_telegram_tokens("Depressionsbot", env)


def test_telegram_token_resolution_rejects_empty_positional_token_slot():
    env = {"TELEGRAM_BOT_TOKENS_DEPRESSIONSBOT": "token-a,,token-c"}

    with pytest.raises(RuntimeConfigError, match="empty value in positional slot list TELEGRAM_BOT_TOKENS_DEPRESSIONSBOT"):
        resolve_telegram_tokens("Depressionsbot", env)


def test_telegram_token_resolution_supports_global_plural_fallback():
    env = {
        "TELEGRAM_BOT_TOKENS": "global-a, global-b",
    }

    assert resolve_telegram_tokens("Depressionsbot", env) == ("global-a", "global-b")


def test_duplicate_channels_raise_instead_of_starting_adapter_twice():
    with pytest.raises(RuntimeConfigError):
        resolve_channels({}, cli_channels="telegram,telegram")


def test_channels_reject_empty_list_items_instead_of_silently_shifting_selection():
    with pytest.raises(RuntimeConfigError, match="empty value in TEEBOTUS_CHANNELS"):
        resolve_channels({}, cli_channels="telegram,,signal")


def test_build_account_configs_normalizes_direct_channel_values():
    env = {
        "TELEGRAM_BOT_TOKEN_DEPRESSIONSBOT": "telegram-token",
        "OPENAI_API_KEY_DEPRESSIONSBOT": "sk-shared",
    }

    accounts = build_account_run_configs("Depressionsbot", (" Telegram ",), env)

    assert [account.channel for account in accounts] == ["telegram"]


def test_build_account_configs_rejects_unknown_direct_channel():
    with pytest.raises(RuntimeConfigError, match="unsupported channel"):
        build_account_run_configs("Depressionsbot", ("irc",), {})


def test_build_account_configs_rejects_empty_direct_channel_sequence():
    with pytest.raises(RuntimeConfigError, match="must include at least one channel"):
        build_account_run_configs("Depressionsbot", (), {})


def test_build_account_configs_rejects_duplicate_direct_channels():
    with pytest.raises(RuntimeConfigError, match="duplicate values in runtime channels"):
        build_account_run_configs("Depressionsbot", ("telegram", " Telegram "), {})


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


def test_openai_key_resolution_skips_blank_direct_key_and_strips_value():
    env = {
        "OPENAI_API_KEY_DEPRESSIONSBOT_TELEGRAM_1": " ",
        "OPENAI_API_KEY_DEPRESSIONSBOT_TELEGRAM": " sk-channel ",
        "OPENAI_API_KEY_DEPRESSIONSBOT": "sk-instance",
    }

    assert resolve_openai_key("Depressionsbot", "telegram", 1, env) == "sk-channel"


def test_openai_key_resolution_accepts_channel_wide_key_before_instance_slot_key():
    env = {
        "OPENAI_API_KEY_DEPRESSIONSBOT_SIGNAL": "sk-signal-channel",
        "OPENAI_API_KEY_DEPRESSIONSBOT_1": "sk-instance-slot",
    }

    assert resolve_openai_key("Depressionsbot", "signal", 1, env) == "sk-signal-channel"


def test_openai_key_resolution_uses_background_key_only_for_non_user_channels():
    env = {
        "Depressionsbot_BACKGROUND_SERVICES": "sk-background",
        "Bot_der_Wahrheit_BACKGROUND_SERVICES": "sk-other-background",
        "OPENAI_API_KEY_DEPRESSIONSBOT": "sk-instance",
    }

    assert resolve_openai_key("Depressionsbot", "proactive", 1, env) == "sk-background"
    assert resolve_openai_key("Depressionsbot", "telegram", 1, env) == "sk-instance"
    assert resolve_openai_key("Bot_der_Wahrheit", "proactive", 1, env) == ""


def test_openai_key_resolution_strips_background_services_key():
    env = {
        "Depressionsbot_BACKGROUND_SERVICES": " sk-background ",
    }

    assert resolve_openai_key("Depressionsbot", "proactive", 1, env) == "sk-background"


def test_openai_key_resolution_ignores_global_background_key():
    env = {"OPENAI_API_KEY_BACKGROUND": "sk-global-background"}

    assert resolve_openai_key("Depressionsbot", "proactive", 1, env) == ""


def test_openai_key_resolution_ignores_global_proactive_key():
    env = {"OPENAI_API_KEY_PROACTIVE": "sk-global-proactive"}

    assert resolve_openai_key("Depressionsbot", "proactive", 1, env) == ""


def test_openai_key_resolution_ignores_legacy_instance_background_key():
    env = {
        "OPENAI_API_KEY_DEPRESSIONSBOT_BACKGROUND_2": "sk-legacy-background-slot",
        "OPENAI_API_KEY_DEPRESSIONSBOT_BACKGROUND": "sk-legacy-background",
        "OPENAI_API_KEYS_DEPRESSIONSBOT_BACKGROUND": "sk-legacy-background-a, sk-legacy-background-b",
    }

    assert resolve_openai_key("Depressionsbot", "proactive", 1, env) == ""
    assert resolve_openai_key("Depressionsbot", "background", 2, env) == ""


def test_openai_key_resolution_prefers_proactive_key_before_background_key():
    env = {
        "OPENAI_API_KEY_DEPRESSIONSBOT_PROACTIVE": "sk-proactive",
        "Depressionsbot_BACKGROUND_SERVICES": "sk-background",
        "OPENAI_API_KEY_DEPRESSIONSBOT": "sk-instance",
    }

    assert resolve_openai_key("Depressionsbot", "proactive", 1, env) == "sk-proactive"


def test_openai_key_resolution_ignores_generic_background_services_aliases():
    env = {
        "DEPRESSIONSBOT_BACKGROUND_SERVICES": "sk-token-alias",
        "OPENAI_API_KEY_DEPRESSIONSBOT_BACKGROUND_SERVICES_2": "sk-background-slot",
        "OPENAI_API_KEYS_DEPRESSIONSBOT_BACKGROUND_SERVICES": "sk-background-a, sk-background-b",
        "OPENAI_API_KEY_DEPRESSIONSBOT_BACKGROUND_SERVICES": "sk-background-single",
    }

    assert resolve_openai_key("Depressionsbot", "proactive", 1, env) == ""
    assert resolve_openai_key("Depressionsbot", "background", 2, env) == ""


def test_openai_key_resolution_background_services_single_key_is_shared_across_slots():
    env = {
        "Depressionsbot_BACKGROUND_SERVICES": "sk-background",
    }

    assert resolve_openai_key("Depressionsbot", "background", 2, env) == "sk-background"


def test_openai_key_resolution_background_services_is_depressionsbot_only():
    env = {
        "Depressionsbot_BACKGROUND_SERVICES": "sk-background",
        "Bot_der_Wahrheit_BACKGROUND_SERVICES": "sk-other-background",
    }

    assert resolve_openai_key("Bot_der_Wahrheit", "proactive", 1, env) == ""


def test_openai_key_resolution_rejects_empty_positional_key_slot():
    env = {"OPENAI_API_KEYS_DEPRESSIONSBOT": "key-a,,key-c"}

    with pytest.raises(RuntimeConfigError, match="empty value in positional slot list OPENAI_API_KEYS_DEPRESSIONSBOT"):
        resolve_openai_key("Depressionsbot", "telegram", 2, env)


def test_openai_key_resolution_rejects_invalid_direct_slot_number():
    env = {
        "OPENAI_API_KEY_DEPRESSIONSBOT_0": "sk-zero",
        "OPENAI_API_KEY_DEPRESSIONSBOT_-1": "sk-minus",
        "OPENAI_API_KEY_DEPRESSIONSBOT": "sk-fallback",
    }

    with pytest.raises(RuntimeConfigError, match="OpenAI key slot must be >= 1"):
        resolve_openai_key("Depressionsbot", "telegram", 0, env)
    with pytest.raises(RuntimeConfigError, match="OpenAI key slot must be >= 1"):
        resolve_openai_key("Depressionsbot", "telegram", -1, env)


def test_openai_key_resolution_rejects_unknown_direct_channel():
    with pytest.raises(RuntimeConfigError, match="unsupported OpenAI key channel"):
        resolve_openai_key("Depressionsbot", "irc", 1, {"OPENAI_API_KEY_DEPRESSIONSBOT": "sk-fallback"})


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


def test_llm_setting_resolution_rejects_invalid_direct_channel_and_slot() -> None:
    env = {"TEEBOTUS_LLM_PROVIDER_DEPRESSIONSBOT": "ollama"}

    with pytest.raises(RuntimeConfigError, match="unsupported channel"):
        resolve_llm_setting("Depressionsbot", "irc", 1, "PROVIDER", env)
    with pytest.raises(RuntimeConfigError, match="LLM runtime slot must be >= 1"):
        resolve_llm_setting("Depressionsbot", "telegram", 0, "PROVIDER", env)


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


def test_build_account_configs_rejects_multi_telegram_without_matching_openai_keys():
    env = {
        "TELEGRAM_BOT_TOKENS_DEPRESSIONSBOT": "token-a, token-b",
    }

    with pytest.raises(RuntimeConfigError, match="Missing OpenAI API key.*1, 2"):
        build_account_run_configs("Depressionsbot", ("telegram",), env)


def test_build_account_configs_rejects_multi_telegram_shared_openai_key():
    env = {
        "TELEGRAM_BOT_TOKENS_DEPRESSIONSBOT": "token-a, token-b",
        "OPENAI_API_KEY_DEPRESSIONSBOT": "shared-key",
    }

    with pytest.raises(RuntimeConfigError, match="must not share the same OpenAI API key"):
        build_account_run_configs("Depressionsbot", ("telegram",), env)


def test_build_account_configs_accepts_multi_telegram_with_matching_openai_key_slots():
    env = {
        "TELEGRAM_BOT_TOKENS_DEPRESSIONSBOT": "token-a, token-b",
        "TELEGRAM_BOT_TOKEN_DEPRESSIONSBOT_3": "token-c",
        "OPENAI_API_KEYS_DEPRESSIONSBOT": "key-a, key-b",
        "OPENAI_API_KEY_DEPRESSIONSBOT_3": "key-c",
    }

    accounts = build_account_run_configs("Depressionsbot", ("telegram",), env)

    assert [(account.slot, account.telegram_token, account.openai_api_key) for account in accounts] == [
        (1, "token-a", "key-a"),
        (2, "token-b", "key-b"),
        (3, "token-c", "key-c"),
    ]


def test_build_account_configs_accepts_base_and_numbered_telegram_slots():
    env = {
        "TELEGRAM_BOT_TOKEN_DEPRESSIONSBOT": "token-a",
        "TELEGRAM_BOT_TOKEN_DEPRESSIONSBOT_2": "token-b",
        "OPENAI_API_KEY_DEPRESSIONSBOT": "key-a",
        "OPENAI_API_KEY_DEPRESSIONSBOT_2": "key-b",
    }

    accounts = build_account_run_configs("Depressionsbot", ("telegram",), env)

    assert [(account.slot, account.telegram_token, account.openai_api_key) for account in accounts] == [
        (1, "token-a", "key-a"),
        (2, "token-b", "key-b"),
    ]


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


def test_instances_dir_resolution_strips_whitespace_and_uses_first_nonempty_value(tmp_path: Path):
    fallback = tmp_path / "fallback"
    explicit = tmp_path / "explicit"

    assert resolve_instances_dir({"TEEBOTUS_INSTANCES_DIR": f" {explicit} "}) == explicit
    assert resolve_instances_dir({"TEEBOTUS_INSTANCES_DIR": " ", "TELEGRAM_BOT_INSTANCES_DIR": f" {fallback} "}) == fallback


def test_plural_instances_all_requests_runtime_discovery(tmp_path: Path):
    for name in ("Bote_der_Wahrheit", "Depressionsbot"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "Bot_Verhalten.md").write_text("# Bot", encoding="utf-8")

    assert resolve_selected_instances(tmp_path, {"TEEBOTUS_INSTANCES": "all"}) == ("Bote_der_Wahrheit", "Depressionsbot")
    assert resolve_selected_instances(tmp_path, {"TELEGRAM_BOT_INSTANCES": "auto"}) == ("Bote_der_Wahrheit", "Depressionsbot")


def test_selected_instances_resolution_uses_first_nonempty_alias(tmp_path: Path):
    assert resolve_selected_instances(
        tmp_path,
        {"TEEBOTUS_INSTANCES": " ", "TELEGRAM_BOT_INSTANCES": "Depressionsbot"},
    ) == ("Depressionsbot",)
    assert resolve_selected_instances(
        tmp_path,
        {"TEEBOTUS_INSTANCE": " ", "TELEGRAM_BOT_INSTANCE": "Bote_der_Wahrheit"},
    ) == ("Bote_der_Wahrheit",)


def test_selected_instances_reject_empty_list_items(tmp_path: Path):
    with pytest.raises(RuntimeConfigError, match="empty value in TEEBOTUS_INSTANCES/TELEGRAM_BOT_INSTANCES"):
        resolve_selected_instances(tmp_path, {"TEEBOTUS_INSTANCES": "Depressionsbot,,Bote_der_Wahrheit"})


def test_selected_instances_reject_duplicate_names(tmp_path: Path):
    with pytest.raises(RuntimeConfigError, match="duplicate values in TEEBOTUS_INSTANCES/TELEGRAM_BOT_INSTANCES"):
        resolve_selected_instances(tmp_path, {"TEEBOTUS_INSTANCES": "Depressionsbot,Depressionsbot"})


def test_single_instance_alias_rejects_comma_separated_values(tmp_path: Path):
    with pytest.raises(RuntimeConfigError, match="accepts one instance only"):
        resolve_selected_instances(tmp_path, {"TEEBOTUS_INSTANCE": "Depressionsbot,Bote_der_Wahrheit"})


def test_plural_instances_cannot_mix_discovery_token_with_explicit_names(tmp_path: Path):
    with pytest.raises(RuntimeConfigError, match="cannot combine all/auto"):
        resolve_selected_instances(tmp_path, {"TEEBOTUS_INSTANCES": "all,Depressionsbot"})


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


def test_matrix_single_device_id_requires_complete_single_config():
    env = {"MATRIX_BOT_DEVICE_ID_DEPRESSIONSBOT": "TEEBOTUS"}

    with pytest.raises(RuntimeConfigError, match="device_id requires homeserver/user/access_token"):
        resolve_matrix_accounts("Depressionsbot", env)


def test_duplicate_matrix_user_ids_raise_instead_of_collapsing_slots():
    env = {
        "MATRIX_BOT_HOMESERVERS_DEPRESSIONSBOT": "https://a.example,https://b.example",
        "MATRIX_BOT_USER_IDS_DEPRESSIONSBOT": "@bot:example,@bot:example",
        "MATRIX_BOT_ACCESS_TOKENS_DEPRESSIONSBOT": "token-a,token-b",
    }

    with pytest.raises(RuntimeConfigError):
        resolve_matrix_accounts("Depressionsbot", env)


def test_matrix_account_resolution_rejects_empty_positional_token_slot():
    env = {
        "MATRIX_BOT_HOMESERVERS_DEPRESSIONSBOT": "https://a.example,https://b.example,https://c.example",
        "MATRIX_BOT_USER_IDS_DEPRESSIONSBOT": "@a:example,@b:example,@c:example",
        "MATRIX_BOT_ACCESS_TOKENS_DEPRESSIONSBOT": "token-a,,token-c",
    }

    with pytest.raises(RuntimeConfigError, match="empty value in positional slot list MATRIX_BOT_ACCESS_TOKENS_DEPRESSIONSBOT"):
        resolve_matrix_accounts("Depressionsbot", env)
