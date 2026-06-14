from __future__ import annotations

import importlib
from pathlib import Path


def test_package_entrypoint_exists_and_delegates_to_bot_main() -> None:
    module = importlib.import_module("TeeBotus.__main__")
    bot = importlib.import_module("TeeBotus.bot")
    assert hasattr(module, "main")
    assert module.main is bot.main


def test_bot_main_is_callable() -> None:
    bot = importlib.import_module("TeeBotus.bot")
    assert callable(bot.main)


def test_runtime_status_does_not_require_telegram_bot_start() -> None:
    bot = importlib.import_module("TeeBotus.bot")
    result = bot.main(["--runtime-status", "--channels", "telegram"])
    assert result == 0


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


def test_bot_main_delegates_unknown_normal_args_to_telegram_bot() -> None:
    bot = importlib.import_module("TeeBotus.bot")
    assert bot.main(["--definitely-not-runtime-status"]) == 2


def test_channels_telegram_is_stripped_before_telegram_delegation() -> None:
    bot = importlib.import_module("TeeBotus.bot")
    assert bot.main(["--channels", "telegram", "--definitely-not-runtime-status"]) == 2


def test_channels_signal_does_not_start_partial_runtime() -> None:
    bot = importlib.import_module("TeeBotus.bot")
    assert bot.main(["--channels", "signal"]) == 2
