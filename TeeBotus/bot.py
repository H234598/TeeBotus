"""Stable entry point for TeeBotus.

``TeeBotus.bot`` stays as the public import and command module, while the
Telegram transport is started through the shared runtime configuration.
"""

from __future__ import annotations

import importlib
import asyncio
import contextlib
import io
import json
import os
import re
import shutil
import sys
import types
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

from TeeBotus import __version__

_TELEGRAM_MODULE = "TeeBotus.adapters.telegram_runtime"
ALLOW_BROKEN_ACCOUNT_MEMORY_START_ENV = "TEEBOTUS_ALLOW_BROKEN_ACCOUNT_MEMORY_START"
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
        from TeeBotus.core.status import (
            account_identity_health_lines,
            account_memory_index_health_lines,
            account_secret_health_lines,
            codex_history_status_lines,
            mcp_tool_runtime_status_line,
        )
        from TeeBotus.core.local_transcription import check_local_transcription_backend
        from TeeBotus.instructions import InstructionStore
        from TeeBotus.llm.gemini_limits_refresh import gemini_free_tier_limit_status_line
        from TeeBotus.llm.hf_pool.health import check_hf_pool, format_hf_pool_status_lines
        from TeeBotus.runtime.bibliothekar_service import check_bibliothekar_service
        from TeeBotus.runtime.config import RuntimeConfigError, resolve_runtime_config
        from TeeBotus.runtime.matrix_runner import check_matrix_accounts, check_matrix_homeservers
        from TeeBotus.runtime.ollama_health import check_ollama_services
        from TeeBotus.runtime.admin_accounts import admin_account_group_status_lines
        from TeeBotus.runtime.qdrant import (
            check_default_collections,
            check_qdrant_health,
            format_qdrant_collection_status_lines,
            format_qdrant_status_line,
            qdrant_display_target,
        )
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
    _print_runtime_status_section(
        "Konfiguration",
        (
            f"instances_dir={config.instances_dir}",
            f"instances={','.join(config.selected_instances) if config.selected_instances else 'auto'}",
            f"channels={','.join(config.channels)}",
        ),
    )
    instructions_by_instance: dict[str, Any] = {}
    account_lines: list[str] = []
    for instance in config.instances:
        try:
            instructions = InstructionStore(instance.instruction_path).get()
            instruction_error = ""
            instructions_by_instance[instance.instance_name] = instructions
        except Exception as exc:  # noqa: BLE001 - runtime-status should diagnose unreadable instructions.
            instructions = None
            instruction_error = f"{type(exc).__name__}: {exc}"
        for account in instance.accounts:
            account_lines.append(_runtime_status_llm_line(account, instructions=instructions, instruction_error=instruction_error))
            account_lines.append(_runtime_status_structured_decision_line(account, instructions=instructions, instruction_error=instruction_error))
        for line in _runtime_status_missing_channel_slot_lines(config.channels, instance):
            account_lines.append(line)
    _print_runtime_status_section("Accounts und Entscheidungen", account_lines)

    llm_backend_lines: list[str] = []
    for health in check_ollama_services(config, instructions_by_instance=instructions_by_instance):
        state = "reachable" if health.ok else "unreachable"
        if health.ok:
            models = ",".join(health.models) if health.models else "<none>"
            llm_backend_lines.append(f"ollama={_sanitize_status_url(health.target)} status={state} models={_sanitize_status_text(models)}")
        else:
            llm_backend_lines.append(f"ollama={_sanitize_status_url(health.target)} status={state} error={_sanitize_status_text(health.error)}")
    try:
        for line in format_hf_pool_status_lines(check_hf_pool(state_store=_runtime_status_hf_pool_state_store())):
            llm_backend_lines.append(_sanitize_status_text(line))
    except Exception as exc:  # noqa: BLE001 - runtime-status should not crash on optional hf_pool.
        llm_backend_lines.append(f"hf_pool=default status=broken error={_sanitize_status_text(f'{type(exc).__name__}: {exc}')}")
    llm_backend_lines.append(_sanitize_status_text(gemini_free_tier_limit_status_line()))
    route_instance_names = tuple(instance.instance_name for instance in config.instances)
    for purpose in _runtime_status_route_purposes():
        llm_backend_lines.append(_runtime_status_decision_line(purpose, instance_names=route_instance_names))
    _print_runtime_status_section("LLM-Routen und Backends", llm_backend_lines)
    _print_runtime_status_section(
        "API Keys, Limits und Kosten",
        _runtime_status_api_budget_lines(config, route_instance_names),
    )
    project_history_lines: list[str] = []
    for instance_name in config.selected_instances:
        for line in codex_history_status_lines(instance_name=instance_name, project_root=config.instances_dir.parent):
            project_history_lines.append(_sanitize_status_text(line))
    _print_runtime_status_section("Projekt-History", project_history_lines)

    crew_lines: list[str] = []
    try:
        from TeeBotus.runtime.crew_pilots import crew_pilot_status_lines

        for line in crew_pilot_status_lines():
            crew_lines.append(_sanitize_status_text(line))
    except Exception as exc:  # noqa: BLE001 - runtime-status should not crash on optional CrewAI planning.
        crew_lines.append(f"crew_pilot=all status=broken error={_sanitize_status_text(f'{type(exc).__name__}: {exc}')}")
    _print_runtime_status_section("Agenten-Piloten", crew_lines)

    qdrant_ok = False
    qdrant_specs, qdrant_collection_config_error = _runtime_qdrant_collection_specs(instructions_by_instance)
    qdrant_status_url, qdrant_url_config_error = _runtime_qdrant_status_url(instructions_by_instance)
    qdrant_config_error = qdrant_collection_config_error or qdrant_url_config_error
    memory_lines: list[str] = []
    try:
        qdrant_health = check_qdrant_health(qdrant_status_url)
        qdrant_ok = qdrant_health.ok
        memory_lines.append(_sanitize_status_text(format_qdrant_status_line(qdrant_health)))
        collection_results = (
            check_default_collections(url=qdrant_health.target, specs=qdrant_specs)
            if qdrant_health.ok and not qdrant_config_error
            else None
        )
        for line in format_qdrant_collection_status_lines(qdrant_health, collection_results=collection_results, specs=qdrant_specs):
            memory_lines.append(_sanitize_status_text(line))
        if qdrant_config_error:
            memory_lines.append(
                _sanitize_status_text(
                    "qdrant_collection=teebotus_user_memory "
                    f"target={qdrant_display_target(qdrant_health.target)} "
                    f"status=config_conflict vector_size=mixed embedding_model=mixed error={qdrant_config_error}"
                )
            )
    except Exception as exc:  # noqa: BLE001 - runtime-status should not crash on optional Qdrant.
        memory_lines.append(f"qdrant=local status=invalid fallback=keyword_memory_search error={_sanitize_status_text(f'{type(exc).__name__}: {exc}')}")
    for instance in config.instances:
        memory_lines.append(
            _sanitize_status_text(
                _runtime_status_memory_index_line(
                    instance.instance_name,
                    instructions_by_instance.get(instance.instance_name),
                    qdrant_ok=qdrant_ok,
                )
            )
        )
    _print_runtime_status_section("Memory und semantische Suche", memory_lines)

    messenger_lines: list[str] = []
    for health in check_signal_services(config):
        state = "reachable" if health.ok else "unreachable"
        detail = "" if health.ok else f" error={_sanitize_status_text(health.error)}"
        messenger_lines.append(f"signal_service={health.account.instance_name}/{health.account.label} target={_sanitize_status_url(health.target)} status={state}{detail}")
    for health in check_signal_accounts(config):
        if health.registered:
            state = "registered"
        elif health.error == "account missing in signal-cli-rest-api /v1/accounts":
            state = "missing"
        else:
            state = "unavailable"
        detail_parts: list[str] = []
        if not health.ok and health.error:
            detail_parts.append(f"error={_sanitize_status_text(health.error)}")
        warning = str(getattr(health, "warning", "") or "").strip()
        if warning:
            detail_parts.append(f"warning={_sanitize_status_text(warning)}")
        router = str(getattr(health, "router", "") or "").strip()
        if router:
            detail_parts.append(f"router={_sanitize_status_text(router)}")
        detail = f" {' '.join(detail_parts)}" if detail_parts else ""
        messenger_lines.append(
            f"signal_account={health.account.instance_name}/{health.account.label} "
            f"phone={health.account.signal_phone_number} target={_sanitize_status_url(health.target)} status={state}{detail}"
        )
    for health in check_telegram_accounts(config):
        state = "configured" if health.ok else "broken"
        detail = " token=configured" if health.ok else f" error={_sanitize_status_text(health.error)}"
        messenger_lines.append(f"telegram_slot={health.account.instance_name}/{health.account.label} status={state}{detail}")
    for health in check_matrix_homeservers(config):
        state = "reachable" if health.ok else "unreachable"
        detail = "" if health.ok else f" error={_sanitize_status_text(health.error)}"
        messenger_lines.append(f"matrix_homeserver={health.account.instance_name}/{health.account.label} target={_sanitize_status_url(health.target)} status={state}{detail}")
    for health in check_matrix_accounts(config):
        state = "configured" if health.ok else "broken"
        detail = " user_id=configured" if health.ok else f" error={_sanitize_status_text(health.error)}"
        messenger_lines.append(f"matrix_account={health.account.instance_name}/{health.account.label} target={_sanitize_status_url(health.target)} status={state}{detail}")
    _print_runtime_status_section("Messenger", messenger_lines)

    local_service_lines: list[str] = []
    for instance in config.instances:
        try:
            instructions = InstructionStore(instance.instruction_path).get()
        except Exception as exc:
            local_service_lines.append(f"local_transcription={instance.instance_name} status=broken error={_sanitize_status_text(f'{type(exc).__name__}: {exc}')}")
            continue
        health = check_local_transcription_backend(instance.instance_name, instructions)
        if health is None:
            continue
        state = "ready" if health.ok else "unavailable"
        detail = f" engine={_sanitize_status_text(health.engine)}" if health.ok else f" error={_sanitize_status_text(health.error)}"
        local_service_lines.append(f"local_transcription={health.instance_name} backend={health.backend} model={health.model} status={state}{detail}")
    for instance in config.instances:
        try:
            instructions = InstructionStore(instance.instruction_path).get()
        except Exception as exc:
            local_service_lines.append(f"bibliothekar={instance.instance_name} status=broken error={_sanitize_status_text(f'{type(exc).__name__}: {exc}')}")
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
        local_service_lines.append(detail)
    _print_runtime_status_section("Lokale Dienste", local_service_lines)

    tool_lines: list[str] = []
    for instance in config.instances:
        try:
            instructions = InstructionStore(instance.instruction_path).get()
        except Exception as exc:
            tool_lines.append(f"mcp_tools={instance.instance_name} status=broken error={_sanitize_status_text(f'{type(exc).__name__}: {exc}')}")
            continue
        tool_lines.append(_sanitize_status_text(mcp_tool_runtime_status_line(instance.instance_name, instructions.mcp_tools)))
    for instance_name in config.selected_instances:
        for line in account_secret_health_lines(instance_name=instance_name, project_root=config.instances_dir.parent):
            tool_lines.append(_sanitize_status_text(line))
        for line in account_memory_index_health_lines(instance_name=instance_name, project_root=config.instances_dir.parent):
            tool_lines.append(_sanitize_status_text(line))
        for line in account_identity_health_lines(
            instance_name=instance_name,
            project_root=config.instances_dir.parent,
            env=os.environ,
            runtime_channels=tuple(config.channels),
        ):
            tool_lines.append(_sanitize_status_text(line))
        for line in admin_account_group_status_lines(
            instance_name=instance_name,
            project_root=config.instances_dir.parent,
            env=os.environ,
        ):
            tool_lines.append(_sanitize_status_text(line))
    _print_runtime_status_section("Tools und Account-Memory", tool_lines)
    return 0


