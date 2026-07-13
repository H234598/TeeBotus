from __future__ import annotations

from pathlib import Path

import pytest

from TeeBotus.adapters.telegram_runtime import BotIdentity
from TeeBotus.runtime.config import AccountRunConfig, InstanceRunConfig, RuntimeConfig
from TeeBotus.runtime.accounts import StaticSecretProvider
from TeeBotus.runtime import telegram_runner
from TeeBotus.runtime.telegram_runner import (
    TelegramPollingTransport,
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
    decision_kwargs = []
    monkeypatch.setattr(telegram_runner.BibliothekarService, "from_instructions", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(telegram_runner, "build_runtime_text_llm_client", lambda **_kwargs: "llm-client")

    def fake_decision_runner(**kwargs):
        decision_kwargs.append(kwargs)
        return "decision-runner"

    monkeypatch.setattr(telegram_runner, "build_runtime_structured_decision_runner", fake_decision_runner)

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
    assert bridge.context.engine.structured_decision_runner == "decision-runner"
    assert decision_kwargs and decision_kwargs[0]["instructions"] is bridge.instruction_store.get()
    assert bridge.context.bot_identity.mention == "@demo_bot"
    assert bridge.account_store.instance_name == "Demo"
    assert bridge.chat_state.teladi_call_state_path == tmp_path / "Demo" / "data" / "Teladi_Emergency_State.json"


def test_telegram_runtime_bridge_retries_missing_identity_before_polling(monkeypatch, tmp_path: Path) -> None:
    instance_dir = tmp_path / "Demo"
    instance_dir.mkdir()
    (instance_dir / "Bot_Verhalten.md").write_text("# Demo\n", encoding="utf-8")
    monkeypatch.setattr(telegram_runner.BibliothekarService, "from_instructions", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(telegram_runner, "build_runtime_text_llm_client", lambda **_kwargs: "llm-client")
    monkeypatch.setattr(telegram_runner, "build_runtime_structured_decision_runner", lambda **_kwargs: "decision-runner")

    class API:
        token = "telegram-token"

        def __init__(self) -> None:
            self.get_me_calls = 0

        def get_me(self):
            self.get_me_calls += 1
            if self.get_me_calls == 1:
                raise telegram_runner.telegram_runtime.TelegramAPIError("temporary getMe failure")
            return BotIdentity(id=42, first_name="DemoBot", username="demo_bot")

    api = API()
    bridge = TelegramRuntimeBridge(
        run_config=AccountRunConfig(
            instance_name="Demo",
            channel="telegram",
            slot=1,
            label="telegram:1",
            telegram_token="telegram-token",
            openai_api_key="",
        ),
        api=api,
        instances_dir=tmp_path,
        secret_provider=StaticSecretProvider(b"t" * 32),
    )

    assert bridge.bot_identity.has_identity() is False
    bridge.refresh_bot_identity_if_missing()

    assert api.get_me_calls == 2
    assert bridge.bot_identity.username == "demo_bot"
    assert bridge.context.bot_identity.username == "demo_bot"
    assert "demobot" in bridge.context.engine.bot_address_names


def test_telegram_polling_transport_delegates_to_bridge() -> None:
    calls = []
    stop_event = object()
    job_runner = object()

    class FakeBridge:
        def run_polling(self, **kwargs):  # noqa: ANN001 - fake mirrors bridge run signature.
            calls.append(kwargs)

    transport = TelegramPollingTransport(
        bridge=FakeBridge(),  # type: ignore[arg-type]
        poll_timeout=12,
        youtube_job_runner=job_runner,
    )

    transport.run(stop_event=stop_event)  # type: ignore[arg-type]

    assert calls == [{"stop_event": stop_event, "poll_timeout": 12, "youtube_job_runner": job_runner}]


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
            stop_event.set()

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
        telegram_runner,
        "_notify_recent_users_for_current_version",
        lambda _config, instance_configs: events.append(("notify", len(instance_configs))),
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


def test_run_telegram_accounts_surfaces_polling_thread_failure(monkeypatch, tmp_path: Path) -> None:
    class FakeJobRunner:
        def shutdown(self, *, wait: bool = False) -> None:
            return None

    class FailingBridge:
        def __init__(self, **_kwargs):  # noqa: ANN001 - fake mirrors runtime bridge construction.
            return None

        def run_polling(self, **_kwargs):  # noqa: ANN001 - fake mirrors polling transport.
            raise RuntimeError("polling failed")

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
    monkeypatch.setattr(telegram_runner, "TelegramRuntimeBridge", FailingBridge)
    monkeypatch.setattr(telegram_runner.telegram_runtime, "YouTubeTranscriptionJobRunner", FakeJobRunner)
    monkeypatch.setattr(telegram_runner, "_notify_recent_users_for_current_version", lambda *_args: None)

    with pytest.raises(TelegramRuntimeError, match="telegram:1"):
        run_telegram_accounts(config)


def test_run_telegram_accounts_does_not_start_partial_threads_when_bridge_setup_fails(monkeypatch, tmp_path: Path) -> None:
    events: list[tuple[str, object]] = []

    class FakeJobRunner:
        def shutdown(self, *, wait: bool = False) -> None:
            events.append(("shutdown", wait))

    class FailingSecondBridge:
        def __init__(self, *, run_config, **_kwargs):  # noqa: ANN001 - fake mirrors runtime bridge signature.
            events.append(("bridge", run_config.label))
            if run_config.label == "telegram:2":
                raise RuntimeError("bridge setup failed")

        def run_polling(self, **_kwargs):  # noqa: ANN001 - fake mirrors runtime bridge signature.
            events.append(("poll", True))

    class FakeThread:
        def __init__(self, **_kwargs):  # noqa: ANN001 - fake mirrors threading.Thread signature.
            events.append(("thread", "created"))

        def start(self) -> None:
            events.append(("thread", "started"))

        def is_alive(self) -> bool:
            return False

        def join(self, timeout: float | None = None) -> None:
            events.append(("thread", timeout))

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
                        telegram_token="telegram-token-1",
                        openai_api_key="",
                    ),
                    AccountRunConfig(
                        instance_name="Demo",
                        channel="telegram",
                        slot=2,
                        label="telegram:2",
                        telegram_token="telegram-token-2",
                        openai_api_key="",
                    ),
                ),
            ),
        ),
    )
    monkeypatch.setattr(telegram_runner, "TelegramRuntimeBridge", FailingSecondBridge)
    monkeypatch.setattr(telegram_runner.threading, "Thread", FakeThread)
    monkeypatch.setattr(telegram_runner.telegram_runtime, "YouTubeTranscriptionJobRunner", FakeJobRunner)
    monkeypatch.setattr(telegram_runner, "_notify_recent_users_for_current_version", lambda _config, _instance_configs: None)

    with pytest.raises(RuntimeError, match="bridge setup failed"):
        run_telegram_accounts(config)

    assert ("bridge", "telegram:1") in events
    assert ("bridge", "telegram:2") in events
    assert not any(event[0] == "thread" for event in events)
    assert not any(event[0] == "poll" for event in events)
    assert ("shutdown", False) in events


