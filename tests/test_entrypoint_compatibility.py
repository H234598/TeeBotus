from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace


def test_package_entrypoint_exists_and_delegates_to_bot_main() -> None:
    module = importlib.import_module("TeeBotus.__main__")
    bot = importlib.import_module("TeeBotus.bot")
    assert hasattr(module, "main")
    assert module.main is bot.main


def test_bot_main_is_callable() -> None:
    bot = importlib.import_module("TeeBotus.bot")
    assert callable(bot.main)


def test_version_flag_prints_package_version_without_runtime_start(monkeypatch, capsys) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    monkeypatch.setattr(bot, "_runtime_config_from_main_args", lambda _args: (_ for _ in ()).throw(AssertionError("runtime loaded")))
    monkeypatch.setattr(bot, "_load_telegram_main", lambda: (_ for _ in ()).throw(AssertionError("telegram loaded")))

    assert bot.main(["--version"]) == 0

    captured = capsys.readouterr()
    assert captured.out == "TeeBotus 1.4.28\n"
    assert captured.err == ""


def test_runtime_status_does_not_require_telegram_bot_start() -> None:
    bot = importlib.import_module("TeeBotus.bot")
    result = bot.main(["--runtime-status", "--channels", "telegram"])
    assert result == 0


def test_runtime_status_prints_account_memory_index_health(monkeypatch, capsys) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setattr(
        "TeeBotus.core.status.account_memory_index_health_lines",
        lambda *, instance_name, project_root: [f"account_memory={instance_name}/abc status=broken error=recent_ids missing entries: mem_missing"],
    )

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert "account_memory=Demo/abc status=broken error=recent_ids missing entries: mem_missing" in captured.out


