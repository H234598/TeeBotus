from __future__ import annotations

import importlib


def test_package_entrypoint_exists_and_delegates_to_bot_main() -> None:
    module = importlib.import_module("TeeBotus.__main__")
    bot = importlib.import_module("TeeBotus.bot")
    assert hasattr(module, "main")
    assert module.main is bot.main


def test_bot_main_is_callable() -> None:
    bot = importlib.import_module("TeeBotus.bot")
    assert callable(bot.main)


def test_runtime_status_does_not_require_legacy_bot() -> None:
    bot = importlib.import_module("TeeBotus.bot")
    result = bot.main(["--runtime-status", "--channels", "telegram"])
    assert result == 0


def test_bot_main_delegates_unknown_normal_args_to_legacy_bot() -> None:
    bot = importlib.import_module("TeeBotus.bot")
    assert bot.main(["--definitely-not-runtime-status"]) == 2


def test_channels_telegram_is_stripped_before_legacy_delegation() -> None:
    bot = importlib.import_module("TeeBotus.bot")
    assert bot.main(["--channels", "telegram", "--definitely-not-runtime-status"]) == 2


def test_channels_signal_does_not_start_partial_runtime() -> None:
    bot = importlib.import_module("TeeBotus.bot")
    assert bot.main(["--channels", "signal"]) == 2
