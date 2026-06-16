"""Stable entry point for TeeBotus.

``TeeBotus.bot`` stays as the public import and command module, while the
Telegram transport is started through the shared runtime configuration.
"""

from __future__ import annotations

import importlib
import os
import re
import sys
import types
from collections.abc import Sequence
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

from TeeBotus import __version__

_TELEGRAM_MODULE = "TeeBotus.adapters.telegram_runtime"
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
        from TeeBotus.core.status import account_memory_index_health_lines, mcp_tool_runtime_status_line
        from TeeBotus.core.local_transcription import check_local_transcription_backend
        from TeeBotus.instructions import InstructionStore
        from TeeBotus.runtime.bibliothekar_service import check_bibliothekar_service
        from TeeBotus.runtime.config import RuntimeConfigError, resolve_runtime_config
        from TeeBotus.runtime.matrix_runner import check_matrix_homeservers
        from TeeBotus.runtime.ollama_health import check_ollama_services
        from TeeBotus.runtime.signal_runner import check_signal_accounts, check_signal_services
        from TeeBotus.runtime.telegram_runner import check_telegram_accounts
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
    for instance in config.instances:
        for account in instance.accounts:
            print(_runtime_status_llm_line(account))
    for health in check_ollama_services(config):
        state = "reachable" if health.ok else "unreachable"
        if health.ok:
            models = ",".join(health.models) if health.models else "<none>"
            print(f"ollama={_sanitize_status_url(health.target)} status={state} models={_sanitize_status_text(models)}")
        else:
            print(f"ollama={_sanitize_status_url(health.target)} status={state} error={_sanitize_status_text(health.error)}")
    for health in check_signal_services(config):
        state = "reachable" if health.ok else "unreachable"
        detail = "" if health.ok else f" error={_sanitize_status_text(health.error)}"
        print(f"signal_service={health.account.instance_name}/{health.account.label} target={_sanitize_status_url(health.target)} status={state}{detail}")
    for health in check_signal_accounts(config):
        if health.registered:
            state = "registered"
        elif health.error == "account missing in signal-cli-rest-api /v1/accounts":
            state = "missing"
        else:
            state = "unavailable"
        detail = "" if health.ok else f" error={_sanitize_status_text(health.error)}"
        print(
            f"signal_account={health.account.instance_name}/{health.account.label} "
            f"phone={health.account.signal_phone_number} target={_sanitize_status_url(health.target)} status={state}{detail}"
        )
    for health in check_telegram_accounts(config):
        state = "configured" if health.ok else "broken"
        detail = " token=configured" if health.ok else f" error={_sanitize_status_text(health.error)}"
        print(f"telegram_slot={health.account.instance_name}/{health.account.label} status={state}{detail}")
    for health in check_matrix_homeservers(config):
        state = "reachable" if health.ok else "unreachable"
        detail = "" if health.ok else f" error={_sanitize_status_text(health.error)}"
        print(f"matrix_homeserver={health.account.instance_name}/{health.account.label} target={_sanitize_status_url(health.target)} status={state}{detail}")
    for instance in config.instances:
        try:
            instructions = InstructionStore(instance.instruction_path).get()
        except Exception as exc:
            print(f"local_transcription={instance.instance_name} status=broken error={_sanitize_status_text(f'{type(exc).__name__}: {exc}')}")
            continue
        health = check_local_transcription_backend(instance.instance_name, instructions)
        if health is None:
            continue
        state = "ready" if health.ok else "unavailable"
        detail = f" engine={_sanitize_status_text(health.engine)}" if health.ok else f" error={_sanitize_status_text(health.error)}"
        print(f"local_transcription={health.instance_name} backend={health.backend} model={health.model} status={state}{detail}")
    for instance in config.instances:
        try:
            instructions = InstructionStore(instance.instruction_path).get()
        except Exception as exc:
            print(f"bibliothekar={instance.instance_name} status=broken error={_sanitize_status_text(f'{type(exc).__name__}: {exc}')}")
            continue
        health = check_bibliothekar_service(instance.instance_name, config.instances_dir, instructions)
        detail = (
            f"bibliothekar={health.instance_name} backend={health.backend} "
            f"store={health.store or '<none>'} collection={health.collection or '<none>'}"
        )
        if health.target:
            detail += f" target={_sanitize_status_url(health.target)}"
        detail += f" status={health.status}"
        if health.documents or health.chunks:
            detail += f" documents={health.documents} chunks={health.chunks}"
        if health.error:
            detail += f" error={_sanitize_status_text(health.error)}"
        print(detail)
    for instance in config.instances:
        try:
            instructions = InstructionStore(instance.instruction_path).get()
        except Exception as exc:
            print(f"mcp_tools={instance.instance_name} status=broken error={_sanitize_status_text(f'{type(exc).__name__}: {exc}')}")
            continue
        print(_sanitize_status_text(mcp_tool_runtime_status_line(instance.instance_name, instructions.mcp_tools)))
    for instance_name in config.selected_instances:
        for line in account_memory_index_health_lines(instance_name=instance_name, project_root=config.instances_dir.parent):
            print(_sanitize_status_text(line))
    return 0