def test_runtime_version_notifications_use_runtime_instances_dir(monkeypatch, tmp_path: Path) -> None:
    events = []
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

    class FakeAPI:
        def __init__(self, token: str) -> None:
            events.append(("api", token))

        def send_message(self, chat_id: str, text: str) -> int:
            events.append(("send", chat_id, text))
            return 1

    def fake_notify(**kwargs):  # noqa: ANN001 - mirrors notification helper kwargs.
        events.append(("notify", kwargs["instances_dir"], kwargs["instance_name"], kwargs["repo_root"], kwargs["adapter_slot"]))
        return 0

    monkeypatch.setattr(telegram_runner.telegram_runtime, "TelegramAPI", FakeAPI)
    monkeypatch.setattr(telegram_runner, "notify_recent_telegram_users_for_version", fake_notify)

    telegram_runner._notify_recent_users_for_current_version(config, build_telegram_instance_configs(config))

    assert ("api", "telegram-token") in events
    assert ("notify", tmp_path, "Demo", telegram_runner.telegram_runtime.PROJECT_ROOT, 1) in events


def test_runtime_version_notifications_use_matching_telegram_slot_token(monkeypatch, tmp_path: Path) -> None:
    events = []
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
                        telegram_token="telegram-token-1",
                        openai_api_key="",
                    ),
                    AccountRunConfig(
                        instance_name="Demo",
                        channel="telegram",
                        slot=2,
                        label="telegram:2",
                        telegram_token="telegram-token-2",
                        openai_api_key="",
                    ),
                ),
            ),
        ),
    )

    class FakeAPI:
        def __init__(self, token: str) -> None:
            self.token = token
            events.append(("api", token))

        def send_message(self, chat_id: str, text: str) -> int:
            events.append(("send", self.token, chat_id, text))
            return 1

    def fake_notify(**kwargs):  # noqa: ANN001 - mirrors notification helper kwargs.
        events.append(("notify", kwargs["adapter_slot"], kwargs["send_message"].__self__.token))
        return 0

    monkeypatch.setattr(telegram_runner.telegram_runtime, "TelegramAPI", FakeAPI)
    monkeypatch.setattr(telegram_runner, "notify_recent_telegram_users_for_version", fake_notify)

    telegram_runner._notify_recent_users_for_current_version(config, build_telegram_instance_configs(config))

    assert ("notify", 1, "telegram-token-1") in events
    assert ("notify", 2, "telegram-token-2") in events


def test_adapter_version_notifications_use_matching_telegram_slot_token(monkeypatch, tmp_path: Path) -> None:
    events = []

    class FakeAPI:
        def __init__(self, token: str) -> None:
            self.token = token
            events.append(("api", token))

        def send_message(self, chat_id: str, text: str) -> int:
            events.append(("send", self.token, chat_id, text))
            return 1

    class FakeStore:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003 - mirrors AccountStore construction.
            events.append(("store", args[1] if len(args) > 1 else ""))

    def fake_notify(**kwargs):  # noqa: ANN001 - mirrors notification helper kwargs.
        events.append(("notify", kwargs.get("adapter_slot"), kwargs["send_message"].__self__.token))
        return 0

    monkeypatch.setattr(telegram_runner.telegram_runtime, "_resolve_instances_dir", lambda: tmp_path)
    monkeypatch.setattr(telegram_runner.telegram_runtime, "TelegramAPI", FakeAPI)
    monkeypatch.setattr(telegram_runner.telegram_runtime, "AccountStore", FakeStore)
    monkeypatch.setattr(telegram_runner.telegram_runtime, "runtime_secret_provider", lambda: object())
    monkeypatch.setattr(telegram_runner.telegram_runtime, "notify_recent_telegram_users_for_version", fake_notify)

    instance_config = telegram_runner.telegram_runtime.InstanceRunConfig(
        "Demo",
        tmp_path / "Demo" / "Bot_Verhalten.md",
        (
            telegram_runner.telegram_runtime.BotTokenConfig("telegram:1", "telegram-token-1", ""),
            telegram_runner.telegram_runtime.BotTokenConfig("telegram:2", "telegram-token-2", ""),
        ),
    )

    telegram_runner.telegram_runtime._notify_recent_users_for_current_version([instance_config])

    assert ("notify", 1, "telegram-token-1") in events
    assert ("notify", 2, "telegram-token-2") in events


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
