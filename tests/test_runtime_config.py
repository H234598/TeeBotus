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
    resolve_signal_accounts,
    resolve_telegram_tokens,
)


def test_channels_default_to_telegram_and_signal():
    assert resolve_channels({}) == ("telegram", "signal")
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


def test_signal_account_resolution_pairs_services_and_numbers():
    env = {
        "SIGNAL_BOT_SERVICES_DEPRESSIONSBOT": "127.0.0.1:8080,127.0.0.1:8081",
        "SIGNAL_BOT_PHONE_NUMBERS_DEPRESSIONSBOT": "+491,+492",
    }

    assert resolve_signal_accounts("Depressionsbot", env) == (("127.0.0.1:8080", "+491"), ("127.0.0.1:8081", "+492"))


def test_build_account_configs_for_telegram_and_signal():
    env = {
        "TELEGRAM_BOT_TOKEN_DEPRESSIONSBOT": "telegram-token",
        "SIGNAL_BOT_SERVICE_DEPRESSIONSBOT": "127.0.0.1:8080",
        "SIGNAL_BOT_PHONE_NUMBER_DEPRESSIONSBOT": "+491",
        "OPENAI_API_KEY_DEPRESSIONSBOT": "sk-shared",
    }

    accounts = build_account_run_configs("Depressionsbot", ("telegram", "signal"), env)

    assert [account.channel for account in accounts] == ["telegram", "signal"]
    assert {account.openai_api_key for account in accounts} == {"sk-shared"}


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