def _print_runtime_status_section(title: str, lines: Sequence[str]) -> None:
    entries = tuple(
        sanitized
        for line in lines
        if (sanitized := _sanitize_status_text(line)).strip()
    )
    if not entries:
        return
    print()
    print(f"[{title}]")
    for line in entries:
        print(line)


def _runtime_status_llm_line(account: Any, *, instructions: Any | None = None, instruction_error: str = "") -> str:
    if instruction_error:
        return (
            f"llm={account.instance_name}/{account.label} provider=<unknown> "
            f"model=<unknown> status=broken error={_sanitize_status_text(instruction_error)}"
        )
    enabled_override = _parse_optional_status_bool(getattr(account, "llm_enabled", ""))
    if enabled_override is False:
        return f"llm={account.instance_name}/{account.label} provider=none model=<disabled> status=disabled"
    if enabled_override is None and getattr(instructions, "llm_enabled", None) is False:
        return f"llm={account.instance_name}/{account.label} provider=none model=<disabled> status=disabled"
    (
        provider,
        model,
        base_url,
        route_fallback_count,
        route_api_key_env,
        route_fallback_api_key_env,
        route_service_tier,
        route_error,
        route_mode,
    ) = _status_llm_route(account, instructions=instructions)
    provider = _normalize_status_llm_provider(provider)
    if provider == "openai" and model == "<legacy>":
        model = "<Bot_Verhalten/OpenAI>"
    key_configured = _llm_key_configured(
        account,
        provider,
        route_api_key_env=route_api_key_env,
        instructions=instructions,
    )
    gemini_key_ring_count = _status_gemini_key_ring_count(
        instance_name=getattr(account, "instance_name", ""),
        provider=provider,
        model=model,
    )
    if gemini_key_ring_count:
        key_configured = True
    key_required = _llm_key_required_for_status(
        account,
        provider=provider,
        model=model,
        base_url=base_url,
        route_api_key_env=route_api_key_env,
    )
    fallback_key_configured = bool(route_fallback_api_key_env and os.environ.get(route_fallback_api_key_env, "").strip())
    direct_fallback_key_status = _direct_remote_fallback_key_status(
        account,
        instructions=instructions,
        provider=provider,
        base_url=base_url,
        key_configured=key_configured,
        route_mode=route_mode,
    )
    fallback_key_missing = (
        bool(route_fallback_count and route_fallback_api_key_env and not fallback_key_configured)
        or direct_fallback_key_status == "missing"
    )
    purpose = str(getattr(account, "llm_purpose", "") or "").strip()
    if route_error:
        status = "broken"
    else:
        pool_status, pool_error = _runtime_status_hf_pool_status(
            account,
            instructions=instructions,
            provider=provider,
            model=model,
            purpose=purpose,
            route_mode=route_mode,
        )
        if pool_status == "unavailable":
            status = "unavailable"
            route_error = pool_error
        elif key_required and not key_configured:
            status = "missing_key"
        elif fallback_key_missing:
            status = "degraded"
        else:
            status = "configured"
    detail = (
        f"llm={account.instance_name}/{account.label} "
        f"provider={provider} model={model} status={status}"
    )
    profile = _effective_llm_profile(account, instructions)
    if profile:
        detail += f" profile={profile}"
    if purpose:
        detail += f" purpose={purpose}"
    if base_url:
        detail += f" base_url={base_url}"
    if provider != "openai":
        detail += f" api_key={'configured' if key_configured else 'none'}"
    if gemini_key_ring_count > 1:
        detail += f" api_key_ring={gemini_key_ring_count}"
    if _status_route_uses_google_gemini(provider=provider, model=model):
        detail += f" google_mode={_status_google_mode(provider=provider, model=model)}"
        service_tier = _status_gemini_service_tier(
            account,
            provider=provider,
            model=model,
            explicit_service_tier=route_service_tier,
        )
        if service_tier:
            detail += f" service_tier={_sanitize_status_text(service_tier)}"
        detail += f" free_tier_guard={_status_gemini_free_tier_guard(account, provider=provider, model=model)}"
        detail += f" google_billing={_status_google_billing(provider=provider)}"
    fallback_count = _status_effective_fallback_count(
        account,
        instructions=instructions,
        provider=provider,
        route_fallback_count=route_fallback_count,
        route_mode=route_mode,
    )
    if fallback_count:
        detail += f" fallback_models={fallback_count}"
        fallback_identity = _status_route_fallback_identity(account, purpose=purpose, route_mode=route_mode)
        if fallback_identity:
            detail += f" {fallback_identity}"
    if route_fallback_api_key_env and fallback_count:
        detail += f" fallback_api_key={'configured' if fallback_key_configured else 'missing'}"
    elif direct_fallback_key_status and fallback_count:
        detail += f" fallback_api_key={direct_fallback_key_status}"
    allow_remote_fallback = _parse_optional_status_bool(getattr(account, "llm_allow_remote_fallback", ""))
    if allow_remote_fallback is not None:
        detail += f" remote_fallback={'enabled' if allow_remote_fallback else 'disabled'}"
    timeout = _effective_llm_text(account, instructions, "llm_timeout_seconds", "llm_timeout_seconds")
    if timeout:
        detail += f" timeout_seconds={timeout}"
    max_tokens = _effective_llm_text(account, instructions, "llm_max_output_tokens", "llm_max_output_tokens")
    if max_tokens:
        detail += f" max_output_tokens={max_tokens}"
    temperature = _effective_llm_text(account, instructions, "llm_temperature", "llm_temperature")
    if temperature:
        detail += f" temperature={temperature}"
    if route_error:
        detail += f" error={_sanitize_status_text(route_error)}"
    return detail


def _runtime_status_memory_index_line(instance_name: str, instructions: Any | None, *, qdrant_ok: bool = False) -> str:
    instance = str(instance_name or "default").strip() or "default"
    if instructions is None:
        return f"memory_index={instance} backend=keyword status=unknown semantic=unknown"
    status = "ready" if bool(getattr(instructions, "user_memory_enabled", False)) else "disabled"
    semantic_enabled = bool(getattr(instructions, "memory_search_semantic_enabled", False))
    semantic_backend = str(getattr(instructions, "memory_search_semantic_backend", "") or "").strip().casefold()
    embedding_error = ""
    if not semantic_enabled:
        semantic = "disabled"
    elif semantic_backend == "qdrant":
        embedding_error = _runtime_account_memory_embedding_config_error(instructions)
        semantic = "invalid" if embedding_error else ("ready" if qdrant_ok else "unavailable")
    else:
        semantic = "unsupported"
    detail = f"memory_index={instance} backend=keyword status={status} semantic={semantic}"
    if semantic_enabled and semantic_backend == "qdrant":
        provider = str(getattr(instructions, "memory_search_embedding_provider", "") or "").strip() or "unknown"
        model = str(getattr(instructions, "memory_search_embedding_model", "") or "").strip() or "unknown"
        dimensions = str(getattr(instructions, "memory_search_embedding_dimensions", "") or "").strip() or "unknown"
        detail += f" embedding_provider={provider} embedding_model={model} embedding_dimensions={dimensions}"
        if embedding_error:
            detail += f" error={_sanitize_status_text(embedding_error)}"
    return detail