def test_runtime_status_reports_local_transcription_health(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text(
        "## OpenAI\n- transcription_backend: local\n- local_transcription_model: tiny\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setattr("TeeBotus.core.local_transcription._has_python_module", lambda module: module == "faster_whisper")

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert "local_transcription=Demo backend=local model=tiny status=ready engine=faster-whisper" in captured.out


def test_runtime_status_reports_llm_provider_without_secrets(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text("# Bot\n", encoding="utf-8")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("TEEBOTUS_LLM_PROVIDER_DEMO", "litellm")
    monkeypatch.setenv("TEEBOTUS_LLM_MODEL_DEMO", "ollama_chat/llama3.1:8b")
    monkeypatch.setenv("TEEBOTUS_LLM_BASE_URL_DEMO", "http://user:secret@127.0.0.1:11434/api?token=nope")
    monkeypatch.setenv("TEEBOTUS_LLM_API_KEY_DEMO", "llm-secret")
    monkeypatch.setenv("TEEBOTUS_LLM_FALLBACK_MODELS_DEMO", "groq/llama-3.3-70b-versatile,openai/gpt-4.1-mini")

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert (
        "llm=Demo/telegram:1 provider=litellm model=ollama_chat/llama3.1:8b "
        "status=configured base_url=http://127.0.0.1:11434/api api_key=configured fallback_models=2"
    ) in captured.out
    assert "llm-secret" not in captured.out
    assert "user:secret" not in captured.out
    assert "token=nope" not in captured.out


def test_runtime_status_reports_missing_local_transcription_backend(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text(
        "## OpenAI\n- transcription_backend: local\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setattr("TeeBotus.core.local_transcription._has_python_module", lambda _module: False)
    monkeypatch.setattr("TeeBotus.core.local_transcription.shutil.which", lambda _binary: None)

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert "local_transcription=Demo backend=local model=tiny status=unavailable error=weder faster-whisper noch whisper ist lokal installiert" in captured.out


def test_runtime_status_loads_env_before_resolving_config(monkeypatch) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls: list[tuple[str, Path]] = []

    class TelegramModule:
        PROJECT_ROOT = Path("/tmp/teebotus-test-root")
        ALL_BOTS_DEFAULT_FILENAME = "ALL_BOTS_DEFAULT.md"

        @staticmethod
        def _load_dotenv(path: Path) -> None:
            calls.append(("dotenv", path))
            monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
            monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "token")

        @staticmethod
        def _load_runtime_config_defaults(path: Path) -> None:
            calls.append(("defaults", path))
            monkeypatch.setenv("OPENAI_API_KEY_DEMO", "sk-demo")

    monkeypatch.setattr(bot, "_load_telegram_module", lambda: TelegramModule)
    monkeypatch.delenv("TEEBOTUS_INSTANCE", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN_DEMO", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY_DEMO", raising=False)

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0
    assert calls == [
        ("dotenv", Path("/tmp/teebotus-test-root/.env")),
        ("defaults", Path("/tmp/teebotus-test-root/ALL_BOTS_DEFAULT.md")),
    ]


def test_runtime_status_reports_signal_service_health(monkeypatch, capsys) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("SIGNAL_BOT_SERVICE_DEMO", "http://127.0.0.1:8080")
    monkeypatch.setenv("SIGNAL_BOT_PHONE_NUMBER_DEMO", "+491234")

    def fake_check_signal_services(config):
        account = [account for instance in config.instances for account in instance.accounts if account.channel == "signal"][0]
        return (SimpleNamespace(account=account, ok=False, target="127.0.0.1:8080", error="connection refused"),)

    def fake_check_signal_accounts(config):
        account = [account for instance in config.instances for account in instance.accounts if account.channel == "signal"][0]
        return (
            SimpleNamespace(
                account=account,
                ok=False,
                registered=False,
                target="127.0.0.1:8080",
                error="account missing in signal-cli-rest-api /v1/accounts",
            ),
        )

    monkeypatch.setattr("TeeBotus.runtime.signal_runner.check_signal_services", fake_check_signal_services)
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.check_signal_accounts", fake_check_signal_accounts)

    assert bot.main(["--runtime-status", "--channels", "signal"]) == 0
    captured = capsys.readouterr()
    assert "signal_service=Demo/signal:1 target=127.0.0.1:8080 status=unreachable error=connection refused" in captured.out
    assert (
        "signal_account=Demo/signal:1 phone=+491234 target=127.0.0.1:8080 status=missing "
        "error=account missing in signal-cli-rest-api /v1/accounts"
    ) in captured.out


def test_runtime_status_reports_matrix_homeserver_health(monkeypatch, capsys) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("MATRIX_BOT_HOMESERVER_DEMO", "https://matrix.example")
    monkeypatch.setenv("MATRIX_BOT_USER_ID_DEMO", "@bot:example")
    monkeypatch.setenv("MATRIX_BOT_ACCESS_TOKEN_DEMO", "matrix-token")

    def fake_check_matrix_homeservers(config):
        account = [account for instance in config.instances for account in instance.accounts if account.channel == "matrix"][0]
        return (SimpleNamespace(account=account, ok=False, target="matrix.example:443", error="connection refused"),)

    monkeypatch.setattr("TeeBotus.runtime.matrix_runner.check_matrix_homeservers", fake_check_matrix_homeservers)

    assert bot.main(["--runtime-status", "--channels", "matrix"]) == 0
    captured = capsys.readouterr()
    assert "matrix_homeserver=Demo/matrix:1 target=matrix.example:443 status=unreachable error=connection refused" in captured.out


def test_runtime_status_marks_signal_account_unavailable_when_backend_is_down(monkeypatch, capsys) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("SIGNAL_BOT_SERVICE_DEMO", "http://127.0.0.1:8080")
    monkeypatch.setenv("SIGNAL_BOT_PHONE_NUMBER_DEMO", "+491234")

    def fake_check_signal_services(config):
        account = [account for instance in config.instances for account in instance.accounts if account.channel == "signal"][0]
        return (SimpleNamespace(account=account, ok=False, target="127.0.0.1:8080", error="connection refused"),)

    def fake_check_signal_accounts(config):
        account = [account for instance in config.instances for account in instance.accounts if account.channel == "signal"][0]
        return (
            SimpleNamespace(
                account=account,
                ok=False,
                registered=False,
                target="127.0.0.1:8080",
                error="service does not expose signal-cli-rest-api account list",
            ),
        )

    monkeypatch.setattr("TeeBotus.runtime.signal_runner.check_signal_services", fake_check_signal_services)
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.check_signal_accounts", fake_check_signal_accounts)

    assert bot.main(["--runtime-status", "--channels", "signal"]) == 0
    captured = capsys.readouterr()
    assert (
        "signal_account=Demo/signal:1 phone=+491234 target=127.0.0.1:8080 status=unavailable "
        "error=service does not expose signal-cli-rest-api account list"
    ) in captured.out


def test_bot_main_delegates_unknown_normal_args_to_telegram_bot(monkeypatch) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    assert bot.main(["--definitely-not-runtime-status"]) == 2


def test_channels_telegram_is_stripped_before_telegram_delegation(monkeypatch) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    assert bot.main(["--channels", "telegram", "--definitely-not-runtime-status"]) == 2


def test_channels_signal_without_config_fails_clearly(monkeypatch) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.delenv("SIGNAL_BOT_SERVICE_DEMO", raising=False)
    monkeypatch.delenv("SIGNAL_BOT_PHONE_NUMBER_DEMO", raising=False)
    assert bot.main(["--channels", "signal"]) == 2


def test_channels_signal_delegates_to_signal_runtime(monkeypatch) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls = []
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("SIGNAL_BOT_SERVICE_DEMO", "http://127.0.0.1:8080")
    monkeypatch.setenv("SIGNAL_BOT_PHONE_NUMBER_DEMO", "+491234")
    monkeypatch.setattr(bot, "_run_signal_runtime", lambda config: calls.append(config) or 0)

    assert bot.main(["--channels", "signal"]) == 0
    assert calls
    assert calls[0].instances[0].accounts[0].channel == "signal"


def test_channels_telegram_signal_starts_signal_before_telegram(monkeypatch) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls = []
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("SIGNAL_BOT_SERVICE_DEMO", "http://127.0.0.1:8080")
    monkeypatch.setenv("SIGNAL_BOT_PHONE_NUMBER_DEMO", "+491234")
    monkeypatch.setattr(bot, "_start_signal_runtime_background", lambda config: calls.append(("signal", config)) or 0)
    monkeypatch.setattr(bot, "_load_telegram_main", lambda: lambda args: calls.append(("telegram", args)) or 0)

    assert bot.main(["--channels", "telegram,signal"]) == 0
    assert [call[0] for call in calls] == ["signal", "telegram"]


def test_channels_matrix_without_config_fails_clearly(monkeypatch) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.delenv("MATRIX_BOT_HOMESERVER_DEMO", raising=False)
    monkeypatch.delenv("MATRIX_BOT_USER_ID_DEMO", raising=False)
    monkeypatch.delenv("MATRIX_BOT_ACCESS_TOKEN_DEMO", raising=False)
    assert bot.main(["--channels", "matrix"]) == 2


def test_channels_matrix_delegates_to_matrix_runtime(monkeypatch) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls = []
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("MATRIX_BOT_HOMESERVER_DEMO", "https://matrix.example")
    monkeypatch.setenv("MATRIX_BOT_USER_ID_DEMO", "@bot:example")
    monkeypatch.setenv("MATRIX_BOT_ACCESS_TOKEN_DEMO", "matrix-token")
    monkeypatch.setattr(bot, "_run_matrix_runtime", lambda config: calls.append(config) or 0)

    assert bot.main(["--channels", "matrix"]) == 0
    assert calls
    assert calls[0].instances[0].accounts[0].channel == "matrix"


def test_channels_telegram_matrix_starts_matrix_before_telegram(monkeypatch) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls = []
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("MATRIX_BOT_HOMESERVER_DEMO", "https://matrix.example")
    monkeypatch.setenv("MATRIX_BOT_USER_ID_DEMO", "@bot:example")
    monkeypatch.setenv("MATRIX_BOT_ACCESS_TOKEN_DEMO", "matrix-token")
    monkeypatch.setattr(bot, "_start_matrix_runtime_background", lambda config: calls.append(("matrix", config)) or 0)
    monkeypatch.setattr(bot, "_load_telegram_main", lambda: lambda args: calls.append(("telegram", args)) or 0)

    assert bot.main(["--channels", "telegram,matrix"]) == 0
    assert [call[0] for call in calls] == ["matrix", "telegram"]


def test_channels_signal_matrix_rejects_before_starting_any_runner(monkeypatch) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls = []
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("SIGNAL_BOT_SERVICE_DEMO", "http://127.0.0.1:8080")
    monkeypatch.setenv("SIGNAL_BOT_PHONE_NUMBER_DEMO", "+491234")
    monkeypatch.setenv("MATRIX_BOT_HOMESERVER_DEMO", "https://matrix.example")
    monkeypatch.setenv("MATRIX_BOT_USER_ID_DEMO", "@bot:example")
    monkeypatch.setenv("MATRIX_BOT_ACCESS_TOKEN_DEMO", "matrix-token")
    monkeypatch.setattr(bot, "_start_signal_runtime_background", lambda config: calls.append(("signal", config)) or 0)
    monkeypatch.setattr(bot, "_start_matrix_runtime_background", lambda config: calls.append(("matrix", config)) or 0)
    monkeypatch.setattr(bot, "_run_signal_runtime", lambda config: calls.append(("run-signal", config)) or 0)
    monkeypatch.setattr(bot, "_run_matrix_runtime", lambda config: calls.append(("run-matrix", config)) or 0)

    assert bot.main(["--channels", "signal,matrix"]) == 2
    assert calls == []
