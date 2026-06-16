from __future__ import annotations

from pathlib import Path

import pytest

from TeeBotus.adapters.telegram_runtime import BotIdentity
from TeeBotus.runtime.config import AccountRunConfig, InstanceRunConfig, RuntimeConfig
from TeeBotus.runtime.accounts import StaticSecretProvider
from TeeBotus.runtime import telegram_runner
from TeeBotus.runtime.telegram_runner import (
    TelegramRuntimeBridge,
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


def test_telegram_runtime_bridge_builds_modern_context(monkeypatch, tmp_path: Path) -> None:
    instance_dir = tmp_path / "Demo"
    instance_dir.mkdir()
    (instance_dir / "Bot_Verhalten.md").write_text("# Demo\n", encoding="utf-8")
    monkeypatch.setattr(telegram_runner.BibliothekarService, "from_instructions", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(telegram_runner, "build_runtime_text_llm_client", lambda **_kwargs: "llm-client")

    bridge = TelegramRuntimeBridge(
        run_config=AccountRunConfig(
            instance_name="Demo",
            channel="telegram",
            slot=2,
            label="telegram:2",
            telegram_token="telegram-token",
            openai_api_key="",
            llm_provider="ollama",
            llm_model="llama3.1:8b",
        ),
        api=object(),
        instances_dir=tmp_path,
        secret_provider=StaticSecretProvider(b"t" * 32),
        bot_identity=BotIdentity(first_name="DemoBot", username="demo_bot"),
    )

    assert bridge.context.instance_name == "Demo"
    assert bridge.context.adapter_slot == 2
    assert bridge.context.engine.llm_client == "llm-client"
    assert bridge.context.bot_identity.mention == "@demo_bot"
    assert bridge.account_store.instance_name == "Demo"


def test_run_telegram_accounts_uses_runtime_bridges_instead_of_polling_all(monkeypatch, tmp_path: Path) -> None:
    events: list[tuple[str, object]] = []

    class FakeJobRunner:
        def shutdown(self, *, wait: bool = False) -> None:
            events.append(("shutdown", wait))

    class FakeBridge:
        def __init__(self, *, run_config, api, instances_dir, youtube_job_runner, **_kwargs):  # noqa: ANN001 - fake mirrors runtime bridge signature.
            events.append(("bridge", (run_config.instance_name, run_config.label, Path(instances_dir), bool(youtube_job_runner))))

        def run_polling(self, *, stop_event, poll_timeout, youtube_job_runner):  # noqa: ANN001 - fake mirrors runtime bridge signature.
            events.append(("poll", (stop_event.is_set(), poll_timeout, bool(youtube_job_runner))))

    config = RuntimeConfig(
        instances_dir=tmp_path,
        selected_instances=("Demo",),
        channels=("telegram",),
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
                        openai_api_key="",
                    ),
                ),
            ),
        ),
    )
    monkeypatch.setattr(telegram_runner, "TelegramRuntimeBridge", FakeBridge)
    monkeypatch.setattr(telegram_runner.telegram_runtime, "YouTubeTranscriptionJobRunner", FakeJobRunner)
    monkeypatch.setattr(
        telegram_runner.telegram_runtime,
        "_notify_recent_users_for_current_version",
        lambda instance_configs: events.append(("notify", len(instance_configs))),
    )
    monkeypatch.setattr(
        telegram_runner.telegram_runtime,
        "run_polling_all",
        lambda _instance_configs: (_ for _ in ()).throw(AssertionError("old polling shortcut used")),
    )

    assert run_telegram_accounts(config) == 0

    assert ("notify", 1) in events
    assert ("bridge", ("Demo", "telegram:1", tmp_path, True)) in events
    assert ("poll", (False, telegram_runner.telegram_runtime.MULTI_BOT_POLL_TIMEOUT_SECONDS, True)) in events
    assert ("shutdown", False) in events


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