def _runtime_qdrant_collection_specs(instructions_by_instance: Mapping[str, Any]) -> tuple[tuple[Any, ...], str]:
    from TeeBotus.runtime.qdrant import default_qdrant_collection_specs

    active_memory_specs: list[tuple[str, int, str]] = []
    embedding_errors: list[tuple[str, str]] = []
    for instance_name, instructions in sorted(instructions_by_instance.items()):
        if instructions is None:
            continue
        semantic_enabled = bool(getattr(instructions, "memory_search_semantic_enabled", False))
        semantic_backend = str(getattr(instructions, "memory_search_semantic_backend", "") or "").strip().casefold()
        if not semantic_enabled or semantic_backend != "qdrant":
            continue
        embedding_error = _runtime_account_memory_embedding_config_error(instructions)
        if embedding_error:
            embedding_errors.append((str(instance_name), embedding_error))
            continue
        dimensions = _positive_status_int(getattr(instructions, "memory_search_embedding_dimensions", 0), default=0)
        model = str(getattr(instructions, "memory_search_embedding_model", "") or "").strip()
        if dimensions <= 0 or not model:
            continue
        active_memory_specs.append((str(instance_name), dimensions, model))
    if embedding_errors:
        errors = ", ".join(f"{instance}:{error}" for instance, error in embedding_errors)
        return default_qdrant_collection_specs(), f"invalid user-memory embedding config: {errors}"
    if not active_memory_specs:
        return default_qdrant_collection_specs(), ""
    unique_specs = {(dimensions, model) for _instance, dimensions, model in active_memory_specs}
    if len(unique_specs) == 1:
        dimensions, model = next(iter(unique_specs))
        return (
            default_qdrant_collection_specs(
                user_memory_vector_size=dimensions,
                user_memory_embedding_model=model,
            ),
            "",
        )
    conflicts = ", ".join(f"{instance}:{model}/{dimensions}" for instance, dimensions, model in active_memory_specs)
    return default_qdrant_collection_specs(), f"conflicting user-memory embedding configs: {conflicts}"


def _runtime_account_memory_embedding_config_error(instructions: Any) -> str:
    try:
        from TeeBotus.embedding.config import EmbeddingConfig, build_account_memory_embedding_provider

        build_account_memory_embedding_provider(
            EmbeddingConfig(
                provider=str(getattr(instructions, "memory_search_embedding_provider", "") or "").strip(),
                model_name=str(getattr(instructions, "memory_search_embedding_model", "") or "").strip(),
                dimensions=_positive_status_int(getattr(instructions, "memory_search_embedding_dimensions", 0), default=64),
                endpoint=str(getattr(instructions, "memory_search_embedding_endpoint", "") or "").strip(),
                api_key_env=str(getattr(instructions, "memory_search_embedding_api_key_env", "") or "").strip(),
            )
        )
    except ValueError as exc:
        return str(exc)
    return ""


def _runtime_qdrant_status_url(instructions_by_instance: Mapping[str, Any]) -> tuple[str, str]:
    from TeeBotus.runtime.qdrant import DEFAULT_QDRANT_URL

    active_urls: list[tuple[str, str, str]] = []
    for instance_name, instructions in sorted(instructions_by_instance.items()):
        if instructions is None:
            continue
        semantic_enabled = bool(getattr(instructions, "memory_search_semantic_enabled", False))
        semantic_backend = str(getattr(instructions, "memory_search_semantic_backend", "") or "").strip().casefold()
        if semantic_enabled and semantic_backend == "qdrant":
            active_urls.append(
                (
                    str(instance_name),
                    "memory",
                    str(getattr(instructions, "memory_search_qdrant_url", "") or DEFAULT_QDRANT_URL).strip() or DEFAULT_QDRANT_URL,
                )
            )
        bibliothekar_enabled = bool(getattr(instructions, "bibliothekar_enabled", True))
        bibliothekar_backend = str(getattr(instructions, "bibliothekar_backend", "") or "").strip().casefold()
        if bibliothekar_enabled and bibliothekar_backend in {"haystack", "qdrant"}:
            active_urls.append(
                (
                    str(instance_name),
                    "bibliothekar",
                    str(getattr(instructions, "bibliothekar_qdrant_url", "") or DEFAULT_QDRANT_URL).strip() or DEFAULT_QDRANT_URL,
                )
            )
    if not active_urls:
        return DEFAULT_QDRANT_URL, ""
    unique_urls = {url for _instance, _purpose, url in active_urls}
    if len(unique_urls) == 1:
        return active_urls[0][2], ""
    conflicts = ", ".join(f"{instance}/{purpose}:{url}" for instance, purpose, url in active_urls)
    return DEFAULT_QDRANT_URL, f"conflicting qdrant urls: {conflicts}"


def _positive_status_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _runtime_status_missing_channel_slot_lines(channels: Sequence[str], instance: Any) -> tuple[str, ...]:
    account_channels = {str(account.channel) for account in getattr(instance, "accounts", ())}
    lines: list[str] = []
    for channel in channels:
        channel_name = str(channel or "").strip().casefold()
        if not channel_name or channel_name in account_channels:
            continue
        label = f"{instance.instance_name}/{channel_name}"
        lines.append(f"runtime_slot={label} status=not_configured reason=missing_{channel_name}_credentials")
        lines.append(f"structured_decision={label} status=not_applicable reason=no_runtime_slot")
    return tuple(lines)


def _runtime_status_structured_decision_line(account: Any, *, instructions: Any | None = None, instruction_error: str = "") -> str:
    label = f"{account.instance_name}/{account.label}"
    if instruction_error:
        return f"structured_decision={label} status=broken error={_sanitize_status_text(instruction_error)}"
    enabled, reason = _structured_decision_enabled_for_status(account, instructions)
    if not enabled:
        detail = f"structured_decision={label} status=disabled reason={reason}"
        return _sanitize_status_text(detail)
    allow_remote_fallback = _parse_optional_status_bool(getattr(account, "llm_allow_remote_fallback", "")) is True
    try:
        from TeeBotus.llm.profiles import select_llm_route

        route = select_llm_route("structured_decision", allow_remote_fallback=allow_remote_fallback)
    except Exception as exc:  # noqa: BLE001 - status should diagnose bad optional routing config.
        return (
            f"structured_decision={label} status=broken route_status=broken "
            f"error={_sanitize_status_text(f'{type(exc).__name__}: {exc}')}"
        )
    route_status, route_error = _runtime_route_status(route)
    detail = (
        f"structured_decision={label} status=enabled source={reason} "
        f"profile={route.profile_name} provider={route.provider} model={route.model} route_status={route_status}"
    )
    if route.fallback_profile_name:
        detail += f" fallback={route.fallback_profile_name} fallback_model={route.fallback_model}"
        if route.fallback_base_url:
            detail += f" fallback_base_url={_sanitize_status_url(route.fallback_base_url)}"
    if allow_remote_fallback:
        detail += " remote_fallback=enabled"
    if route_error:
        detail += f" route_error={_sanitize_status_text(route_error)}"
    return _sanitize_status_text(detail)


def _structured_decision_enabled_for_status(account: Any, instructions: Any | None) -> tuple[bool, str]:
    enabled_override = _parse_optional_status_bool(getattr(account, "llm_enabled", ""))
    if enabled_override is False:
        return False, "runtime_llm_disabled"
    structured_setting = getattr(instructions, "structured_decision_enabled", None) if instructions is not None else None
    if enabled_override is True:
        return True, "runtime_llm_enabled"
    if structured_setting is False:
        return False, "structured_decision_disabled"
    if _has_runtime_llm_route_override(account) or _effective_llm_profile(account, instructions):
        return True, "runtime_llm_configured"
    if structured_setting is True:
        return True, "structured_decision_enabled"
    if instructions is not None and callable(getattr(instructions, "text_llm_enabled", None)):
        if not instructions.text_llm_enabled():
            return False, "text_llm_disabled"
    return True, "text_llm_enabled"


def _status_route_fallback_identity(account: Any, *, purpose: str, route_mode: str) -> str:
    if route_mode != "purpose" or not purpose:
        return ""
    allow_remote_fallback = _parse_optional_status_bool(getattr(account, "llm_allow_remote_fallback", "")) is True
    try:
        from TeeBotus.llm.profiles import select_llm_route

        route = select_llm_route(purpose, allow_remote_fallback=allow_remote_fallback)
    except Exception:
        return ""
    if not route.fallback_model:
        return ""
    parts = [
        f"fallback_profile={route.fallback_profile_name or '<direct>'}",
        f"fallback_model={route.fallback_model}",
    ]
    if route.fallback_base_url:
        parts.append(f"fallback_base_url={_sanitize_status_url(route.fallback_base_url)}")
    return _sanitize_status_text(" ".join(parts))


