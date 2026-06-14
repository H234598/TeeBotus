"""Stable entry point for TeeBotus.

``TeeBotus.bot`` stays as the public import and command module, while the
Telegram polling implementation lives in ``TeeBotus.adapters.telegram_polling``.
"""

from __future__ import annotations

import importlib
import os
import sys
import types
from collections.abc import Sequence
from typing import Any, Callable

_TELEGRAM_MODULE = "TeeBotus.adapters.telegram_polling"


class TelegramBotMissingError(RuntimeError):
    """Raised when the Telegram bot implementation cannot be found."""


def _load_telegram_main() -> Callable[[list[str] | None], int] | None:
    module = _load_telegram_module()
    main = getattr(module, "main", None) if module is not None else None
    if callable(main):
        return main
    return None


def _load_telegram_module() -> Any | None:
    try:
        return importlib.import_module(_TELEGRAM_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name == _TELEGRAM_MODULE or _TELEGRAM_MODULE.startswith(f"{exc.name}."):
            return None
        raise


def __getattr__(name: str) -> Any:
    telegram_module = _load_telegram_module()
    if telegram_module is not None and hasattr(telegram_module, name):
        return getattr(telegram_module, name)
    raise AttributeError(f"module 'TeeBotus.bot' has no attribute {name!r}")


def _populate_telegram_exports() -> None:
    telegram_module = _load_telegram_module()
    if telegram_module is None:
        return
    current = globals()
    for name, value in vars(telegram_module).items():
        if name.startswith("__"):
            continue
        current.setdefault(name, value)


class _TelegramBotModule(types.ModuleType):
    def __setattr__(self, name: str, value: Any) -> None:
        telegram_module = _load_telegram_module()
        if telegram_module is not None and hasattr(telegram_module, name):
            setattr(telegram_module, name, value)
        super().__setattr__(name, value)


def _load_runtime_environment() -> None:
    telegram_module = _load_telegram_module()
    if telegram_module is None:
        return
    project_root = getattr(telegram_module, "PROJECT_ROOT", None)
    load_dotenv = getattr(telegram_module, "_load_dotenv", None)
    if project_root is not None and callable(load_dotenv):
        load_dotenv(project_root / ".env")
    load_defaults = getattr(telegram_module, "_load_runtime_config_defaults", None)
    defaults_filename = getattr(telegram_module, "ALL_BOTS_DEFAULT_FILENAME", "ALL_BOTS_DEFAULT.md")
    if project_root is not None and callable(load_defaults):
        load_defaults(project_root / defaults_filename)


def _runtime_status(argv: Sequence[str]) -> int:
    _load_runtime_environment()
    try:
        from TeeBotus.runtime.config import RuntimeConfigError, resolve_runtime_config
    except Exception as exc:  # pragma: no cover - defensive only
        print(f"TeeBotus compatibility error: could not import runtime config: {exc}", file=sys.stderr)
        return 2

    try:
        config = resolve_runtime_config(argv=list(argv))
    except RuntimeConfigError as exc:
        print(f"TeeBotus runtime configuration error: {exc}", file=sys.stderr)
        return 2
    print("TeeBotus runtime configuration resolves.")
    print(f"instances_dir={config.instances_dir}")
    print(f"instances={','.join(config.selected_instances) if config.selected_instances else 'auto'}")
    print(f"channels={','.join(config.channels)}")
    return 0


def _telegram_args_from_runtime_cli(args: list[str]) -> tuple[list[str] | None, int]:
    telegram_args: list[str] = []
    channels = "auto"
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--channels":
            if index + 1 >= len(args):
                print("Missing value for --channels.", file=sys.stderr)
                return None, 2
            channels = args[index + 1]
            index += 2
            continue
        if arg.startswith("--channels="):
            channels = arg.split("=", 1)[1]
            index += 1
            continue
        telegram_args.append(arg)
        index += 1
    requested = {part.strip().casefold() for part in channels.split(",") if part.strip()}
    if not requested or requested in ({"auto"}, {"all"}):
        return telegram_args, 0
    if requested == {"telegram"}:
        return telegram_args, 0
    print("Signal/Mehrkanal-Produktivstart ist in diesem Entry-Point noch nicht freigeschaltet. Nutze --runtime-status zur Konfigurationsprüfung.", file=sys.stderr)
    return None, 2


def main(argv: list[str] | None = None) -> int:
    """Run TeeBotus through the productive Telegram entry point."""

    args = list(sys.argv[1:] if argv is None else argv)

    if args and args[0] in {"--runtime-status", "runtime-status"}:
        return _runtime_status(args[1:])

    telegram_args, cli_status = _telegram_args_from_runtime_cli(args)
    if telegram_args is None:
        return cli_status

    telegram_main = _load_telegram_main()
    if telegram_main is not None:
        return int(telegram_main(telegram_args))

    print("TeeBotus Telegram bot implementation is missing.", file=sys.stderr)
    print("Expected invariant: python3 -m TeeBotus and python3 -m TeeBotus --all must delegate to TeeBotus.adapters.telegram_polling.", file=sys.stderr)
    return 1


__all__ = ["TelegramBotMissingError", "main"]

_populate_telegram_exports()
sys.modules[__name__].__class__ = _TelegramBotModule