def _runtime_status_llm_line(account: Any) -> str:
    if _parse_optional_status_bool(getattr(account, "llm_enabled", "")) is False:
        return f"llm={account.instance_name}/{account.label} provider=none model=<disabled> status=disabled"
    provider, model, base_url, route_fallback_count, route_api_key_env, route_error = _status_llm_route(account)
    if provider == "openai" and model == "<legacy>":
        model = "<Bot_Verhalten/OpenAI>"
    key_configured = _llm_key_configured(account, provider, route_api_key_env=route_api_key_env)
    if route_error:
        status = "broken"
    elif provider == "openai":
        status = "configured" if key_configured else "missing_key"
    else:
        status = "configured"
    detail = (
        f"llm={account.instance_name}/{account.label} "
        f"provider={provider} model={model} status={status}"
    )
    profile = str(getattr(account, "llm_profile", "") or "").strip()
    if profile:
        detail += f" profile={profile}"
    purpose = str(getattr(account, "llm_purpose", "") or "").strip()
    if purpose:
        detail += f" purpose={purpose}"
    if base_url:
        detail += f" base_url={base_url}"
    if provider != "openai":
        detail += f" api_key={'configured' if key_configured else 'none'}"
    fallback_count = _status_effective_fallback_count(
        account,
        provider=provider,
        route_fallback_count=route_fallback_count,
    )
    if fallback_count:
        detail += f" fallback_models={fallback_count}"
    allow_remote_fallback = _parse_optional_status_bool(getattr(account, "llm_allow_remote_fallback", ""))
    if allow_remote_fallback is not None:
        detail += f" remote_fallback={'enabled' if allow_remote_fallback else 'disabled'}"
    timeout = str(getattr(account, "llm_timeout_seconds", "") or "").strip()
    if timeout:
        detail += f" timeout_seconds={timeout}"
    max_tokens = str(getattr(account, "llm_max_output_tokens", "") or "").strip()
    if max_tokens:
        detail += f" max_output_tokens={max_tokens}"
    temperature = str(getattr(account, "llm_temperature", "") or "").strip()
    if temperature:
        detail += f" temperature={temperature}"
    if route_error:
        detail += f" error={_sanitize_status_text(route_error)}"
    return detail


def _status_llm_route(account: Any) -> tuple[str, str, str, int, str, str]:
    provider = _status_value(getattr(account, "llm_provider", ""), default="openai")
    model = _status_value(getattr(account, "llm_model", ""), default="<legacy>")
    base_url = _sanitize_status_url(getattr(account, "llm_base_url", ""))
    profile_name = str(getattr(account, "llm_profile", "") or "").strip()
    purpose = str(getattr(account, "llm_purpose", "") or "").strip()
    allow_remote_fallback = _parse_optional_status_bool(getattr(account, "llm_allow_remote_fallback", "")) is True
    try:
        if profile_name:
            from TeeBotus.llm.profiles import load_llm_profiles

            profile = load_llm_profiles()[profile_name]
            return profile.provider, profile.model, _sanitize_status_url(profile.base_url), 0, profile.api_key_env, ""
        if purpose and not (str(getattr(account, "llm_provider", "") or "").strip() or str(getattr(account, "llm_model", "") or "").strip()):
            from TeeBotus.llm.profiles import select_llm_route

            route = select_llm_route(purpose, allow_remote_fallback=allow_remote_fallback)
            return route.provider, route.model, _sanitize_status_url(route.base_url), len(route.fallback_models), route.api_key_env, ""
    except Exception as exc:  # noqa: BLE001 - runtime-status should report bad routing config without crashing.
        return provider, model, base_url, 0, "", f"{type(exc).__name__}: {exc}"
    return provider, model, base_url, 0, "", ""


def _status_value(value: object, *, default: str) -> str:
    text = str(value or "").strip()
    return text if text else default


def _llm_key_configured(account: Any, provider: str, *, route_api_key_env: str = "") -> bool:
    if provider == "openai":
        if str(getattr(account, "openai_api_key", "") or "").strip():
            return True
    if str(getattr(account, "llm_api_key", "") or "").strip():
        return True
    if route_api_key_env and os.environ.get(route_api_key_env, "").strip():
        return True
    profile_name = str(getattr(account, "llm_profile", "") or "").strip()
    if profile_name:
        try:
            from TeeBotus.llm.profiles import load_llm_profiles

            profile = load_llm_profiles()[profile_name]
        except Exception:
            return False
        return bool(profile.api_key_env and os.environ.get(profile.api_key_env, "").strip())
    return False