def _status_llm_route(account: Any, *, instructions: Any | None = None) -> tuple[str, str, str, int, str, str, str, str, str]:
    account_provider = str(getattr(account, "llm_provider", "") or "").strip()
    account_model = str(getattr(account, "llm_model", "") or "").strip()
    account_base_url = str(getattr(account, "llm_base_url", "") or "").strip()
    provider = _status_value(account_provider or _instruction_text(instructions, "llm_provider"), default="openai")
    model = _status_value(account_model or _instruction_text(instructions, "llm_model"), default="<legacy>")
    base_url = _sanitize_status_url(account_base_url or _instruction_text(instructions, "llm_base_url"))
    profile_name = _effective_llm_profile(account, instructions)
    purpose = str(getattr(account, "llm_purpose", "") or "").strip()
    allow_remote_fallback = _parse_optional_status_bool(getattr(account, "llm_allow_remote_fallback", "")) is True
    try:
        if profile_name:
            from TeeBotus.llm.profiles import load_llm_profiles

            profile = load_llm_profiles()[profile_name]
            return (
                profile.provider,
                profile.model,
                _sanitize_status_url(account_base_url) or _sanitize_status_url(profile.base_url),
                0,
                profile.api_key_env,
                "",
                profile.service_tier,
                "",
                "profile",
            )
        if purpose and not (account_provider or account_model):
            from TeeBotus.llm.profiles import select_llm_route

            route = select_llm_route(purpose, allow_remote_fallback=allow_remote_fallback)
            account_fallbacks = str(getattr(account, "llm_fallback_models", "") or "").strip()
            return (
                route.provider,
                route.model,
                _sanitize_status_url(account_base_url) or _sanitize_status_url(route.base_url),
                0 if account_fallbacks else len(route.fallback_models),
                route.api_key_env,
                "" if account_fallbacks else route.fallback_api_key_env,
                route.service_tier,
                "",
                "purpose",
            )
    except Exception as exc:  # noqa: BLE001 - runtime-status should report bad routing config without crashing.
        return provider, model, base_url, 0, "", "", "", f"{type(exc).__name__}: {exc}", "broken"
    service_tier = _effective_llm_text(account, instructions, "llm_service_tier", "llm_service_tier")
    return provider, model, base_url, 0, "", "", service_tier, "", "direct"


def _runtime_status_decision_line(purpose: str, *, instance_names: Sequence[str] = ()) -> str:
    purpose_name = str(purpose or "structured_decision").strip() or "structured_decision"
    try:
        from TeeBotus.llm.profiles import select_llm_route

        route = select_llm_route(purpose_name)
    except Exception as exc:  # noqa: BLE001 - runtime-status should diagnose bad optional routing config.
        return (
            f"llm_route={purpose_name} profile=<unknown> provider=<unknown> model=<unknown> "
            f"status=broken error={_sanitize_status_text(f'{type(exc).__name__}: {exc}')}"
        )
    status, status_error = _runtime_route_status(route, instance_names=instance_names)
    detail = (
        f"llm_route={route.purpose} profile={route.profile_name} provider={route.provider} "
        f"model={route.model} status={status}"
    )
    if route.base_url:
        detail += f" base_url={_sanitize_status_url(route.base_url)}"
    if route.api_key_env:
        detail += f" api_key_env={_sanitize_status_text(route.api_key_env)}"
    gemini_key_ring_count = _status_gemini_key_ring_count_for_instances(instance_names, provider=route.provider, model=route.model)
    if gemini_key_ring_count > 1:
        detail += f" api_key_ring={gemini_key_ring_count}"
    gemini_key_instances = _status_gemini_key_instance_availability(instance_names, provider=route.provider, model=route.model)
    if gemini_key_instances is not None:
        configured_instances, total_instances = gemini_key_instances
        detail += f" api_key_instances={configured_instances}/{total_instances}"
    if _status_route_uses_google_gemini(provider=route.provider, model=route.model):
        detail += f" google_mode={_status_google_mode(provider=route.provider, model=route.model)}"
        service_tier = _status_gemini_service_tier_for_instances(
            instance_names,
            provider=route.provider,
            model=route.model,
            explicit_service_tier=route.service_tier,
        )
        if service_tier:
            detail += f" service_tier={_sanitize_status_text(service_tier)}"
        detail += f" free_tier_guard={_status_gemini_free_tier_guard(types.SimpleNamespace(instance_name=''), provider=route.provider, model=route.model)}"
        detail += f" google_billing={_status_google_billing(provider=route.provider)}"
    if route.fallback_profile_name:
        detail += f" fallback={route.fallback_profile_name} fallback_profile={route.fallback_profile_name} fallback_model={route.fallback_model}"
        if route.fallback_base_url:
            detail += f" fallback_base_url={_sanitize_status_url(route.fallback_base_url)}"
        if route.fallback_api_key_env:
            configured = bool(os.environ.get(route.fallback_api_key_env, "").strip())
            detail += f" fallback_api_key={'configured' if configured else 'missing'}"
    if status_error:
        detail += f" error={_sanitize_status_text(status_error)}"
    return _sanitize_status_text(detail)


def _runtime_status_route_purposes() -> tuple[str, ...]:
    purposes: list[str] = ["structured_decision"]
    seen = {"structured_decision"}
    try:
        from TeeBotus.llm.profiles import load_llm_routing, normalize_llm_purpose

        _default_profile, routing = load_llm_routing()
        for purpose in routing:
            normalized = normalize_llm_purpose(purpose)
            if normalized and normalized not in seen:
                seen.add(normalized)
                purposes.append(normalized)
    except Exception:
        return tuple(purposes)
    return tuple(purposes)


def _runtime_status_api_budget_lines(config: Any, instance_names: Sequence[str]) -> tuple[str, ...]:
    lines: list[str] = []
    try:
        from TeeBotus.llm.profiles import select_llm_route
    except Exception as exc:  # pragma: no cover - defensive status path.
        return (f"api_budget=llm status=broken error={_sanitize_status_text(f'{type(exc).__name__}: {exc}')}",)
    for purpose in _runtime_status_route_purposes():
        try:
            route = select_llm_route(purpose)
        except Exception as exc:  # noqa: BLE001 - status should diagnose bad optional routing config.
            lines.append(
                f"api_budget={_sanitize_status_text(purpose)} provider=<unknown> model=<unknown> "
                f"status=broken error={_sanitize_status_text(f'{type(exc).__name__}: {exc}')}"
            )
            continue
        lines.append(_runtime_status_api_budget_route_line(route, instance_names=instance_names))
    lines.extend(_runtime_status_codex_usage_lines())
    return tuple(lines)


def _runtime_status_api_budget_route_line(route: Any, *, instance_names: Sequence[str]) -> str:
    provider = _normalize_status_llm_provider(getattr(route, "provider", ""))
    model = str(getattr(route, "model", "") or "").strip()
    status, error = _runtime_route_status(route, instance_names=instance_names)
    key_state = _status_api_key_state(route, provider=provider, model=model, instance_names=instance_names)
    detail = (
        f"api_budget={_sanitize_status_text(getattr(route, 'purpose', '') or 'normal_chat')} "
        f"profile={_sanitize_status_text(getattr(route, 'profile_name', '') or '<direct>')} "
        f"provider={provider} model={_sanitize_status_text(model or '<none>')} status={status} "
        f"key={key_state}"
    )
    api_key_env = str(getattr(route, "api_key_env", "") or "").strip()
    if api_key_env:
        detail += f" key_env={_sanitize_status_text(api_key_env)}"
    gemini_key_ring_count = _status_gemini_key_ring_count_for_instances(instance_names, provider=provider, model=model)
    if gemini_key_ring_count > 1:
        detail += f" key_ring={gemini_key_ring_count}"
    gemini_key_instances = _status_gemini_key_instance_availability(instance_names, provider=provider, model=model)
    if gemini_key_instances is not None:
        configured_instances, total_instances = gemini_key_instances
        detail += f" key_instances={configured_instances}/{total_instances}"
    if _status_route_uses_google_gemini(provider=provider, model=model):
        google_billing = _status_google_billing(provider=provider)
        token_source = "provider_usage_response+litellm_response_cost" if google_billing == "paid" else "provider_usage_response+local_free_tier_guard"
        detail += (
            f" google_mode={_status_google_mode(provider=provider, model=model)} "
            f"store={'true' if _status_google_mode(provider=provider, model=model) == 'stateful' else 'false'} "
            f"billing={google_billing} "
            f"limits={_status_gemini_free_tier_guard(types.SimpleNamespace(instance_name=''), provider=provider, model=model)} "
            "costs=provider_billing_not_fetched "
            f"tokens={token_source}"
        )
        service_tier = _status_gemini_service_tier_for_instances(
            instance_names,
            provider=provider,
            model=model,
            explicit_service_tier=str(getattr(route, "service_tier", "") or ""),
        )
        if service_tier:
            detail += f" service_tier={_sanitize_status_text(service_tier)}"
    elif _status_route_is_local(provider=provider, model=model):
        detail += " limits=local costs=local tokens=local_model"
    elif provider == "hf_pool":
        detail += " limits=pool_state costs=target_provider tokens=hf_pool_usage_log"
    else:
        detail += " limits=provider costs=provider_billing_not_fetched tokens=response_usage_when_available"
    fallback_model = str(getattr(route, "fallback_model", "") or "").strip()
    if fallback_model:
        detail += (
            f" fallback_profile={_sanitize_status_text(getattr(route, 'fallback_profile_name', '') or '<direct>')} "
            f"fallback_model={_sanitize_status_text(fallback_model)}"
        )
    if error:
        detail += f" error={_sanitize_status_text(error)}"
    return _sanitize_status_text(detail)


