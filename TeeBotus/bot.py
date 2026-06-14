"""Compatibility entry point for TeeBotus.

Plan-3 work is intentionally additive.  The productive Telegram bot entry point
must remain available as ``TeeBotus.bot.main`` and through ``python3 -m
TeeBotus``.  This shim exists to prevent the new runtime scaffolding from
replacing the legacy Telegram polling path by accident.

When the original implementation is present in a legacy module, this file
forwards to it.  If it is missing, the command fails loudly with a concrete
repair message instead of raising ``No module named TeeBotus.__main__`` or
silently starting the unfinished Plan-3 runtime.
"""

from __future__ import annotations

import importlib
import os
import sys
import types
from collections.abc import Sequence
from typing import Any, Callable

_LEGACY_MAIN_CANDIDATES = (
    # Preferred location if the historic implementation is moved out of the
    # way during the Plan-3 refactor.
    "TeeBotus.legacy_bot",
    "TeeBotus._legacy_bot",
    # Historical package name used before the package rename.
    "telegram_bot.bot",
)


class LegacyBotMissingError(RuntimeError):
    """Raised when no legacy Telegram bot implementation can be found."""


def _load_legacy_main() -> Callable[[list[str] | None], int] | None:
    for module_name in _LEGACY_MAIN_CANDIDATES:
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            # Ignore only the candidate itself being absent.  If importing a
            # candidate fails because one of its dependencies is missing, surface
            # the real error instead of hiding it and falling through.
            if exc.name == module_name or module_name.startswith(f"{exc.name}."):
                continue
            raise
        main = getattr(module, "main", None)
        if callable(main):
            return main
    return None


def _load_legacy_module() -> Any | None:
    for module_name in _LEGACY_MAIN_CANDIDATES:
        try:
            return importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name == module_name or module_name.startswith(f"{exc.name}."):
                continue
            raise
    return None


def __getattr__(name: str) -> Any:
    legacy_module = _load_legacy_module()
    if legacy_module is not None and hasattr(legacy_module, name):
        return getattr(legacy_module, name)
    raise AttributeError(f"module 'TeeBotus.bot' has no attribute {name!r}")


def _populate_legacy_exports() -> None:
    legacy_module = _load_legacy_module()
    if legacy_module is None:
        return
    current = globals()
    for name, value in vars(legacy_module).items():
        if name.startswith("__"):
            continue
        current.setdefault(name, value)


class _CompatBotModule(types.ModuleType):
    def __setattr__(self, name: str, value: Any) -> None:
        legacy_module = _load_legacy_module()
        if legacy_module is not None and hasattr(legacy_module, name):
            setattr(legacy_module, name, value)
        super().__setattr__(name, value)


def _runtime_status(argv: Sequence[str]) -> int:
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


def _legacy_args_from_runtime_cli(args: list[str]) -> tuple[list[str] | None, int]:
    legacy_args: list[str] = []
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
        legacy_args.append(arg)
        index += 1
    requested = {part.strip().casefold() for part in channels.split(",") if part.strip()}
    if not requested or requested in ({"auto"}, {"all"}):
        return legacy_args, 0
    if requested == {"telegram"}:
        return legacy_args, 0
    print("Signal/Mehrkanal-Produktivstart ist in diesem Compatibility-Entry-Point noch nicht freigeschaltet. Nutze --runtime-status zur Plan-3-Konfigurationsprüfung.", file=sys.stderr)
    return None, 2


def main(argv: list[str] | None = None) -> int:
    """Run TeeBotus without breaking the existing Telegram-only entry point.

    The Plan-3 runtime is not yet a drop-in replacement for the old Telegram
    polling loop.  Therefore this function delegates to a preserved legacy
    implementation when available.  It deliberately refuses to start a partial
    runtime as if it were production-ready.
    """

    args = list(sys.argv[1:] if argv is None else argv)

    if args and args[0] in {"--runtime-status", "runtime-status"}:
        return _runtime_status(args[1:])

    legacy_args, cli_status = _legacy_args_from_runtime_cli(args)
    if legacy_args is None:
        return cli_status

    legacy_main = _load_legacy_main()
    if legacy_main is not None:
        return int(legacy_main(legacy_args))

    print("TeeBotus legacy Telegram bot implementation is missing.", file=sys.stderr)
    print("This Plan-3 patch must be applied additively; restore the original TeeBotus/bot.py as TeeBotus/legacy_bot.py or revert the deletion.", file=sys.stderr)
    print("Expected invariant: python3 -m TeeBotus and python3 -m TeeBotus --all must delegate to the existing Telegram polling loop until the new runtime is fully wired.", file=sys.stderr)
    return 1


__all__ = ["LegacyBotMissingError", "main"]

_populate_legacy_exports()
sys.modules[__name__].__class__ = _CompatBotModule