def _status_effective_fallback_count(account: Any, *, provider: str, route_fallback_count: int) -> int:
    configured_fallbacks = str(getattr(account, "llm_fallback_models", "") or "").strip()
    if not configured_fallbacks:
        return route_fallback_count
    allow_remote_fallback = _parse_optional_status_bool(getattr(account, "llm_allow_remote_fallback", "")) is True
    try:
        from TeeBotus.runtime.llm_factory import filter_runtime_fallback_models

        return len(
            filter_runtime_fallback_models(
                provider=provider,
                fallback_models=configured_fallbacks,
                allow_remote_fallback=allow_remote_fallback,
            )
        )
    except Exception:
        return _csv_count(configured_fallbacks)


def _csv_count(value: object) -> int:
    return len([part for part in str(value or "").split(",") if part.strip()])


def _parse_optional_status_bool(value: object) -> bool | None:
    text = str(value or "").strip().casefold()
    if not text:
        return None
    if text in {"1", "true", "yes", "ja", "on", "enabled", "an"}:
        return True
    if text in {"0", "false", "no", "nein", "off", "disabled", "aus"}:
        return False
    return None


def _sanitize_status_url(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = urlsplit(text)
    except ValueError:
        return "<invalid>"
    if parsed.scheme and parsed.netloc:
        netloc = _safe_url_netloc(parsed)
        return urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/"), "", ""))
    try:
        schemeless = urlsplit(f"//{text}")
    except ValueError:
        return redact_status_url_text(text)
    if schemeless.hostname:
        return _safe_url_netloc(schemeless)
    return redact_status_url_text(text)


def _safe_url_netloc(parsed: Any) -> str:
    netloc = parsed.hostname or ""
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port is not None:
        netloc = f"{netloc}:{port}"
    return netloc


def redact_status_url_text(value: object) -> str:
    text = _sanitize_status_text(value)
    return re.sub(r"(?<!\S)[^/\s:@]+:[^/\s@]+@(?=[^\s]+)", "", text)


def _sanitize_status_text(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "sk-<redacted>", text)
    text = re.sub(r"\bxox[baprs]-[A-Za-z0-9_-]{8,}\b", "xox-<redacted>", text)
    text = re.sub(r"\bsyt_[A-Za-z0-9_=-]{8,}\b", "syt_<redacted>", text)
    text = re.sub(r"\bgh[pousr]_[A-Za-z0-9_]{8,}\b", "gh_<redacted>", text)
    text = re.sub(r"\bgithub_pat_[A-Za-z0-9_]{12,}\b", "github_pat_<redacted>", text)
    text = re.sub(r"\bglpat-[A-Za-z0-9_-]{8,}\b", "glpat-<redacted>", text)
    text = re.sub(r"\bhf_[A-Za-z0-9]{8,}\b", "hf_<redacted>", text)
    text = re.sub(r"\bgsk_[A-Za-z0-9]{8,}\b", "gsk_<redacted>", text)
    text = re.sub(r"\bAIza[0-9A-Za-z_-]{16,}\b", "AIza<redacted>", text)
    text = re.sub(
        r"\b([A-Za-z0-9_ -]*(?:api[_ -]?key|access[_ -]?token|auth[_ -]?token|bearer[_ -]?token|token|secret|password)"
        r"[A-Za-z0-9_ -]*)\s*([:=])\s*([^,\s)]+)",
        r"\1\2<redacted>",
        text,
        flags=re.IGNORECASE,
    )
    return text.replace("\r", " ").replace("\n", " ")


def _runtime_config_from_main_args(args: list[str]) -> Any | None:
    _load_runtime_environment()
    try:
        from TeeBotus.runtime.config import RuntimeConfigError, resolve_runtime_config
    except Exception as exc:  # pragma: no cover - defensive only
        print(f"TeeBotus compatibility error: could not import runtime config: {exc}", file=sys.stderr)
        return None
    runtime_args = []
    runtime_env = None
    unknown_args: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--all":
            if runtime_env is None:
                runtime_env = dict(os.environ)
            runtime_env.pop("TEEBOTUS_INSTANCES", None)
            runtime_env.pop("TELEGRAM_BOT_INSTANCES", None)
            runtime_env["TEEBOTUS_INSTANCE"] = "all"
            runtime_env["TELEGRAM_BOT_INSTANCE"] = "all"
            index += 1
            continue
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
            continue
        unknown_args.append(arg)
        index += 1
    if unknown_args:
        print(f"Unsupported startup option(s): {', '.join(unknown_args)}", file=sys.stderr)
        return None
    try:
        return resolve_runtime_config(runtime_args, env=runtime_env)
    except RuntimeConfigError as exc:
        print(f"TeeBotus runtime configuration error: {exc}", file=sys.stderr)
        return None


def _runtime_has_signal_accounts(config: Any) -> bool:
    return _runtime_has_channel_accounts(config, "signal")


def _runtime_has_telegram_accounts(config: Any) -> bool:
    return _runtime_has_channel_accounts(config, "telegram")


def _runtime_has_matrix_accounts(config: Any) -> bool:
    return _runtime_has_channel_accounts(config, "matrix")


def _runtime_has_channel_accounts(config: Any, channel: str) -> bool:
    return any(account.channel == channel for instance in config.instances for account in instance.accounts)


def _channel_requested_without_telegram(config: Any, channel: str) -> bool:
    return channel in config.channels and "telegram" not in config.channels


def _non_telegram_channels(config: Any) -> set[str]:
    return {channel for channel in config.channels if channel != "telegram"}


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


def _run_matrix_runtime(config: Any) -> int:
    try:
        from TeeBotus.runtime.matrix_runner import MatrixRuntimeError, run_matrix_accounts
    except Exception as exc:  # pragma: no cover - defensive only
        print(f"TeeBotus compatibility error: could not import Matrix runtime: {exc}", file=sys.stderr)
        return 2
    try:
        return int(run_matrix_accounts(config))
    except MatrixRuntimeError as exc:
        print(f"TeeBotus Matrix runtime error: {exc}", file=sys.stderr)
        return 2


def _start_matrix_runtime_background(config: Any) -> int:
    try:
        from TeeBotus.runtime.matrix_runner import MatrixRuntimeError, start_matrix_accounts_in_background
    except Exception as exc:  # pragma: no cover - defensive only
        print(f"TeeBotus compatibility error: could not import Matrix runtime: {exc}", file=sys.stderr)
        return 2
    try:
        start_matrix_accounts_in_background(config)
    except MatrixRuntimeError as exc:
        print(f"TeeBotus Matrix runtime error: {exc}", file=sys.stderr)
        return 2
    return 0


def _run_telegram_runtime(config: Any) -> int:
    try:
        from TeeBotus.runtime.telegram_runner import TelegramRuntimeError, start_telegram_accounts
    except Exception as exc:  # pragma: no cover - defensive only
        print(f"TeeBotus compatibility error: could not import Telegram runtime: {exc}", file=sys.stderr)
        return 2
    try:
        return int(start_telegram_accounts(config))
    except TelegramRuntimeError as exc:
        print(f"TeeBotus Telegram runtime error: {exc}", file=sys.stderr)
        return 2


def main(argv: list[str] | None = None) -> int:
    """Run TeeBotus through the shared multi-channel runtime entry point."""

    args = list(sys.argv[1:] if argv is None else argv)

    if args and args[0] in {"--version", "version"}:
        print(f"TeeBotus {__version__}")
        return 0

    if args and args[0] in {"--help", "-h", "help"}:
        print(_main_help_text())
        return 0

    if args and args[0] in {"--runtime-status", "runtime-status"}:
        return _runtime_status(args[1:])

    config = _runtime_config_from_main_args(args)
    if config is None:
        return 2
    if "telegram" not in config.channels and len(_non_telegram_channels(config)) != 1:
        print("Mehrkanal-Start ohne Telegram braucht genau einen blockierenden Channel: signal oder matrix.", file=sys.stderr)
        return 2
    if _channel_requested_without_telegram(config, "matrix") and "signal" not in config.channels:
        return _run_matrix_runtime(config)
    if _channel_requested_without_telegram(config, "signal") and "matrix" not in config.channels:
        return _run_signal_runtime(config)
    if "matrix" in config.channels and _runtime_has_matrix_accounts(config):
        status = _start_matrix_runtime_background(config)
        if status != 0:
            return status
    if "signal" in config.channels and _runtime_has_signal_accounts(config):
        status = _start_signal_runtime_background(config)
        if status != 0:
            return status
    if "telegram" in config.channels and not _runtime_has_telegram_accounts(config):
        print("Telegram ist angefordert, aber kein TELEGRAM_BOT_TOKEN_<INSTANCE> ist konfiguriert.", file=sys.stderr)
        return 2

    if "telegram" in config.channels:
        return _run_telegram_runtime(config)
    return 2


__all__ = ["TelegramBotMissingError", "main"]


def _main_help_text() -> str:
    return "\n".join(
        [
            "Usage: python3 -m TeeBotus [--all] [--channels telegram,signal,matrix]",
            "",
            "Options:",
            "  --version                 Print package version and exit.",
            "  --runtime-status          Print resolved runtime health without starting bot loops.",
            "  --channels CHANNELS       Select channels for runtime-status or startup.",
            "  --all                     Start all configured instances through the runtime entry point.",
            "  --help                    Show this help text and exit.",
        ]
    )

_populate_telegram_exports()
sys.modules[__name__].__class__ = _TelegramBotModule