def _status_api_key_state(route: Any, *, provider: str, model: str, instance_names: Sequence[str]) -> str:
    if not _llm_key_required_for_status(
        types.SimpleNamespace(llm_api_key="", openai_api_key=""),
        provider=provider,
        model=model,
        base_url=str(getattr(route, "base_url", "") or ""),
        route_api_key_env=str(getattr(route, "api_key_env", "") or ""),
    ):
        return "not_required"
    gemini_key_instances = _status_gemini_key_instance_availability(instance_names, provider=provider, model=model)
    if gemini_key_instances is not None:
        configured_instances, total_instances = gemini_key_instances
        if configured_instances == total_instances:
            return "configured"
        if configured_instances:
            return "partial"
        return "missing"
    api_key_env = str(getattr(route, "api_key_env", "") or "").strip()
    if api_key_env and os.environ.get(api_key_env, "").strip():
        return "configured"
    return "missing"


def _runtime_status_codex_usage_lines() -> tuple[str, ...]:
    repo = Path(os.environ.get("TEEBOTUS_CODEX_USAGE_REPO", "/home/teladi/codex-usage")).expanduser()
    snapshot_dir = Path(os.environ.get("CODEX_USAGE_STATE_ROOT", Path.home() / ".local" / "share" / "codex-usage")) / "snapshots"
    cli = shutil.which("codex-usage") or str(Path.home() / ".local" / "bin" / "codex-usage")
    cli_path = Path(cli)
    snapshots = _codex_usage_snapshot_payloads(snapshot_dir)
    status = "ready" if repo.is_dir() and cli_path.exists() else "missing"
    latest_at = _latest_codex_usage_capture(snapshots)
    stale_hours = _codex_usage_stale_hours(latest_at)
    line = (
        f"codex_usage=local status={status} repo={repo} cli={cli_path} snapshot_dir={snapshot_dir} "
        f"snapshots={len(snapshots)}"
    )
    if latest_at:
        line += f" latest_at={_status_time_token(latest_at)} stale_hours={stale_hours}"
    lines = [_sanitize_status_text(line)]
    for payload in snapshots[:8]:
        account = _status_token(payload.get("account") or "<unknown>")
        account_status = _status_token(payload.get("status") or "unknown")
        captured_at = _status_time_token(_parse_status_datetime(payload.get("captured_at")))
        five = _codex_usage_window_label(payload.get("five_hour"))
        weekly = _codex_usage_window_label(payload.get("weekly"))
        lines.append(
            _sanitize_status_text(
                f"codex_usage_account={account} status={account_status} captured_at={captured_at} "
                f"five_hour={five} weekly={weekly}"
            )
        )
    return tuple(lines)


def _codex_usage_snapshot_payloads(snapshot_dir: Path) -> list[dict[str, Any]]:
    try:
        paths = sorted(snapshot_dir.glob("*.json"))
    except OSError:
        return []
    payloads: list[dict[str, Any]] = []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    payloads.sort(key=lambda item: str(item.get("captured_at") or ""), reverse=True)
    return payloads


def _latest_codex_usage_capture(payloads: Sequence[Mapping[str, Any]]) -> datetime | None:
    captures = [_parse_status_datetime(payload.get("captured_at")) for payload in payloads]
    captures = [value for value in captures if value is not None]
    return max(captures) if captures else None


