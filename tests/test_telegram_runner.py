from __future__ import annotations

from pathlib import Path

import pytest

from TeeBotus.runtime.config import AccountRunConfig, InstanceRunConfig, RuntimeConfig
from TeeBotus.runtime.telegram_runner import (
    TelegramRuntimeError,
    build_telegram_instance_configs,
    check_telegram_accounts,
    run_telegram_accounts,
)


def test_build_telegram_instance_configs_filters_and_maps_runtime_slots(tmp_path: Path) -> None:
    config = RuntimeConfig(
        instances_dir=tmp_path,
        selected_instances=("Demo",),
        channels=("telegram", "signal"),
        instances=(
            InstanceRunConfig(
                instance_name="Demo",
                instruction_path=tmp_path / "Demo" / "Bot_Verhalten.md",
                accounts=(
                    AccountRunConfig(
                        instance_name="Demo",
                        channel="telegram",
                        slot=1,
                        label="telegram:1",
                        telegram_token="telegram-token",
                        openai_api_key="sk-demo",
                    ),
                    AccountRunConfig(
                        instance_name="Demo",
                        channel="signal",
                        slot=1,
                        label="signal:1",
                        signal_service="127.0.0.1:8080",
                        signal_phone_number="+491234",
                        openai_api_key="sk-signal",
                    ),
                ),
            ),
        ),
    )

    instance_configs = build_telegram_instance_configs(config)

    assert len(instance_configs) == 1
    assert instance_configs[0].instance_name == "Demo"
    assert instance_configs[0].instruction_path == str(tmp_path / "Demo" / "Bot_Verhalten.md")
    assert instance_configs[0].token_configs[0].label == "telegram:1"
    assert instance_configs[0].token_configs[0].token == "telegram-token"
    assert instance_configs[0].token_configs[0].openai_api_key == "sk-demo"


def test_run_telegram_accounts_rejects_missing_slots(tmp_path: Path) -> None:
    config = RuntimeConfig(
        instances_dir=tmp_path,
        selected_instances=("Demo",),
        channels=("telegram",),
        instances=(
            InstanceRunConfig(
                instance_name="Demo",
                instruction_path=tmp_path / "Demo" / "Bot_Verhalten.md",
                accounts=(),
            ),
        ),
    )

    with pytest.raises(TelegramRuntimeError, match="kein TELEGRAM_BOT_TOKEN"):
        run_telegram_accounts(config)


def test_check_telegram_accounts_reports_duplicate_tokens_without_leaking_secret(tmp_path: Path) -> None:
    config = RuntimeConfig(
        instances_dir=tmp_path,
        selected_instances=("DemoA", "DemoB"),
        channels=("telegram",),
        instances=(
            InstanceRunConfig(
                instance_name="DemoA",
                instruction_path=tmp_path / "DemoA" / "Bot_Verhalten.md",
                accounts=(
                    AccountRunConfig(
                        instance_name="DemoA",
                        channel="telegram",
                        slot=1,
                        label="telegram:1",
                        telegram_token="same-token-secret",
                        openai_api_key="",
                    ),
                ),
            ),
            InstanceRunConfig(
                instance_name="DemoB",
                instruction_path=tmp_path / "DemoB" / "Bot_Verhalten.md",
                accounts=(
                    AccountRunConfig(
                        instance_name="DemoB",
                        channel="telegram",
                        slot=1,
                        label="telegram:1",
                        telegram_token="same-token-secret",
                        openai_api_key="",
                    ),
                ),
            ),
        ),
    )

    health = check_telegram_accounts(config)

    assert health[0].ok is True
    assert health[1].ok is False
    assert health[1].error == "duplicate token with DemoA/telegram:1"
    assert "same-token-secret" not in health[1].error


def test_run_telegram_accounts_rejects_duplicate_tokens_across_instances(tmp_path: Path) -> None:
    config = RuntimeConfig(
        instances_dir=tmp_path,
        selected_instances=("DemoA", "DemoB"),
        channels=("telegram",),
        instances=(
            InstanceRunConfig(
                instance_name="DemoA",
                instruction_path=tmp_path / "DemoA" / "Bot_Verhalten.md",
                accounts=(
                    AccountRunConfig(
                        instance_name="DemoA",
                        channel="telegram",
                        slot=1,
                        label="telegram:1",
                        telegram_token="same-token",
                        openai_api_key="",
                    ),
                ),
            ),
            InstanceRunConfig(
                instance_name="DemoB",
                instruction_path=tmp_path / "DemoB" / "Bot_Verhalten.md",
                accounts=(
                    AccountRunConfig(
                        instance_name="DemoB",
                        channel="telegram",
                        slot=1,
                        label="telegram:1",
                        telegram_token="same-token",
                        openai_api_key="",
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(TelegramRuntimeError, match="Duplicate Telegram bot token"):
        run_telegram_accounts(config)
