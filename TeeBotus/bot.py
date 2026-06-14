"""Stable entry point for TeeBotus.

``TeeBotus.bot`` stays as the public import and command module, while the
Telegram polling implementation lives in ``TeeBotus.adapters.telegram_polling``.
"""

from __future__ import annotations

import importlib
import sys
import types
from collections.abc import Sequence
from typing import Any, Callable

_TELEGRAM_MODULE = "TeeBotus.adapters.telegram_polling"
_COMPAT_EXPORT_MODULES = (
    _TELEGRAM_MODULE,
    "TeeBotus.core.youtube",
)


class TelegramBotMissingError(RuntimeError):
    """Raised when the Telegram bot implementation cannot be found."""


def _load_telegram_main() -> Callable[[list[str] | None], int] | None:
    module = _load_telegram_module()
    main = getattr(module, "main", None) if module is not None else None
    if callable(main):
        return main
    return None


def _load_telegram_module() -> Any | None:
    return _load_module(_TELEGRAM_MODULE)


def _load_module(module_name: str) -> Any | None:
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name or module_name.startswith(f"{exc.name}."):
            return None
        raise


def __getattr__(name: str) -> Any:
    for module_name in _COMPAT_EXPORT_MODULES:
        module = _load_module(module_name)
        if module is not None and hasattr(module, name):
            return getattr(module, name)
    raise AttributeError(f"module 'TeeBotus.bot' has no attribute {name!r}")


def _populate_telegram_exports() -> None:
    current = globals()
    for module_name in _COMPAT_EXPORT_MODULES:
        module = _load_module(module_name)
        if module is None:
            continue
        for name, value in vars(module).items():
            if name.startswith("__"):
                continue
            current.setdefault(name, value)


class _TelegramBotModule(types.ModuleType):
    def __setattr__(self, name: str, value: Any) -> None:
        for module_name in _COMPAT_EXPORT_MODULES:
            module = _load_module(module_name)
            if module is not None and hasattr(module, name):
                setattr(module, name, value)
                break
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
    return _strip_runtime_channels_arg(args)


def _strip_runtime_channels_arg(args: list[str]) -> tuple[list[str] | None, int]:
    telegram_args: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--channels":
            if index + 1 >= len(args):
                print("Missing value for --channels.", file=sys.stderr)
                return None, 2
            index += 2
            continue
        if arg.startswith("--channels="):
            index += 1
            continue
        telegram_args.append(arg)
        index += 1
    return telegram_args, 0


def _runtime_config_from_main_args(args: list[str]) -> Any | None:
    _load_runtime_environment()
    try:
        from TeeBotus.runtime.config import RuntimeConfigError, resolve_runtime_config
    except Exception as exc:  # pragma: no cover - defensive only
        print(f"TeeBotus compatibility error: could not import runtime config: {exc}", file=sys.stderr)
        return None
    runtime_args = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--channels":
            if index + 1 >= len(args):
                print("Missing value for --channels.", file=sys.stderr)
                return None
            runtime_args.extend([arg, args[index + 1]])
            index += 2
            continue
        if arg.startswith("--channels="):
            runtime_args.append(arg)
        index += 1
    try:
        return resolve_runtime_config(runtime_args)
    except RuntimeConfigError as exc:
        print(f"TeeBotus runtime configuration error: {exc}", file=sys.stderr)
        return None


def _runtime_has_signal_accounts(config: Any) -> bool:
    return any(account.channel == "signal" for instance in config.instances for account in instance.accounts)


def _runtime_has_telegram_accounts(config: Any) -> bool:
    return any(account.channel == "telegram" for instance in config.instances for account in instance.accounts)


def _signal_requested_without_telegram(config: Any) -> bool:
    return "signal" in config.channels and "telegram" not in config.channels


def _run_signal_runtime(config: Any) -> int:
    try:
        from TeeBotus.runtime.signal_runner import SignalRuntimeError, run_signal_accounts
    except Exception as exc:  # pragma: no cover - defensive only
        print(f"TeeBotus compatibility error: could not import Signal runtime: {exc}", file=sys.stderr)
        return 2
    try:
        return int(run_signal_accounts(config))
    except SignalRuntimeError as exc:
        print(f"TeeBotus Signal runtime error: {exc}", file=sys.stderr)
        return 2


def _start_signal_runtime_background(config: Any) -> int:
    try:
        from TeeBotus.runtime.signal_runner import SignalRuntimeError, start_signal_accounts_in_background
    except Exception as exc:  # pragma: no cover - defensive only
        print(f"TeeBotus compatibility error: could not import Signal runtime: {exc}", file=sys.stderr)
        return 2
    try:
        start_signal_accounts_in_background(config)
    except SignalRuntimeError as exc:
        print(f"TeeBotus Signal runtime error: {exc}", file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run TeeBotus through the productive Telegram entry point."""

    args = list(sys.argv[1:] if argv is None else argv)

    if args and args[0] in {"--runtime-status", "runtime-status"}:
        return _runtime_status(args[1:])

    config = _runtime_config_from_main_args(args)
    if config is None:
        return 2
    if _signal_requested_without_telegram(config):
        return _run_signal_runtime(config)
    if "signal" in config.channels and _runtime_has_signal_accounts(config):
        status = _start_signal_runtime_background(config)
        if status != 0:
            return status
    if "telegram" in config.channels and not _runtime_has_telegram_accounts(config):
        print("Telegram ist angefordert, aber kein TELEGRAM_BOT_TOKEN_<INSTANCE> ist konfiguriert.", file=sys.stderr)
        return 2

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