def _codex_usage_stale_hours(value: datetime | None) -> int:
    if value is None:
        return -1
    delta = datetime.now(timezone.utc) - value.astimezone(timezone.utc)
    return max(0, int(delta.total_seconds() // 3600))


def _codex_usage_window_label(value: object) -> str:
    if not isinstance(value, Mapping):
        return "none"
    used = _status_number(value.get("used"))
    limit = _status_number(value.get("limit"))
    percent = _status_number(value.get("percent"))
    remaining = _status_number(value.get("remaining"))
    reset = _status_time_token(_parse_status_datetime(value.get("reset_at")))
    parts: list[str] = []
    if used != "unknown" and limit != "unknown":
        parts.append(f"{used}/{limit}")
    elif used != "unknown":
        parts.append(f"used:{used}")
    if percent != "unknown":
        parts.append(f"percent:{percent}")
    if remaining != "unknown":
        parts.append(f"remaining:{remaining}")
    if reset != "unknown":
        parts.append(f"reset:{reset}")
    return ",".join(parts) if parts else "unknown"


def _status_number(value: object) -> str:
    if value is None:
        return "unknown"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "unknown"
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _parse_status_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _status_time_token(value: datetime | None) -> str:
    if value is None:
        return "unknown"
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _status_token(value: object) -> str:
    return re.sub(r"\s+", "_", str(value or "").strip()) or "unknown"


def _runtime_route_status(route: Any, *, instance_names: Sequence[str] = ()) -> tuple[str, str]:
    provider = _normalize_status_llm_provider(getattr(route, "provider", ""))
    if provider != "hf_pool":
        return _runtime_route_key_status(route, instance_names=instance_names)
    try:
        from TeeBotus.llm.hf_pool.config import load_hf_pool_config
        from TeeBotus.llm.hf_pool.scheduler import select_target

        select_target(
            load_hf_pool_config(),
            pool_name=_hf_pool_route_pool_name(str(getattr(route, "model", "") or "")),
            purpose=str(getattr(route, "purpose", "") or "normal_chat"),
            state=_runtime_status_hf_pool_state(),
        )
    except Exception as exc:  # noqa: BLE001 - route status must be diagnostic, not fatal.
        return "unavailable", f"{type(exc).__name__}: {exc}"
    return "configured", ""


def _runtime_status_hf_pool_state_store() -> Any | None:
    try:
        from TeeBotus.llm.hf_pool.state import SQLiteHFPoolRuntimeStateStore, default_hf_pool_state_path

        state_path = default_hf_pool_state_path()
        if not state_path.exists():
            return None
        return SQLiteHFPoolRuntimeStateStore(state_path)
    except Exception:
        return None


def _runtime_status_hf_pool_state() -> Any | None:
    state_store = _runtime_status_hf_pool_state_store()
    if state_store is None:
        return None
    try:
        return state_store.load()
    except Exception:
        return None


def _runtime_route_key_status(route: Any, *, instance_names: Sequence[str] = ()) -> tuple[str, str]:
    provider = _normalize_status_llm_provider(getattr(route, "provider", ""))
    model = str(getattr(route, "model", "") or "")
    api_key_env = str(getattr(route, "api_key_env", "") or "").strip()
    key_required = _llm_key_required_for_status(
        types.SimpleNamespace(llm_api_key="", openai_api_key=""),
        provider=provider,
        model=model,
        base_url=str(getattr(route, "base_url", "") or ""),
        route_api_key_env=api_key_env,
    )
    if not key_required:
        return "configured", ""
    gemini_key_instances = _status_gemini_key_instance_availability(instance_names, provider=provider, model=model)
    if gemini_key_instances is not None:
        configured_instances, total_instances = gemini_key_instances
        if configured_instances == total_instances:
            return "configured", ""
        if configured_instances:
            missing = total_instances - configured_instances
            return "degraded", f"missing api key for {missing}/{total_instances} instances"
        return "missing_key", f"missing api key for all {total_instances} instances"
    if _status_gemini_key_ring_count(instance_name="", provider=provider, model=model):
        return "configured", ""
    api_key_env = str(getattr(route, "api_key_env", "") or "").strip()
    if api_key_env and os.environ.get(api_key_env, "").strip():
        return "configured", ""
    error = f"missing api_key_env {api_key_env}" if api_key_env else "missing api key"
    return "missing_key", error


def _runtime_status_hf_pool_status(
    account: Any,
    *,
    instructions: Any | None,
    provider: str,
    model: str,
    purpose: str,
    route_mode: str,
) -> tuple[str, str]:
    if _normalize_status_llm_provider(provider) != "hf_pool":
        return "", ""
    try:
        if route_mode == "purpose" and purpose:
            from TeeBotus.llm.profiles import select_llm_route

            allow_remote_fallback = _parse_optional_status_bool(getattr(account, "llm_allow_remote_fallback", "")) is True
            route = select_llm_route(purpose, allow_remote_fallback=allow_remote_fallback)
        else:
            route = types.SimpleNamespace(
                provider="hf_pool",
                model=model,
                purpose=_hf_pool_route_purpose(model, fallback=purpose),
            )
    except Exception as exc:  # noqa: BLE001 - runtime-status should diagnose optional routing failures.
        return "unavailable", f"{type(exc).__name__}: {exc}"
    return _runtime_route_status(route)


def _hf_pool_route_pool_name(model: str) -> str:
    text = str(model or "").strip()
    if not text.startswith("pool:"):
        return "default"
    selector = text.removeprefix("pool:")
    return selector.split("#", maxsplit=1)[0].strip() or "default"


def _hf_pool_route_purpose(model: str, *, fallback: str = "") -> str:
    text = str(model or "").strip()
    if text.startswith("pool:") and "#" in text:
        purpose = text.split("#", maxsplit=1)[1].strip()
        if purpose:
            try:
                from TeeBotus.llm.profiles import normalize_llm_purpose

                return normalize_llm_purpose(purpose)
            except Exception:
                return purpose
    return str(fallback or "normal_chat").strip() or "normal_chat"


def _status_value(value: object, *, default: str) -> str:
    text = str(value or "").strip()
    return text if text else default


def _llm_key_configured(
    account: Any,
    provider: str,
    *,
    route_api_key_env: str = "",
    instructions: Any | None = None,
) -> bool:
    if provider == "openai":
        if str(getattr(account, "openai_api_key", "") or "").strip():
            return True
    if str(getattr(account, "llm_api_key", "") or "").strip():
        return True
    if route_api_key_env and os.environ.get(route_api_key_env, "").strip():
        return True
    instruction_api_key_env = _instruction_text(instructions, "llm_api_key_env")
    if provider != "openai" and instruction_api_key_env and os.environ.get(instruction_api_key_env, "").strip():
        return True
    profile_name = _effective_llm_profile(account, instructions)
    if profile_name:
        try:
            from TeeBotus.llm.profiles import load_llm_profiles

            profile = load_llm_profiles()[profile_name]
        except Exception:
            return False
        return bool(profile.api_key_env and os.environ.get(profile.api_key_env, "").strip())
    return False


def _llm_key_required_for_status(
    account: Any,
    *,
    provider: str,
    model: str,
    base_url: str,
    route_api_key_env: str = "",
) -> bool:
    normalized_provider = _normalize_status_llm_provider(provider)
    if normalized_provider == "openai":
        return True
    if normalized_provider in {"ollama", "local_ollama"}:
        return False
    if _status_model_uses_ollama(model):
        return False
    if normalized_provider in {
        "huggingface",
        "hf",
        "groq",
        "gemini",
        "gemini_interactions",
        "litellm_gemini_stateless",
        "litellm_gemini_stateful",
        "litellm_gemini_paid_stateless",
        "litellm_gemini_paid_stateful",
        "vertex_ai",
    }:
        return True
    if normalized_provider == "litellm":
        if route_api_key_env:
            return True
        if _status_model_uses_remote_provider(model):
            return True
        if _status_base_url_is_loopback(base_url):
            return False
        return bool(str(model or "").strip())
    if str(getattr(account, "llm_api_key", "") or "").strip() or route_api_key_env:
        return True
    return False


def _status_model_uses_ollama(model: object) -> bool:
    return str(model or "").strip().casefold().startswith(("ollama/", "ollama_chat/"))


def _status_model_uses_remote_provider(model: object) -> bool:
    value = str(model or "").strip().casefold()
    return value.startswith(
        (
            "openai/",
            "huggingface/",
            "groq/",
            "gemini/",
            "anthropic/",
            "azure/",
            "bedrock/",
            "vertex_ai/",
            "together_ai/",
            "openrouter/",
        )
    )


def _status_base_url_is_loopback(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if "://" not in text and not text.startswith("//"):
        text = f"//{text}"
    try:
        parsed = urlsplit(text)
    except ValueError:
        return False
    return (parsed.hostname or "").strip().casefold() in {"127.0.0.1", "localhost", "::1"}


def _status_effective_fallback_count(
    account: Any,
    *,
    instructions: Any | None = None,
    provider: str,
    route_fallback_count: int,
    route_mode: str = "direct",
) -> int:
    configured_fallbacks = _runtime_fallback_models_text(account, instructions, route_mode=route_mode)
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


def _direct_remote_fallback_key_status(
    account: Any,
    *,
    instructions: Any | None = None,
    provider: str,
    base_url: str,
    key_configured: bool,
    route_mode: str = "direct",
) -> str:
    configured_fallbacks = _runtime_fallback_models_text(account, instructions, route_mode=route_mode)
    if not configured_fallbacks:
        return ""
    allow_remote_fallback = _parse_optional_status_bool(getattr(account, "llm_allow_remote_fallback", "")) is True
    try:
        from TeeBotus.runtime.llm_factory import filter_runtime_fallback_models

        effective_fallbacks = filter_runtime_fallback_models(
            provider=provider,
            fallback_models=configured_fallbacks,
            allow_remote_fallback=allow_remote_fallback,
        )
    except Exception:
        effective_fallbacks = tuple(part.strip() for part in configured_fallbacks.split(",") if part.strip())
    if not any(_status_fallback_model_requires_key(provider=provider, model=model, base_url=base_url) for model in effective_fallbacks):
        return ""
    return "configured" if key_configured else "missing"


def _status_fallback_model_requires_key(*, provider: str, model: object, base_url: str) -> bool:
    normalized_provider = _normalize_status_llm_provider(provider)
    if _status_model_uses_ollama(model):
        return False
    if _status_model_uses_remote_provider(model):
        return True
    if normalized_provider == "litellm":
        return not _status_base_url_is_loopback(base_url)
    return normalized_provider in {
        "openai",
        "huggingface",
        "hf",
        "groq",
        "gemini",
        "gemini_interactions",
        "litellm_gemini_stateless",
        "litellm_gemini_stateful",
        "litellm_gemini_paid_stateless",
        "litellm_gemini_paid_stateful",
        "vertex_ai",
    }


def _status_gemini_key_ring_count(*, instance_name: object, provider: str, model: object) -> int:
    if not _status_route_uses_gemini_api(provider=provider, model=model):
        return 0
    try:
        from TeeBotus.llm.keyring import resolve_gemini_api_key_ring

        return len(resolve_gemini_api_key_ring(instance_name=str(instance_name or "")))
    except Exception:
        return 0


def _status_gemini_key_ring_count_for_instances(instance_names: Sequence[str], *, provider: str, model: object) -> int:
    if not _status_route_uses_gemini_api(provider=provider, model=model):
        return 0
    names = _unique_status_instance_names(instance_names)
    if not names:
        return _status_gemini_key_ring_count(instance_name="", provider=provider, model=model)
    return max((_status_gemini_key_ring_count(instance_name=name, provider=provider, model=model) for name in names), default=0)


def _status_gemini_key_instance_availability(
    instance_names: Sequence[str],
    *,
    provider: str,
    model: object,
) -> tuple[int, int] | None:
    if not _status_route_uses_gemini_api(provider=provider, model=model):
        return None
    names = _unique_status_instance_names(instance_names)
    if not names:
        return None
    configured = sum(1 for name in names if _status_gemini_key_ring_count(instance_name=name, provider=provider, model=model))
    return configured, len(names)


def _unique_status_instance_names(instance_names: Sequence[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in instance_names:
        name = str(value or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        result.append(name)
    return tuple(result)


def _status_gemini_free_tier_guard(account: Any, *, provider: str, model: object) -> str:
    try:
        from TeeBotus.llm.free_tier import resolve_gemini_free_tier_limits

        limits = resolve_gemini_free_tier_limits(
            instance_name=str(getattr(account, "instance_name", "") or ""),
            provider=provider,
            model=str(model or ""),
        )
        return limits.status_summary()
    except Exception:
        return "unknown"


def _status_gemini_service_tier(account: Any, *, provider: str, model: object, explicit_service_tier: str = "") -> str:
    try:
        from TeeBotus.llm.service_tier import resolve_gemini_service_tier

        return resolve_gemini_service_tier(
            instance_name=str(getattr(account, "instance_name", "") or ""),
            provider=provider,
            model=str(model or ""),
            explicit_service_tier=explicit_service_tier,
        )
    except Exception:
        return ""


def _status_gemini_service_tier_for_instances(
    instance_names: Sequence[str],
    *,
    provider: str,
    model: object,
    explicit_service_tier: str = "",
) -> str:
    try:
        from TeeBotus.llm.service_tier import resolve_gemini_service_tier

        if explicit_service_tier:
            return resolve_gemini_service_tier(
                provider=provider,
                model=str(model or ""),
                explicit_service_tier=explicit_service_tier,
            )
        names = tuple(str(name or "").strip() for name in instance_names if str(name or "").strip())
        if not names:
            return resolve_gemini_service_tier(provider=provider, model=str(model or ""))
        tiers = {
            resolve_gemini_service_tier(
                instance_name=name,
                provider=provider,
                model=str(model or ""),
            )
            for name in names
        }
        if len(tiers) == 1:
            return next(iter(tiers))
        if len(tiers) > 1:
            return "mixed"
    except Exception:
        return ""
    return ""


def _status_route_uses_gemini_api(*, provider: str, model: object) -> bool:
    normalized_provider = _normalize_status_llm_provider(provider)
    normalized_model = str(model or "").strip().casefold()
    return normalized_provider in {
        "gemini",
        "gemini_interactions",
        "litellm_gemini_stateless",
        "litellm_gemini_stateful",
        "litellm_gemini_paid_stateless",
        "litellm_gemini_paid_stateful",
    } or normalized_model.startswith("gemini/")


def _status_route_uses_google_gemini(*, provider: str, model: object) -> bool:
    normalized_provider = _normalize_status_llm_provider(provider)
    normalized_model = str(model or "").strip().casefold()
    return normalized_provider in {
        "gemini",
        "gemini_interactions",
        "litellm_gemini_stateless",
        "litellm_gemini_stateful",
        "litellm_gemini_paid_stateless",
        "litellm_gemini_paid_stateful",
        "vertex_ai",
    } or normalized_model.startswith(("gemini/", "vertex_ai/"))


def _status_google_mode(*, provider: str, model: object) -> str:
    normalized_provider = _normalize_status_llm_provider(provider)
    if normalized_provider in {"gemini_interactions", "litellm_gemini_stateful", "litellm_gemini_paid_stateful"}:
        return "stateful"
    return "stateless"


def _status_google_billing(*, provider: object) -> str:
    normalized_provider = _normalize_status_llm_provider(provider)
    if normalized_provider in {"litellm_gemini_paid_stateless", "litellm_gemini_paid_stateful"}:
        return "paid"
    return "free-tier"


def _status_route_is_local(*, provider: str, model: object) -> bool:
    normalized_provider = _normalize_status_llm_provider(provider)
    normalized_model = str(model or "").strip().casefold()
    if normalized_provider in {"ollama", "local_ollama"}:
        return True
    return normalized_model.startswith(("ollama/", "ollama_chat/"))


def _normalize_status_llm_provider(provider: object) -> str:
    try:
        from TeeBotus.llm_client import normalize_llm_provider

        return normalize_llm_provider(str(provider or ""))
    except Exception:
        return str(provider or "").strip().casefold().replace("-", "_")


def _csv_count(value: object) -> int:
    return len([part for part in str(value or "").split(",") if part.strip()])


def _effective_llm_text(account: Any, instructions: Any | None, account_attr: str, instruction_attr: str) -> str:
    account_value = str(getattr(account, account_attr, "") or "").strip()
    if account_value:
        return account_value
    return _instruction_text(instructions, instruction_attr)


def _instruction_text(instructions: Any | None, attr: str) -> str:
    if instructions is None:
        return ""
    value = getattr(instructions, attr, "")
    if isinstance(value, (tuple, list)):
        return ",".join(str(part or "").strip() for part in value if str(part or "").strip())
    return str(value or "").strip()


def _effective_llm_profile(account: Any, instructions: Any | None) -> str:
    account_profile = str(getattr(account, "llm_profile", "") or "").strip()
    if account_profile:
        return account_profile
    if _has_runtime_llm_route_override(account):
        return ""
    return _instruction_text(instructions, "llm_profile")


def _has_runtime_llm_route_override(account: Any) -> bool:
    return any(
        str(getattr(account, attr, "") or "").strip()
        for attr in ("llm_purpose", "llm_provider", "llm_model")
    )


def _runtime_fallback_models_text(account: Any, instructions: Any | None, *, route_mode: str) -> str:
    configured_fallbacks = str(getattr(account, "llm_fallback_models", "") or "").strip()
    if configured_fallbacks:
        return configured_fallbacks
    if route_mode == "direct":
        return _instruction_text(instructions, "llm_fallback_models")
    return ""


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
        r"(?:[a-z][a-z0-9+.-]*://|(?:target|base_url|url)=)[^\s/@:=]+:[^\s/@]+@",
        _status_url_credential_replacement,
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(?<!\S)([A-Za-z0-9_-]*(?:api[_-]?key|access[_-]?token|auth[_-]?token|bearer[_-]?token|token|secret|password)"
        r"[A-Za-z0-9_-]*)\s*([:=])\s*([^,\s)]+)",
        _status_secret_assignment_replacement,
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"([\s=;,])([A-Za-z0-9_-]*(?:api[_-]?key|access[_-]?token|auth[_-]?token|bearer[_-]?token|token|secret|password)"
        r"[A-Za-z0-9_-]*)\s*([:=])\s*([^,\s)]+)",
        _status_secret_assignment_fragment_replacement,
        text,
        flags=re.IGNORECASE,
    )
    return text.replace("\r", " ").replace("\n", " ")


def _sanitize_admin_notify_status_line(value: object) -> str:
    sanitized = _sanitize_status_text(value)
    try:
        from TeeBotus.core.status import redact_status_text
    except Exception:  # pragma: no cover - fallback for import-time constraints.
        return sanitized
    return redact_status_text(sanitized)


def _sanitize_admin_status_output(output: str) -> str:
    text = str(output or "")
    if not text:
        return ""
    return "\n".join(_sanitize_admin_notify_status_line(line) for line in text.split("\n"))


def _status_url_credential_replacement(match: re.Match[str]) -> str:
    value = match.group(0)
    if "://" in value:
        return value.split("://", 1)[0] + "://<redacted>@"
    if "=" in value:
        return value.split("=", 1)[0] + "=<redacted>@"
    return "<redacted>@"


def _status_secret_assignment_replacement(match: re.Match[str]) -> str:
    key = str(match.group(1) or "")
    separator = str(match.group(2) or "=")
    value = str(match.group(3) or "")
    return _status_secret_assignment_text(key, separator, value, original=match.group(0))


def _status_secret_assignment_fragment_replacement(match: re.Match[str]) -> str:
    prefix = str(match.group(1) or "")
    key = str(match.group(2) or "")
    separator = str(match.group(3) or "=")
    value = str(match.group(4) or "")
    original = match.group(0)[len(prefix) :]
    return prefix + _status_secret_assignment_text(key, separator, value, original=original)


def _status_secret_assignment_text(key: str, separator: str, value: str, *, original: str) -> str:
    key_token = key.strip().casefold().replace("-", "_").replace(" ", "_")
    normalized_value = value.strip().strip("\"'`").casefold()
    if normalized_value in {"configured", "none", "missing", "redacted", "<redacted>", "<redacted-secret>"}:
        return original
    if key_token.endswith("_env") and re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", value.strip()):
        return original
    if key_token in {"api_key_ring", "gemini_api_key_ring"} and value.strip().isdigit():
        return original
    if key_token == "api_key_instances" and re.fullmatch(r"\d+/\d+", value.strip()):
        return original
    if key_token in {"tokens", "token_usage", "costs", "limits", "free_tier_guard", "max_output_tokens"}:
        return original
    return f"{key}{separator}<redacted>"


def _runtime_config_from_main_args(args: list[str]) -> Any | None:
    _load_runtime_environment()
    try:
        from TeeBotus.runtime.config import RuntimeConfigError, resolve_runtime_config
    except Exception as exc:  # pragma: no cover - defensive only
        print(f"TeeBotus compatibility error: could not import runtime config: {exc}", file=sys.stderr)
        return None
    runtime_args = []
    unknown_args: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--all":
            runtime_args.append(arg)
            index += 1
            continue
        if arg == "--channels":
            if index + 1 >= len(args) or args[index + 1].startswith("--"):
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
        return resolve_runtime_config(runtime_args)
    except RuntimeConfigError as exc:
        print(f"TeeBotus runtime configuration error: {exc}", file=sys.stderr)
        return None


def _account_storage_preflight_broken_lines(config: Any) -> tuple[str, ...]:
    try:
        from TeeBotus.core.status import account_memory_index_health_lines, account_secret_health_lines
    except Exception as exc:  # pragma: no cover - defensive only
        return (f"account_storage_preflight status=broken error={_sanitize_status_text(f'{type(exc).__name__}: {exc}')}",)
    project_root = config.instances_dir.parent
    broken: list[str] = []
    for instance_name in _account_storage_preflight_instance_names(config):
        for line in (
            *account_secret_health_lines(instance_name=instance_name, project_root=project_root),
            *account_memory_index_health_lines(instance_name=instance_name, project_root=project_root),
        ):
            sanitized = _sanitize_status_text(line)
            if _account_storage_health_line_is_broken(sanitized):
                broken.append(sanitized)
    return tuple(broken)


def _account_storage_preflight_instance_names(config: Any) -> tuple[str, ...]:
    instances_raw = getattr(config, "instances", None)
    if instances_raw is not None:
        return tuple(
            str(getattr(instance, "instance_name", "") or "")
            for instance in instances_raw
            if str(getattr(instance, "instance_name", "") or "").strip() and getattr(instance, "accounts", ())
        )
    selected_raw = getattr(config, "selected_instances", ()) or ()
    return tuple(str(name) for name in selected_raw if str(name or "").strip())


def _account_storage_health_line_is_broken(line: str) -> bool:
    text = str(line or "").strip()
    return bool(text and re.search(r"(^|\s)status=broken(\s|$)", text))


def _allow_broken_account_memory_start() -> bool:
    return str(os.environ.get(ALLOW_BROKEN_ACCOUNT_MEMORY_START_ENV, "") or "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _run_account_storage_preflight(config: Any) -> bool:
    broken_lines = _account_storage_preflight_broken_lines(config)
    if not broken_lines:
        return True
    if _allow_broken_account_memory_start():
        print(
            f"TeeBotus account storage preflight is broken, but {ALLOW_BROKEN_ACCOUNT_MEMORY_START_ENV}=1 allows startup.",
            file=sys.stderr,
        )
        for line in broken_lines:
            print(line, file=sys.stderr)
        return True
    channels = ",".join(str(channel) for channel in getattr(config, "channels", ()) if str(channel or "").strip()) or "telegram,signal,matrix"
    print("TeeBotus account storage preflight failed; refusing to start bot loops.", file=sys.stderr)
    for line in broken_lines:
        print(line, file=sys.stderr)
    print(f"Diagnose: python3 -m TeeBotus --runtime-status --channels {channels}", file=sys.stderr)
    print(f"Emergency override: {ALLOW_BROKEN_ACCOUNT_MEMORY_START_ENV}=1", file=sys.stderr)
    return False


def _runtime_has_signal_accounts(config: Any) -> bool:
    return _runtime_has_channel_accounts(config, "signal")


def _runtime_has_telegram_accounts(config: Any) -> bool:
    return _runtime_has_channel_accounts(config, "telegram")


def _runtime_has_matrix_accounts(config: Any) -> bool:
    return _runtime_has_channel_accounts(config, "matrix")


def _runtime_has_channel_accounts(config: Any, channel: str) -> bool:
    return any(account.channel == channel for instance in config.instances for account in instance.accounts)


def _runtime_channels_explicit(config: Any) -> bool:
    return bool(getattr(config, "channels_explicit", False))


def _runtime_instances_explicit(config: Any) -> bool:
    return bool(getattr(config, "instances_explicit", False))


def _runtime_missing_explicit_instance_errors(config: Any) -> tuple[str, ...]:
    if not _runtime_instances_explicit(config):
        return ()
    errors: list[str] = []
    for instance in getattr(config, "instances", ()) or ():
        instruction_path = Path(getattr(instance, "instruction_path", ""))
        if not instruction_path.exists():
            errors.append(
                f"Instanz {getattr(instance, 'instance_name', '<unknown>')} ist explizit angefordert, "
                f"aber {instruction_path} existiert nicht."
            )
    return tuple(errors)


def _runtime_missing_explicit_channel_errors(config: Any) -> tuple[str, ...]:
    if not _runtime_channels_explicit(config):
        return ()
    messages = {
        "telegram": "Telegram ist angefordert, aber kein TELEGRAM_BOT_TOKEN_<INSTANCE> ist konfiguriert.",
        "signal": "Signal ist angefordert, aber kein SIGNAL_BOT_SERVICE_<INSTANCE> plus SIGNAL_BOT_PHONE_NUMBER_<INSTANCE> ist konfiguriert.",
        "matrix": "Matrix ist angefordert, aber kein MATRIX_BOT_HOMESERVER_<INSTANCE> plus MATRIX_BOT_USER_ID_<INSTANCE> plus MATRIX_BOT_ACCESS_TOKEN_<INSTANCE> ist konfiguriert.",
    }
    return tuple(
        messages[channel]
        for channel in getattr(config, "channels", ())
        if channel in messages and not _runtime_has_channel_accounts(config, channel)
    )


def _channel_requested_without_telegram(config: Any, channel: str) -> bool:
    return channel in config.channels and "telegram" not in config.channels


def _non_telegram_channels(config: Any) -> set[str]:
    return {channel for channel in config.channels if channel != "telegram"}


def _configured_non_telegram_channels(config: Any) -> tuple[str, ...]:
    return tuple(channel for channel in ("matrix", "signal") if channel in config.channels and _runtime_has_channel_accounts(config, channel))


def _runtime_config_for_channels(config: Any, channels: Sequence[str]) -> Any:
    selected_channels = tuple(str(channel) for channel in channels if str(channel or "").strip())
    selected_channel_set = set(selected_channels)
    instances = []
    selected_instances = []
    for instance in getattr(config, "instances", ()):
        accounts = tuple(
            account
            for account in getattr(instance, "accounts", ())
            if str(getattr(account, "channel", "") or "") in selected_channel_set
        )
        if not accounts:
            continue
        instances.append(replace(instance, accounts=accounts))
        selected_instances.append(str(getattr(instance, "instance_name", "") or ""))
    return replace(
        config,
        channels=selected_channels,
        selected_instances=tuple(name for name in selected_instances if name.strip()),
        instances=tuple(instances),
    )


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


def _start_gemini_free_tier_limit_refresh(config: Any) -> None:
    try:
        from TeeBotus.llm.gemini_limits_refresh import start_gemini_free_tier_limit_refresh_background
    except Exception as exc:  # pragma: no cover - defensive only
        print(f"TeeBotus Gemini free-tier refresh unavailable: {exc}", file=sys.stderr)
        return
    try:
        instance_names = tuple(str(instance.instance_name) for instance in getattr(config, "instances", ()))
        start_gemini_free_tier_limit_refresh_background(instance_names=instance_names)
    except Exception as exc:  # noqa: BLE001 - refresh must not block bot startup.
        print(f"TeeBotus Gemini free-tier refresh start failed: {type(exc).__name__}: {_sanitize_status_text(str(exc))}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    original = dict(os.environ)
    try:
        return _main_impl(argv)
    finally:
        os.environ.clear()
        os.environ.update(original)


def _main_impl(argv: list[str] | None = None) -> int:
    """Run TeeBotus through the shared multi-channel runtime entry point."""

    args = list(sys.argv[1:] if argv is None else argv)

    if args and args[0] in {"--version", "version"}:
        print(f"TeeBotus {__version__}")
        return 0

    if args and args[0] in {"--help", "-h", "help"}:
        print(_main_help_text())
        return 0

    if args and args[0] in {"--runtime-status", "runtime-status"}:
        return _runtime_status_preserving_environment(args[1:])

    config = _runtime_config_from_main_args(args)
    if config is None:
        return 2
    missing_explicit_instances = _runtime_missing_explicit_instance_errors(config)
    if missing_explicit_instances:
        for message in missing_explicit_instances:
            print(message, file=sys.stderr)
        return 2
    if "telegram" not in config.channels and len(_non_telegram_channels(config)) != 1:
        print("Mehrkanal-Start ohne Telegram braucht genau einen blockierenden Channel: signal oder matrix.", file=sys.stderr)
        return 2
    missing_explicit_channels = _runtime_missing_explicit_channel_errors(config)
    if missing_explicit_channels:
        for message in missing_explicit_channels:
            print(message, file=sys.stderr)
        return 2
    if "telegram" in config.channels and not _runtime_has_telegram_accounts(config):
        configured_non_telegram = _configured_non_telegram_channels(config)
        if len(configured_non_telegram) == 1 and not _runtime_channels_explicit(config):
            blocking_config = _runtime_config_for_channels(config, configured_non_telegram)
            if not _run_account_storage_preflight(blocking_config):
                return 2
            _start_gemini_free_tier_limit_refresh(blocking_config)
            if configured_non_telegram[0] == "matrix":
                return _run_matrix_runtime(blocking_config)
            return _run_signal_runtime(blocking_config)
        if configured_non_telegram:
            print("Mehrkanal-Start ohne Telegram braucht genau einen blockierenden Channel: signal oder matrix.", file=sys.stderr)
            return 2
        print("Telegram ist angefordert, aber kein TELEGRAM_BOT_TOKEN_<INSTANCE> ist konfiguriert.", file=sys.stderr)
        return 2
    if not _run_account_storage_preflight(config):
        return 2
    if _channel_requested_without_telegram(config, "matrix") and "signal" not in config.channels:
        _start_gemini_free_tier_limit_refresh(config)
        return _run_matrix_runtime(config)
    if _channel_requested_without_telegram(config, "signal") and "matrix" not in config.channels:
        _start_gemini_free_tier_limit_refresh(config)
        return _run_signal_runtime(config)
    if "matrix" in config.channels and _runtime_has_matrix_accounts(config):
        status = _start_matrix_runtime_background(config)
        if status != 0:
            return status
    if "signal" in config.channels and _runtime_has_signal_accounts(config):
        status = _start_signal_runtime_background(config)
        if status != 0:
            return status
    _start_gemini_free_tier_limit_refresh(config)
    if "telegram" in config.channels:
        return _run_telegram_runtime(config)
    return 2


def _runtime_status_preserving_environment(argv: Sequence[str]) -> int:
    original = dict(os.environ)
    try:
        notify_admins, cleaned_argv = _runtime_status_admin_notify_args(argv)
        if not notify_admins:
            return _runtime_status(cleaned_argv)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            status = _runtime_status(cleaned_argv)
        output = stdout.getvalue()
        if output:
            print(output, end="")
        if status == 0:
            _runtime_status_notify_admins(cleaned_argv, output)
        return status
    finally:
        os.environ.clear()
        os.environ.update(original)


def _runtime_status_admin_notify_args(argv: Sequence[str]) -> tuple[bool, tuple[str, ...]]:
    notify = False
    cleaned: list[str] = []
    for arg in argv:
        if arg in {"--notify-admins", "--notify-admins-on-problems", "--admin-notify"}:
            notify = True
            continue
        cleaned.append(arg)
    return notify, tuple(cleaned)


def _runtime_status_notify_admins(argv: Sequence[str], status_output: str) -> None:
    try:
        from TeeBotus.runtime.admin_accounts import (
            format_admin_notification_result_lines,
            notify_runtime_status_admin_accounts,
            runtime_status_problem_lines,
        )
        from TeeBotus.runtime.config import resolve_runtime_config

        sanitized_status_output = _sanitize_admin_status_output(status_output)
        problem_lines = runtime_status_problem_lines(sanitized_status_output)
        config = resolve_runtime_config(argv=list(argv))
        if not problem_lines:
            return
        results = asyncio.run(
            notify_runtime_status_admin_accounts(
                instances_dir=config.instances_dir,
                selected_instances=tuple(instance.instance_name for instance in config.instances),
                problem_lines=problem_lines,
                env=os.environ,
            )
        )
        result_lines = format_admin_notification_result_lines(results)
        print(
            _sanitize_admin_notify_status_line(
                f"admin_notify=runtime_status status=ok count={len(result_lines)}"
            )
        )
    except Exception:  # noqa: BLE001 - notification must not hide runtime-status output.
        print(
            _sanitize_admin_notify_status_line(
                "admin_notify=runtime_status status=failed"
            ),
            file=sys.stderr,
        )


__all__ = ["TelegramBotMissingError", "main"]


def _main_help_text() -> str:
    return "\n".join(
        [
            "Usage: python3 -m TeeBotus [--all] [--channels telegram,signal,matrix]",
            "",
            "Options:",
            "  --version                 Print package version and exit.",
            "  --runtime-status          Print resolved runtime health without starting bot loops.",
            "  --runtime-status --notify-admins",
            "                            Send detected runtime-status warnings/errors to admin accounts.",
            "  --channels CHANNELS       Select channels for runtime-status or startup.",
            "  --all                     Start all configured instances through the runtime entry point.",
            "  --help                    Show this help text and exit.",
        ]
    )

_populate_telegram_exports()
sys.modules[__name__].__class__ = _TelegramBotModule
