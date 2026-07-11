from __future__ import annotations

import contextlib
import hmac
import json
import logging
import os
import re
import shlex
from pathlib import Path
from typing import Any, Mapping, Sequence

from TeeBotus import __version__
from TeeBotus.artifact_outputs import legacy_import_preflight_path
from TeeBotus.core.rich_text import html_with_single_link
from TeeBotus.core.version_notifications import DEFAULT_REPO_URL, github_repo_url
from TeeBotus.llm.free_tier import (
    provider_is_paid_google_gemini,
    provider_is_stateful_google_gemini,
    route_uses_google_gemini,
)
from TeeBotus.llm_client import normalize_llm_provider
from TeeBotus.mcp_tools import DEFAULT_MCP_TOOL_POLICIES, MCPToolPolicy, resolve_mcp_tool_policies
from TeeBotus.runtime.accounts import (
    ACCOUNTS_DIRNAME,
    ACCOUNT_IDENTITIES_FILENAME,
    ACCOUNT_INDEX_FILENAME,
    ACCOUNT_KEYRING_FILENAME,
    ACCOUNT_MEMORY_KEY_PURPOSE,
    ACCOUNT_PROFILE_FILENAME,
    ACCOUNT_SECRETS_FILENAME,
    INSTANCE_KEY_SIZE_BYTES,
    INSTANCE_MAPPING_KEY_PURPOSE,
    INSTANCE_PEPPER_PURPOSE,
    INSTANCE_STATE_ACCOUNT_ID,
    SECRET_VERIFIER_FILENAME,
    TOKEN_HEX_RE,
    AccountStore,
    AccountStoreError,
    EncryptedJsonVault,
    SecretToolInstanceSecretProvider,
    _account_secret_payload_has_verifier,
    _instance_secret_fingerprint,
    _looks_like_teebotus_encrypted_payload,
    _postgres_memory_has_instance_payload_rows,
    _secret_verifier_file_has_payload,
    _sqlite_memory_has_instance_payload_rows,
    telegram_identity_key,
)
from TeeBotus.runtime.artifacts import safe_artifact_name
from TeeBotus.runtime.proactive_agent import proactive_agent_instance_enabled

LOGGER = logging.getLogger("TeeBotus")
USER_MEMORY_INDEX_FILENAME = "User_Memory_Index.json"
USER_MEMORY_ENTRIES_FILENAME = "User_Memory_Entries.jsonl"
ACCOUNT_MEMORY_FILENAMES = frozenset(
    {
        USER_MEMORY_INDEX_FILENAME,
        USER_MEMORY_ENTRIES_FILENAME,
    }
)
STATUS_COMMAND_ALIASES = frozenset(
    {
        "/status",
        "/info",
        "/about",
        "/version",
        "/versions",
        "/programm",
        "/program",
    }
)
STATUS_SECRET_REDACTIONS = (
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"), "sk-<redacted>"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9_-]{8,}\b"), "xox-<redacted>"),
    (re.compile(r"\bsyt_[A-Za-z0-9_=-]{8,}\b"), "syt_<redacted>"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{8,}\b"), "gh_<redacted>"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{12,}\b"), "github_pat_<redacted>"),
    (re.compile(r"\bglpat-[A-Za-z0-9_-]{8,}\b"), "glpat-<redacted>"),
    (re.compile(r"\bhf_[A-Za-z0-9]{8,}\b"), "hf_<redacted>"),
    (re.compile(r"\bgsk_[A-Za-z0-9]{8,}\b"), "gsk_<redacted>"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{16,}\b"), "AIza<redacted>"),
    (
        re.compile(
            r"(?<!\S)([A-Za-z0-9_-]*(?:api[_-]?key|access[_-]?token|auth[_-]?token|bearer[_-]?token|token|secret|password)"
            r"[A-Za-z0-9_-]*)\s*([:=])\s*([^,\s)]+)",
            re.IGNORECASE,
        ),
        r"\1\2<redacted>",
    ),
)
STATUS_URL_CREDENTIAL_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:[A-Za-z][A-Za-z0-9+.-]*://)?[^/\s:@]+:[^/\s@]+@(?=[^\s]+)"
)
CODEX_HISTORY_SUCCESS_STATUSES = frozenset({"accepted", "acknowledged", "delivered", "sent"})


def build_status_reply(
    *,
    sender_id: str = "",
    instance_name: str,
    project_root: Path,
    account_id: str = "",
    account_store: AccountStore | None = None,
    proactive_model_planner: str = "",
    llm_enabled: bool | None = None,
    llm_provider: str = "",
    llm_model: str = "",
    llm_fallback_models: tuple[str, ...] | list[str] | str = (),
    llm_client: object | None = None,
    structured_decision_runner: object | None = None,
    bibliothekar_enabled: bool | None = None,
    mcp_tools: Mapping[str, Mapping[str, Any]] | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    resolved_account_id = _resolve_status_account_id(sender_id=sender_id, account_id=account_id, account_store=account_store)
    account_resolved = bool(resolved_account_id)
    if resolved_account_id and account_store is not None:
        account_dir = _account_memory_dir_from_store(account_store, resolved_account_id)
    elif resolved_account_id:
        account_dir = account_memory_dir_for_account(resolved_account_id, instance_name=instance_name, project_root=project_root)
    else:
        account_dir = account_memory_dir_for_sender(sender_id, instance_name=instance_name, project_root=project_root)
        account_resolved = account_dir is not None
    memory_size = account_memory_payload_size(
        account_store=account_store,
        account_id=resolved_account_id,
        fallback_directory=account_dir,
    )
    encryption_status = memory_encryption_status(account_dir, account_store=account_store, account_id=resolved_account_id)
    commit_history_url = github_commit_history_url(project_root)
    status_name = _status_display_name(instance_name)
    api_budget_lines = _llm_api_budget_status_lines(
        instance_name=instance_name,
        llm_enabled=llm_enabled,
        llm_provider=llm_provider,
        llm_model=llm_model,
        llm_fallback_models=llm_fallback_models,
        llm_client=llm_client,
        structured_decision_runner=structured_decision_runner,
        bibliothekar_enabled=bibliothekar_enabled,
        env=env,
    )
    api_warning_lines = _llm_api_warning_status_lines(
        instance_name=instance_name,
        llm_enabled=llm_enabled,
        llm_provider=llm_provider,
        llm_model=llm_model,
        llm_client=llm_client,
        structured_decision_runner=structured_decision_runner,
        bibliothekar_enabled=bibliothekar_enabled,
        env=env,
    )
    return "\n".join(
        [
            f"{status_name} Status:",
            "",
            "[System]",
            "- Laufzeit: laeuft",
            f"- Version: {__version__} Commits {commit_history_url}",
            "",
            "[Aktive LLMs]",
            *_llm_category_status_lines(
                llm_enabled=llm_enabled,
                llm_provider=llm_provider,
                llm_model=llm_model,
                llm_fallback_models=llm_fallback_models,
                llm_client=llm_client,
                structured_decision_runner=structured_decision_runner,
                bibliothekar_enabled=bibliothekar_enabled,
                env=env,
            ),
            "",
            "[API, Limits und Kosten]",
            *api_budget_lines,
            *api_warning_lines,
            "",
            "[Daten und Memory]",
            f"- Nutzermemory: {_memory_status_text(account_resolved=account_resolved, memory_size=memory_size)}",
            f"- Userfiles: {encryption_status}",
            "",
            *_codex_history_chat_status_lines(account_store=account_store),
            "",
            *mcp_tool_status_lines(mcp_tools or {}),
            "",
            *_proactive_agent_status_lines(
                account_store=account_store,
                account_id=resolved_account_id,
                instance_name=instance_name,
                proactive_model_planner=proactive_model_planner,
                env=env,
            ),
        ]
    )


def build_status_reply_html(text: str, *, project_root: Path) -> str:
    return html_with_single_link(
        text,
        label="Commits",
        url=github_commit_history_url(project_root),
    )


def _llm_category_status_lines(
    *,
    llm_enabled: bool | None,
    llm_provider: str,
    llm_model: str,
    llm_fallback_models: tuple[str, ...] | list[str] | str,
    llm_client: object | None,
    structured_decision_runner: object | None,
    bibliothekar_enabled: bool | None,
    env: Mapping[str, str] | None,
) -> list[str]:
    chat_status = "aktiv" if llm_enabled is True else "aus" if llm_enabled is False else "unbekannt"
    chat_label = _llm_client_status_label(
        llm_client,
        fallback_provider=llm_provider,
        fallback_model=llm_model,
    )
    lines = [
        f"- Chat/Text: {chat_status} - {chat_label}",
        f"- Entscheidungen/Planner: {_structured_decision_status_label(structured_decision_runner)}",
        f"- Bibliothekar/Antworten: {_route_status_label('bibliothekar_answer', enabled=bibliothekar_enabled, env=env)}",
        f"- Ersatzmodelle: {_fallback_category_status(llm_client, llm_fallback_models)}",
    ]
    return [redact_status_text(line) for line in lines]


def _llm_api_budget_status_lines(
    *,
    instance_name: str,
    llm_enabled: bool | None,
    llm_provider: str,
    llm_model: str,
    llm_fallback_models: tuple[str, ...] | list[str] | str,
    llm_client: object | None,
    structured_decision_runner: object | None,
    bibliothekar_enabled: bool | None,
    env: Mapping[str, str] | None,
) -> list[str]:
    del llm_fallback_models
    values = env if env is not None else os.environ
    chat_provider = _first_status_attr(llm_client, "provider_name", "provider", "llm_provider") or llm_provider or "openai"
    chat_model = _first_status_attr(llm_client, "model", "model_name", "model_selector", "llm_model", "pydantic_ai_model_name") or llm_model or "openai-default"
    chat_label = _api_budget_label(
        provider=chat_provider,
        model=chat_model,
        env=values,
        enabled=llm_enabled,
        service_tier=_first_status_attr(llm_client, "service_tier"),
        instance_name=instance_name,
    )
    decision_label = _api_budget_label_for_runner(structured_decision_runner, env=values, instance_name=instance_name)
    bibliothekar_label = _api_budget_label_for_route(
        "bibliothekar_answer",
        enabled=bibliothekar_enabled,
        env=values,
        instance_name=instance_name,
    )
    return [
        redact_status_text(f"- Chat/Text: {chat_label}"),
        redact_status_text(f"- Entscheidungen/Planner: {decision_label}"),
        redact_status_text(f"- Bibliothekar/Antworten: {bibliothekar_label}"),
    ]


def _llm_api_warning_status_lines(
    *,
    instance_name: str,
    llm_enabled: bool | None,
    llm_provider: str,
    llm_model: str,
    llm_client: object | None,
    structured_decision_runner: object | None,
    bibliothekar_enabled: bool | None,
    env: Mapping[str, str] | None,
) -> list[str]:
    values = env if env is not None else os.environ
    warnings: list[str] = []
    seen: set[str] = set()

    chat_provider = _first_status_attr(llm_client, "provider_name", "provider", "llm_provider") or llm_provider or "openai"
    chat_model = _first_status_attr(llm_client, "model", "model_name", "model_selector", "llm_model", "pydantic_ai_model_name") or llm_model
    _append_gemini_stateful_free_tier_warning(
        warnings,
        seen,
        label="Chat/Text",
        provider=chat_provider,
        model=chat_model,
        enabled=llm_enabled,
        env=values,
        instance_name=instance_name,
    )

    if structured_decision_runner is not None:
        decision_provider = _first_status_attr(
            structured_decision_runner,
            "llm_provider",
            "pydantic_ai_provider",
            "provider_name",
            "provider",
        )
        decision_model = _first_status_attr(
            structured_decision_runner,
            "model_name",
            "pydantic_ai_model_name",
            "hf_pool_request_model",
            "llm_model",
        )
        _append_gemini_stateful_free_tier_warning(
            warnings,
            seen,
            label="Entscheidungen/Planner",
            provider=decision_provider,
            model=decision_model,
            enabled=True,
            env=values,
            instance_name=instance_name,
        )

    _append_gemini_stateful_free_tier_route_warning(
        warnings,
        seen,
        label="Bibliothekar/Antworten",
        purpose="bibliothekar_answer",
        enabled=bibliothekar_enabled,
        env=values,
        instance_name=instance_name,
    )
    return [redact_status_text(line) for line in warnings]


def _append_gemini_stateful_free_tier_route_warning(
    warnings: list[str],
    seen: set[str],
    *,
    label: str,
    purpose: str,
    enabled: bool | None,
    env: Mapping[str, str],
    instance_name: str,
) -> None:
    if enabled is False:
        return
    try:
        from TeeBotus.llm.profiles import select_llm_route

        route = select_llm_route(purpose)
    except Exception:
        return
    _append_gemini_stateful_free_tier_warning(
        warnings,
        seen,
        label=label,
        provider=route.provider,
        model=route.model,
        enabled=True,
        env=env,
        instance_name=instance_name,
    )


def _append_gemini_stateful_free_tier_warning(
    warnings: list[str],
    seen: set[str],
    *,
    label: str,
    provider: str,
    model: str,
    enabled: bool | None,
    env: Mapping[str, str],
    instance_name: str,
) -> None:
    if enabled is False:
        return
    resolved_provider = _normalize_status_provider(provider)
    resolved_model = str(model or "").strip()
    if not _provider_is_stateful_gemini(resolved_provider):
        return
    if not _gemini_free_tier_guard_active(provider=resolved_provider, model=resolved_model, env=env, instance_name=instance_name):
        return
    key = f"{resolved_provider}:{resolved_model}"
    if key in seen:
        return
    seen.add(key)
    warnings.append(
        f"- Warnung ({label}): Gemini Stateful + Free-Tier: "
        "Interactions werden mit store=true/previous_interaction_id providerseitig fortgefuehrt "
        "und koennen unter Googles Free-Tier-Interaction-Retention fallen. "
        "Keine sensiblen Inhalte darueber schicken, wenn diese Retention nicht akzeptabel ist."
    )


def _gemini_free_tier_guard_active(*, provider: str, model: str, env: Mapping[str, str], instance_name: str) -> bool:
    try:
        from TeeBotus.llm.free_tier import resolve_gemini_free_tier_limits

        limits = resolve_gemini_free_tier_limits(
            env,
            instance_name=instance_name,
            provider=provider,
            model=model,
        )
    except Exception:
        return True
    return bool(_status_object_attr(limits, "active", False))


def _api_budget_label_for_runner(runner: object | None, *, env: Mapping[str, str], instance_name: str = "") -> str:
    if runner is None:
        return "aus"
    provider = _first_status_attr(runner, "llm_provider", "pydantic_ai_provider", "provider_name", "provider") or "aktiv"
    model = _first_status_attr(runner, "model_name", "pydantic_ai_model_name", "hf_pool_request_model", "llm_model")
    route = _status_object_attr(runner, "llm_route")
    api_key_env = _first_status_attr(route, "api_key_env") or _first_status_attr(runner, "api_key_env", "llm_api_key_env")
    service_tier = _first_status_attr(route, "service_tier") or _first_status_attr(runner, "service_tier")
    return _api_budget_label(
        provider=provider,
        model=model,
        env=env,
        enabled=True,
        api_key_env=api_key_env,
        service_tier=service_tier,
        instance_name=instance_name,
    )


def _api_budget_label_for_route(purpose: str, *, enabled: bool | None, env: Mapping[str, str], instance_name: str = "") -> str:
    if enabled is False:
        return "aus"
    try:
        from TeeBotus.llm.profiles import select_llm_route
        from TeeBotus.llm.service_tier import resolve_gemini_service_tier

        route = select_llm_route(purpose)
        service_tier = resolve_gemini_service_tier(
            env,
            provider=route.provider,
            model=route.model,
            explicit_service_tier=route.service_tier,
        )
        return _api_budget_label(
            provider=route.provider,
            model=route.model,
            env=env,
            enabled=True,
            api_key_env=route.api_key_env,
            service_tier=service_tier,
            instance_name=instance_name,
        )
    except Exception as exc:  # noqa: BLE001 - status should stay diagnostic.
        return f"unbekannt - {type(exc).__name__}: {exc}"


def _api_budget_label(
    *,
    provider: str,
    model: str,
    env: Mapping[str, str],
    enabled: bool | None,
    api_key_env: str = "",
    service_tier: str = "",
    instance_name: str = "",
) -> str:
    if enabled is False:
        return "aus"
    resolved_provider = _normalize_status_provider(provider)
    resolved_model = str(model or "").strip()
    key_env = str(api_key_env or "").strip() or _default_api_key_env(resolved_provider, resolved_model)
    key_label = _api_key_status_label(
        key_env,
        env=env,
        provider=resolved_provider,
        model=resolved_model,
        instance_name=instance_name,
    )
    usage_label = _api_usage_label(provider=resolved_provider, model=resolved_model)
    mode = ""
    if _model_uses_google(resolved_provider, resolved_model):
        mode = "; Google-State: " + ("stateful" if _provider_is_stateful_gemini(resolved_provider) else "stateless")
        mode += "; Google-Billing: " + ("paid" if _provider_is_paid_gemini(resolved_provider) else "free-tier")
    if service_tier:
        mode += f"; service_tier={service_tier}"
    return f"{resolved_provider} / {resolved_model or 'openai-default'}; Key: {key_label}; {usage_label}{mode}"


def _api_key_status_label(key_env: str, *, env: Mapping[str, str], provider: str, model: str, instance_name: str = "") -> str:
    if _model_is_local(provider, model):
        return "nicht noetig"
    if provider == "hf_pool":
        return "ueber Pool/Target"
    if _model_uses_google(provider, model):
        key_ring_size = _gemini_key_ring_size(env, instance_name=instance_name)
        if key_ring_size > 1:
            return f"Gemini-Keyring gesetzt ({key_ring_size})"
        if key_env and str(env.get(key_env, "") or "").strip():
            return f"{key_env} gesetzt"
        if str(env.get("GOOGLE_API_KEY", "") or "").strip():
            return "GOOGLE_API_KEY gesetzt"
        if key_ring_size:
            return f"Gemini-Keyring gesetzt ({key_ring_size})"
        return f"{key_env} fehlt" if key_env else "providerabhaengig"
    if key_env and str(env.get(key_env, "") or "").strip():
        return f"{key_env} gesetzt"
    if not key_env:
        return "providerabhaengig"
    return f"{key_env} fehlt"


def _gemini_key_ring_size(env: Mapping[str, str], *, instance_name: str = "") -> int:
    try:
        from TeeBotus.llm.keyring import resolve_gemini_api_key_ring

        return len(resolve_gemini_api_key_ring(env, instance_name=instance_name))
    except Exception:  # noqa: BLE001 - status output must not fail because optional keyring parsing changed.
        return 0


def _api_usage_label(*, provider: str, model: str) -> str:
    if _model_is_local(provider, model):
        return "Kosten/Limits: lokal; Verbrauch: lokal"
    if _model_uses_google(provider, model):
        if _provider_is_paid_gemini(provider):
            return "Kosten/Limits: Paid/Billing beim Provider; Verbrauch: Provider-Usage + response_cost wenn vorhanden"
        return "Kosten/Limits: Free-Tier-Guard aktiv, Provider-Billing nicht abgefragt; Verbrauch: Guard-Schaetzung + Provider-Usage"
    if provider == "hf_pool":
        return "Kosten/Limits: Pool-Target; Verbrauch: HF-Pool-Usage-Log"
    return "Kosten/Limits: Provider-Billing nicht abgefragt; Verbrauch: Provider-Usage wenn vorhanden"


def _default_api_key_env(provider: str, model: str) -> str:
    normalized_model = str(model or "").strip().casefold()
    if provider == "openai" or normalized_model.startswith("openai/"):
        return "OPENAI_API_KEY"
    if provider == "groq" or normalized_model.startswith("groq/"):
        return "GROQ_API_KEY"
    if provider in {"huggingface", "hf"} or normalized_model.startswith("huggingface/"):
        return "HUGGINGFACE_API_KEY"
    if provider == "vertex_ai" or normalized_model.startswith("vertex_ai/"):
        return "GOOGLE_APPLICATION_CREDENTIALS"
    if route_uses_google_gemini(provider=provider, model=model):
        return "GEMINI_API_KEY"
    return ""


def _normalize_status_provider(value: object) -> str:
    return normalize_llm_provider(str(value or ""))


def _model_is_local(provider: str, model: str) -> bool:
    normalized_model = str(model or "").strip().casefold()
    return provider in {"ollama", "local_ollama"} or normalized_model.startswith(("ollama/", "ollama_chat/"))


def _model_uses_google(provider: str, model: str) -> bool:
    return route_uses_google_gemini(provider=provider, model=model)


def _provider_is_stateful_gemini(provider: str) -> bool:
    return provider_is_stateful_google_gemini(provider)


def _provider_is_paid_gemini(provider: str) -> bool:
    return provider_is_paid_google_gemini(provider)


def _llm_client_status_label(client: object | None, *, fallback_provider: str = "", fallback_model: str = "") -> str:
    provider = _normalize_status_provider(
        _first_status_attr(client, "provider_name", "provider", "llm_provider") or fallback_provider or "openai"
    )
    model = (
        _first_status_attr(client, "model", "model_name", "model_selector", "llm_model", "pydantic_ai_model_name")
        or fallback_model
        or "openai-default"
    )
    label = f"{provider} / {model}"
    service_tier = _first_status_attr(client, "service_tier")
    if service_tier:
        label += f" service_tier={service_tier}"
    return label


def _structured_decision_status_label(runner: object | None) -> str:
    if runner is None:
        return "aus"
    provider = _normalize_status_provider(
        _first_status_attr(runner, "llm_provider", "pydantic_ai_provider", "provider_name", "provider") or "aktiv"
    )
    model = _first_status_attr(runner, "model_name", "pydantic_ai_model_name", "hf_pool_request_model", "llm_model")
    label = f"aktiv - {provider}"
    if model:
        label += f" / {model}"
    fallback = _first_status_attr(runner, "llm_fallback_profile", "llm_fallback_model")
    if fallback:
        label += f" Ersatz bei Planner-Ausfall={fallback}"
    return label


def _route_status_label(purpose: str, *, enabled: bool | None, env: Mapping[str, str] | None) -> str:
    if enabled is False:
        return "aus"
    try:
        from TeeBotus.llm.profiles import select_llm_route
        from TeeBotus.llm.service_tier import resolve_gemini_service_tier

        route = select_llm_route(purpose)
        label = f"aktiv - {_normalize_status_provider(route.provider)} / {route.model}"
        service_tier = resolve_gemini_service_tier(
            env,
            provider=route.provider,
            model=route.model,
            explicit_service_tier=route.service_tier,
        )
        if service_tier:
            label += f" service_tier={service_tier}"
        if route.fallback_model:
            label += f" Ersatz bei Route-/Providerfehler={route.fallback_model}"
        return label
    except Exception as exc:  # noqa: BLE001 - status must stay diagnostic.
        return f"unbekannt - {type(exc).__name__}: {exc}"


def _fallback_category_status(client: object | None, configured_fallbacks: tuple[str, ...] | list[str] | str) -> str:
    runtime_fallbacks = _sequence_status_attr(client, "fallback_models")
    if runtime_fallbacks:
        return "aktiv fuer Chat/Textantworten: " + ", ".join(redact_status_text(model) for model in runtime_fallbacks)
    fallback_client = _status_object_attr(client, "fallback_client")
    if fallback_client is not None:
        return "aktiv fuer Chat/Textantworten: " + _llm_client_status_label(fallback_client)
    fallback_models = _fallback_model_list(configured_fallbacks)
    if fallback_models:
        return "nicht aktiv; bei Chat/Textantwort-Fehlern konfiguriert: " + ", ".join(
            redact_status_text(model) for model in fallback_models
        )
    return "keine (kein aktiver Ersatz fuer Chat/Textantworten)"


def _first_status_attr(obj: object | None, *names: str) -> str:
    if obj is None:
        return ""
    for name in names:
        value = _status_object_attr(obj, name, "")
        if isinstance(value, (tuple, list, set)):
            text = ",".join(str(part or "").strip() for part in value if str(part or "").strip())
        else:
            text = str(value or "").strip()
        if text:
            return text
    return ""


def _sequence_status_attr(obj: object | None, name: str) -> list[str]:
    if obj is None:
        return []
    value = _status_object_attr(obj, name, ())
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (tuple, list, set)):
        return [str(part or "").strip() for part in value if str(part or "").strip()]
    return []


def _status_object_attr(obj: object, name: str, default: object = None) -> object:
    try:
        return getattr(obj, name, default)
    except Exception:  # noqa: BLE001 - optional runtime objects must not break status.
        LOGGER.debug("Failed to read status attribute %s from %s.", name, type(obj).__name__, exc_info=True)
        return default


def _llm_enabled_status(value: bool | None) -> str:
    if value is None:
        return "unbekannt"
    return "ja" if value else "nein"


def _safe_status_value(value: str, *, default: str) -> str:
    text = str(value or "").strip()
    return redact_status_text(text) if text else default


def _fallback_model_count(value: object) -> str:
    return str(len(_fallback_model_list(value)))


def _fallback_model_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (tuple, list, set)):
        return [str(part or "").strip() for part in value if str(part or "").strip()]
    return []


def _fallback_model_status(value: object) -> str:
    models = _fallback_model_list(value)
    if not models:
        return "keine (kein Ersatzmodell fuer Chat/Textantworten konfiguriert)"
    return f"{len(models)} fuer Chat/Textantworten konfiguriert (" + ", ".join(redact_status_text(model) for model in models) + ")"


def mcp_tool_status_lines(mcp_tools: Mapping[str, Mapping[str, Any]] | None = None) -> list[str]:
    if mcp_tools is not None and not isinstance(mcp_tools, Mapping):
        return ["MCP Tools", "- Konfiguration: ungueltig (Mapping erwartet)"]
    configured = {str(name or "").strip().casefold(): config for name, config in (mcp_tools or {}).items() if str(name or "").strip()}
    allowed: list[str] = []
    guarded: list[str] = []
    disabled: list[str] = []
    resolved = resolve_mcp_tool_policies(configured)
    for name, policy in sorted(resolved.items()):
        if _mcp_policy_directly_callable(policy):
            allowed.append(_mcp_tool_status_label(name, policy))
        elif policy.enabled and policy.read_only:
            guarded.append(_mcp_tool_status_label(name, policy))
        elif not policy.enabled:
            disabled.append(name)
        else:
            disabled.append(f"{name} (nicht read-only)")
    ignored = sorted(redact_status_text(name) for name in configured if name not in DEFAULT_MCP_TOOL_POLICIES)
    lines = [
        "MCP Tools",
        f"- Read-only allowlist: {', '.join(allowed) if allowed else 'keine'}",
    ]
    if guarded:
        lines.append(f"- Nur mit Schutz: {', '.join(guarded)}")
    if disabled:
        lines.append(f"- Deaktiviert: {', '.join(disabled)}")
    if ignored:
        lines.append(f"- Ignoriert: {', '.join(ignored)}")
    return lines


def mcp_tool_runtime_status_line(instance_name: str, mcp_tools: Mapping[str, Mapping[str, Any]] | None = None) -> str:
    lines = mcp_tool_status_lines(mcp_tools)
    details = " ".join(line.removeprefix("- ") for line in lines[1:])
    return f"mcp_tools={instance_name} {details}"


def codex_history_status_lines(
    *,
    instance_name: str,
    account_store: AccountStore | None = None,
    project_root: Path | None = None,
    secret_provider: object | None = None,
) -> list[str]:
    if account_store is None and project_root is None:
        return []
    try:
        safe_instance_name = _safe_instance_name_for_accounts(instance_name)
    except ValueError:
        return [f"codex_history={_status_field_value(instance_name)} status=unknown error=invalid_instance_name"]
    if account_store is None:
        root = project_root.resolve() / "instances" / safe_instance_name / "data" / "accounts"
        if not root.exists():
            return [
                (
                    f"codex_history={_status_field_value(safe_instance_name)} status=ok "
                    "queued=0 failed=0 total=0 latest_repo=<none> latest_prefix=<none> latest_kind=<none> "
                    "run_summaries=0 strategies=0 graphs=0 other=0"
                )
            ]
        try:
            account_store = AccountStore(
                root,
                safe_instance_name,
                secret_provider=secret_provider or SecretToolInstanceSecretProvider(create_if_missing=False),
                create_dirs=False,
            )
        except Exception as exc:  # noqa: BLE001 - runtime-status should diagnose store/key mismatches.
            return [
                (
                    f"codex_history={_status_field_value(safe_instance_name)} status=unknown "
                    f"error={_status_field_value(f'{type(exc).__name__}: {exc}')}"
                )
            ]
    summary = _codex_history_summary(account_store)
    if summary.get("error"):
        return [
            (
                f"codex_history={_status_field_value(safe_instance_name)} status=unknown "
                f"error={_status_field_value(summary['error'])}"
            )
        ]
    lines = [
        (
            f"codex_history={_status_field_value(safe_instance_name)} status={summary['status']} "
            f"queued={summary['queued']} failed={summary['failed']} total={summary['total']} "
            f"latest_repo={_status_field_value(summary['latest_repo'])} "
            f"latest_prefix={_status_field_value(summary['latest_prefix'])} "
            f"latest_kind={_status_field_value(summary['latest_kind'])} "
            f"run_summaries={summary['run_summaries']} strategies={summary['strategies']} "
            f"graphs={summary['graphs']} other={summary['other']}"
        )
    ]
    for repo in summary.get("repos", []):
        if not isinstance(repo, Mapping):
            continue
        lines.append(
            (
                f"codex_history_repo={_status_field_value(safe_instance_name)} "
                f"repo={_status_field_value(repo.get('repo_name', '<none>'))} "
                f"status={repo.get('status', 'unknown')} "
                f"queued={repo.get('queued', 0)} failed={repo.get('failed', 0)} total={repo.get('total', 0)} "
                f"run_summaries={repo.get('run_summaries', 0)} strategies={repo.get('strategies', 0)} "
                f"graphs={repo.get('graphs', 0)} other={repo.get('other', 0)} "
                f"latest_prefix={_status_field_value(repo.get('latest_prefix', '<none>'))} "
                f"latest_status={_status_field_value(repo.get('latest_status', '<none>'))} "
                f"latest_kind={_status_field_value(repo.get('latest_kind', '<none>'))} "
                f"latest_title={_status_field_value(repo.get('latest_title', '<none>'))}"
            )
        )
    return lines


def _codex_history_chat_status_lines(*, account_store: AccountStore | None) -> list[str]:
    if account_store is None:
        return []
    summary = _codex_history_summary(account_store)
    if summary.get("error"):
        return [
            "[Projekt-History]",
            f"- Codex-History: status=unknown error={redact_status_text(summary['error'])}",
        ]
    latest = ""
    if summary["latest_repo"] != "<none>" or summary["latest_prefix"] != "<none>":
        latest = f" latest={summary['latest_repo']} {summary['latest_prefix']}"
    return [
        "[Projekt-History]",
        (
            f"- Codex-History: status={summary['status']} queued={summary['queued']} "
            f"failed={summary['failed']} total={summary['total']}{latest}"
        ),
    ]


def _codex_history_summary(account_store: AccountStore) -> dict[str, Any]:
    try:
        rows = account_store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
    except Exception as exc:  # noqa: BLE001 - status should diagnose unreadable history without crashing.
        return {"error": redact_status_text(f"{type(exc).__name__}: {exc}")}
    valid_rows = [row for row in rows if isinstance(row, Mapping)]
    malformed_rows = max(0, len(rows) - len(valid_rows))
    status_counts: dict[str, int] = {}
    for row in valid_rows:
        status = str(row.get("status") or "unknown").strip().casefold() or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
    queued = status_counts.get("queued", 0)
    failed = status_counts.get("failed", 0)
    latest = valid_rows[-1] if valid_rows else {}
    project = latest.get("project", {}) if isinstance(latest, Mapping) else {}
    if not isinstance(project, Mapping):
        project = {}
    latest_repo = redact_status_text(project.get("repo_name") or "<none>") or "<none>"
    latest_prefix = redact_status_text(latest.get("summary_prefix") or "<none>") if isinstance(latest, Mapping) else "<none>"
    if not latest_prefix:
        latest_prefix = "<none>"
    latest_kind = _codex_history_kind(latest) if valid_rows else "<none>"
    kind_counts = _codex_history_kind_counts(valid_rows)
    has_problem_status = malformed_rows > 0 or any(status not in CODEX_HISTORY_SUCCESS_STATUSES for status in status_counts)
    return {
        "status": "warning" if has_problem_status else "ok",
        "queued": queued,
        "failed": failed,
        "total": len(rows),
        "latest_repo": latest_repo,
        "latest_prefix": latest_prefix,
        "latest_kind": latest_kind,
        **kind_counts,
        "repos": _codex_history_repo_summaries(valid_rows),
    }


def _codex_history_repo_summaries(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        project = row.get("project", {})
        if not isinstance(project, Mapping):
            project = {}
        repo_name = redact_status_text(project.get("repo_name") or "<none>") or "<none>"
        repo_key = str(project.get("repo_id") or repo_name).strip() or repo_name
        status = str(row.get("status") or "unknown").strip().casefold() or "unknown"
        entry = grouped.setdefault(
            repo_key,
            {
                "repo_name": repo_name,
                "queued": 0,
                "failed": 0,
                "total": 0,
                "latest_prefix": "<none>",
                "latest_status": "<none>",
                "latest_kind": "<none>",
                "latest_title": "<none>",
                "run_summaries": 0,
                "strategies": 0,
                "graphs": 0,
                "other": 0,
                "problem": False,
            },
        )
        entry["total"] += 1
        if status not in CODEX_HISTORY_SUCCESS_STATUSES:
            entry["problem"] = True
        if status == "queued":
            entry["queued"] += 1
        elif status == "failed":
            entry["failed"] += 1
        summary = row.get("summary", {})
        if not isinstance(summary, Mapping):
            summary = {}
        kind = _codex_history_kind(row)
        if kind == "codex_run_summary":
            entry["run_summaries"] += 1
        elif kind == "codex_strategy_analysis":
            entry["strategies"] += 1
        elif kind == "codex_graph_artifact":
            entry["graphs"] += 1
        else:
            entry["other"] += 1
        entry["latest_prefix"] = redact_status_text(row.get("summary_prefix") or "<none>") or "<none>"
        entry["latest_status"] = status
        entry["latest_kind"] = kind
        entry["latest_title"] = redact_status_text(summary.get("title") or "<none>") or "<none>"
    result = []
    for entry in grouped.values():
        entry["status"] = "warning" if entry.pop("problem", False) else "ok"
        result.append(entry)
    return sorted(result, key=lambda item: str(item.get("repo_name") or "").casefold())


def _codex_history_kind_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = {"run_summaries": 0, "strategies": 0, "graphs": 0, "other": 0}
    for row in rows:
        kind = _codex_history_kind(row)
        if kind == "codex_run_summary":
            counts["run_summaries"] += 1
        elif kind == "codex_strategy_analysis":
            counts["strategies"] += 1
        elif kind == "codex_graph_artifact":
            counts["graphs"] += 1
        else:
            counts["other"] += 1
    return counts


def _codex_history_kind(row: Mapping[str, Any]) -> str:
    kind = str(row.get("kind") or "").strip()
    if not kind:
        return "codex_run_summary"
    return redact_status_text(kind).strip() or "unknown"


def _status_field_value(value: object) -> str:
    text = redact_status_text(value).strip()
    if not text:
        return "<none>"
    return re.sub(r"\s+", "_", text)


def account_identity_health_lines(
    *,
    instance_name: str,
    project_root: Path,
    env: Mapping[str, str] | None = None,
    runtime_channels: tuple[str, ...] = ("telegram", "signal", "matrix"),
    secret_provider: object | None = None,
) -> list[str]:
    if not instance_name:
        return []
    try:
        safe_instance_name = _safe_instance_name_for_accounts(instance_name)
    except ValueError:
        return [f"account_identity={redact_status_text(instance_name)} status=unknown error=invalid_instance_name"]
    try:
        from TeeBotus.admin.accounts_report import build_accounts_admin_report

        report = build_accounts_admin_report(
            instances_dir=project_root.resolve() / "instances",
            instances=(safe_instance_name,),
            provider=secret_provider or SecretToolInstanceSecretProvider(create_if_missing=False),
            env=os.environ if env is None else env,
            runtime_channels=runtime_channels,
        )
    except Exception as exc:  # noqa: BLE001 - runtime-status should diagnose identity health failures.
        return [f"account_identity={safe_instance_name} status=unknown error={redact_status_text(f'{type(exc).__name__}: {exc}')}"]
    raw_instances = report.get("instances", []) if isinstance(report, Mapping) else []
    instances = raw_instances if isinstance(raw_instances, (list, tuple)) else []
    instance_report = next(
        (
            item
            for item in instances
            if isinstance(item, Mapping) and str(item.get("instance") or "") == safe_instance_name
        ),
        None,
    )
    if not isinstance(instance_report, Mapping):
        return [f"account_identity={safe_instance_name} status=none"]
    store_report = instance_report.get("account_store", {})
    runtime_slots = instance_report.get("runtime_slots", {})
    identity_health = instance_report.get("identity_health", {})
    if isinstance(store_report, Mapping) and store_report.get("errors"):
        errors = "; ".join(str(error or "").strip() for error in store_report.get("errors", []) if str(error or "").strip())
        return [f"account_identity={safe_instance_name} status=broken error={redact_status_text(errors)}"]
    status = (
        _health_status_token(identity_health.get("status"))
        if isinstance(identity_health, Mapping)
        else "unknown"
    )
    warning_count = (
        _status_integer_label(identity_health.get("warning_count", 0))
        if isinstance(identity_health, Mapping)
        else "0"
    )
    lines = [
        (
            f"account_identity={safe_instance_name} status={status} "
            f"identity_warnings={warning_count} "
            f"runtime_slots={_runtime_status_count_label(runtime_slots.get('configured_channels', {}) if isinstance(runtime_slots, Mapping) else {})} "
            f"identities={_runtime_status_count_label(store_report.get('identities_by_channel', {}) if isinstance(store_report, Mapping) else {})}"
        )
    ]
    if isinstance(identity_health, Mapping):
        for warning in identity_health.get("warnings", []) if isinstance(identity_health.get("warnings"), list) else []:
            if not isinstance(warning, Mapping):
                continue
            lines.append(
                (
                    f"account_identity_warning={safe_instance_name} "
                    f"code={redact_status_text(warning.get('code', 'unknown'))} "
                    f"channel={redact_status_text(warning.get('channel', '<none>'))} "
                    f"configured_runtime_slots={redact_status_text(warning.get('configured_runtime_slots', '<none>'))} "
                    f"runtime_labels={_runtime_status_sequence_label(warning.get('configured_runtime_labels', []))} "
                    f"identity_channels={_runtime_status_count_label(warning.get('identity_channels', {}))} "
                    f"message={redact_status_text(warning.get('message', ''))} "
                    f"action={redact_status_text(warning.get('recommended_action', ''))}"
                )
            )
    return lines


def account_secret_health_lines(*, instance_name: str, project_root: Path, secret_provider: object | None = None) -> list[str]:
    if not instance_name:
        return []
    try:
        safe_instance_name = _safe_instance_name_for_accounts(instance_name)
    except ValueError:
        return [f"account_crypto={redact_status_text(instance_name)} status=unknown error=invalid_instance_name"]
    root = project_root.resolve() / "instances" / safe_instance_name / "data" / "accounts"
    if not root.exists():
        return [f"account_crypto={safe_instance_name} status=none"]
    provider = secret_provider or SecretToolInstanceSecretProvider(create_if_missing=False)
    presence: dict[str, bool | None] = {}
    presence_errors: dict[str, str] = {}
    purposes = (
        ("mapping", INSTANCE_MAPPING_KEY_PURPOSE),
        ("memory", ACCOUNT_MEMORY_KEY_PURPOSE),
        ("pepper", INSTANCE_PEPPER_PURPOSE),
    )
    for label, purpose in purposes:
        try:
            presence[label] = _account_secret_provider_has_secret(provider, safe_instance_name, purpose)
        except Exception as exc:  # noqa: BLE001 - runtime-status should diagnose secret-service failures.
            presence[label] = None
            presence_errors[label] = redact_status_text(f"{type(exc).__name__}: {exc}")
    try:
        required = {
            "mapping": _account_secret_mapping_required(root),
            "memory": _account_secret_memory_required(root, safe_instance_name),
            "pepper": _account_secret_pepper_required(root, safe_instance_name, provider, mapping_present=presence.get("mapping") is True),
        }
    except Exception as exc:  # noqa: BLE001 - runtime-status should diagnose secret-health failures.
        return [f"account_crypto={safe_instance_name} status=broken error={redact_status_text(f'{type(exc).__name__}: {exc}')}"]
    _confirm_required_secret_presence(provider, safe_instance_name, purposes, presence, required)
    keyring_label, keyring_errors = _account_secret_keyring_health(root, safe_instance_name, provider, required=required)
    labels: dict[str, str] = {}
    errors: list[str] = list(keyring_errors)
    for label, _purpose in purposes:
        current = presence.get(label)
        if current is True:
            labels[label] = "present"
        elif current is None:
            labels[label] = "error"
            errors.append(f"{label}:{presence_errors.get(label, 'lookup failed')}")
        elif required[label]:
            labels[label] = "missing_required"
            errors.append(f"{label}:missing")
        else:
            labels[label] = "not_required"
    status = "broken" if errors else "ok"
    line = (
        f"account_crypto={safe_instance_name} status={status} "
        f"mapping={labels['mapping']} memory={labels['memory']} pepper={labels['pepper']} keyring={keyring_label}"
    )
    if errors:
        line += f" error={redact_status_text('; '.join(errors))}"
    return [line]


def _confirm_required_secret_presence(
    provider: object,
    instance_name: str,
    purposes: tuple[tuple[str, str], ...],
    presence: dict[str, bool | None],
    required: Mapping[str, bool],
) -> None:
    for label, purpose in purposes:
        if presence.get(label) is not False or not required.get(label):
            continue
        try:
            _account_secret_provider_get_secret(provider, instance_name, purpose)
        except Exception:  # noqa: BLE001 - keep the original missing status below.
            continue
        presence[label] = True


def _account_secret_provider_has_secret(provider: object, instance_name: str, purpose: str) -> bool:
    has_secret = getattr(provider, "has_secret", None)
    if callable(has_secret):
        return bool(has_secret(instance_name, purpose))
    get_secret = getattr(provider, "get_secret", None)
    if not callable(get_secret):
        raise AccountStoreError("secret provider has no has_secret or get_secret method")
    try:
        secret = get_secret(instance_name, purpose)
    except AccountStoreError as exc:
        if "missing" in str(exc).casefold():
            return False
        raise
    return bool(secret)


def _account_secret_provider_get_secret(provider: object, instance_name: str, purpose: str) -> bytes:
    get_secret = getattr(provider, "get_secret", None)
    if not callable(get_secret):
        raise AccountStoreError("secret provider has no get_secret method")
    secret = get_secret(instance_name, purpose)
    if not isinstance(secret, (bytes, bytearray)):
        raise AccountStoreError("secret provider returned non-byte secret")
    resolved = bytes(secret)
    if len(resolved) != INSTANCE_KEY_SIZE_BYTES:
        raise AccountStoreError("instance secret has invalid length")
    return resolved


def _account_secret_keyring_health(
    root: Path,
    instance_name: str,
    provider: object,
    *,
    required: Mapping[str, bool],
) -> tuple[str, list[str]]:
    manifest_path = root / ACCOUNT_KEYRING_FILENAME
    required_purposes = {
        "mapping": INSTANCE_MAPPING_KEY_PURPOSE,
        "memory": ACCOUNT_MEMORY_KEY_PURPOSE,
        "pepper": INSTANCE_PEPPER_PURPOSE,
    }
    any_required = any(bool(required.get(label)) for label in required_purposes)
    if not manifest_path.exists():
        if any_required:
            return ("broken", ["keyring:missing_manifest"])
        return ("not_required", [])
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return ("broken", [f"keyring:{type(exc).__name__}:invalid_manifest"])
    if not isinstance(manifest, Mapping):
        return ("broken", ["keyring:invalid_manifest"])
    if manifest.get("schema_version") != 1:
        return ("broken", ["keyring:unsupported_schema"])
    manifest_instance = str(manifest.get("instance") or "").strip()
    if manifest_instance and manifest_instance != instance_name:
        return ("broken", ["keyring:wrong_instance"])
    purposes = manifest.get("purposes")
    if not isinstance(purposes, Mapping):
        return ("broken", ["keyring:invalid_purposes"])
    errors: list[str] = []
    recorded_purposes: set[str] = set()
    for purpose, payload in purposes.items():
        purpose_token = str(purpose or "").strip()
        if not purpose_token:
            errors.append("keyring:empty_purpose")
            continue
        recorded_purposes.add(purpose_token)
        if not isinstance(payload, Mapping):
            errors.append(f"keyring:{purpose_token}:invalid_payload")
            continue
        expected_fingerprint = str(payload.get("fingerprint") or "").strip()
        if not expected_fingerprint:
            errors.append(f"keyring:{purpose_token}:missing_fingerprint")
            continue
        try:
            secret = _account_secret_provider_get_secret(provider, instance_name, purpose_token)
            actual_fingerprint = _instance_secret_fingerprint(instance_name, purpose_token, secret)
        except Exception as exc:  # noqa: BLE001 - runtime-status should diagnose keyring failures.
            errors.append(f"keyring:{purpose_token}:{type(exc).__name__}: {exc}")
            continue
        if not hmac.compare_digest(expected_fingerprint, actual_fingerprint):
            errors.append(f"keyring:{purpose_token}:mismatch")
    if errors:
        return ("broken", [redact_status_text(error) for error in errors])
    missing_recorded = [
        purpose
        for label, purpose in required_purposes.items()
        if required.get(label) and purpose not in recorded_purposes
    ]
    if missing_recorded:
        missing = ",".join(sorted(missing_recorded))
        return ("partial", [f"keyring:missing_required_purpose:{missing}"])
    if recorded_purposes:
        return ("ok", [])
    return ("not_recorded" if any_required else "not_required", [])


def _account_secret_mapping_required(root: Path) -> bool:
    paths = [
        root / ACCOUNT_INDEX_FILENAME,
        root / ACCOUNT_IDENTITIES_FILENAME,
        root / ACCOUNT_SECRETS_FILENAME,
    ]
    accounts_dir = root / ACCOUNTS_DIRNAME
    if accounts_dir.exists():
        try:
            account_dirs = [path for path in accounts_dir.iterdir() if path.is_dir()]
        except OSError:
            account_dirs = []
        for account_dir in account_dirs:
            paths.extend(
                [
                    account_dir / ACCOUNT_PROFILE_FILENAME,
                    account_dir / SECRET_VERIFIER_FILENAME,
                    account_dir / "Account_Tombstone.json",
                ]
            )
    return any(_looks_like_teebotus_encrypted_payload(path, allowed_roots=(root,)) for path in paths)


def _account_secret_memory_required(root: Path, instance_name: str) -> bool:
    accounts_dir = root / ACCOUNTS_DIRNAME
    if accounts_dir.exists():
        for account_dir in _account_memory_account_dirs(accounts_dir):
            for filename in ACCOUNT_MEMORY_FILENAMES | {"LLM_State.json", "OpenAI_State.json", "Agent_State.json", "Proactive_Outbox.jsonl", "Proactive_Audit.jsonl", "Proactive_Dispatch_Results.jsonl"}:
                if _looks_like_teebotus_encrypted_payload(account_dir / filename, allowed_roots=(root,)):
                    return True
    try:
        from TeeBotus.runtime.sqlite_memory import SQLITE_DEFAULT_FALLBACK_FILENAME, SQLITE_DEFAULT_FILENAME, SQLiteMemoryConfig

        sqlite_paths: list[Path] = []
        sqlite_config = SQLiteMemoryConfig.from_env(root)
        if sqlite_config is not None:
            sqlite_paths.append(sqlite_config.path)
            if sqlite_config.fallback_path is not None:
                sqlite_paths.append(sqlite_config.fallback_path)
        sqlite_paths.append(root / SQLITE_DEFAULT_FILENAME)
        sqlite_paths.append(root / SQLITE_DEFAULT_FALLBACK_FILENAME)
        seen: set[str] = set()
        for path in sqlite_paths:
            marker = str(path)
            if marker in seen:
                continue
            seen.add(marker)
            if _sqlite_memory_has_instance_payload_rows(path, instance_name):
                return True
    except Exception as exc:  # noqa: BLE001 - status should report bad backend inspection.
        raise AccountStoreError(f"could not inspect SQLite account-memory secrets: {exc}") from exc
    try:
        from TeeBotus.runtime.postgres_memory import PostgresMemoryConfig

        postgres_config = PostgresMemoryConfig.from_env()
        if postgres_config is not None and _postgres_memory_has_instance_payload_rows(
            postgres_config.dsn,
            instance_name,
            postgres_config.connect_timeout,
        ):
            return True
    except ModuleNotFoundError:
        return False
    except Exception as exc:  # noqa: BLE001 - status should report bad backend inspection.
        raise AccountStoreError(f"could not inspect PostgreSQL account-memory secrets: {exc}") from exc
    return False


def _account_secret_pepper_required(
    root: Path,
    instance_name: str,
    provider: object,
    *,
    mapping_present: bool,
) -> bool:
    accounts_dir = root / ACCOUNTS_DIRNAME
    if accounts_dir.exists():
        for account_dir in _account_memory_account_dirs(accounts_dir):
            if _secret_verifier_file_has_payload(account_dir / SECRET_VERIFIER_FILENAME, allowed_roots=(root,)):
                return True
    secrets_path = root / ACCOUNT_SECRETS_FILENAME
    if not secrets_path.exists() or not mapping_present:
        return False
    try:
        secrets_doc = EncryptedJsonVault(instance_name, provider, root=root).read_json(secrets_path, {})
    except AccountStoreError:
        return _looks_like_teebotus_encrypted_payload(secrets_path, allowed_roots=(root,))
    return any(_account_secret_payload_has_verifier(payload) for payload in secrets_doc.values())


def _runtime_status_count_label(value: Any) -> str:
    if not isinstance(value, Mapping):
        return "<none>"
    parts = []
    for key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
        name = str(key or "").strip()
        if not name:
            continue
        try:
            count = str(max(0, int(item)))
        except (TypeError, ValueError):
            count = "unknown"
        parts.append(f"{name}:{count}")
    return ",".join(parts) if parts else "<none>"


def _status_integer_label(value: object) -> str:
    try:
        return str(max(0, int(value)))
    except (TypeError, ValueError, OverflowError):
        return "unknown"


def _health_status_token(value: object) -> str:
    token = str(value or "").strip().casefold()
    return token if token in {"ok", "warning", "broken", "unknown"} else "unknown"


def _runtime_status_sequence_label(value: Any) -> str:
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",") if part.strip()]
    elif isinstance(value, (list, tuple, set)):
        parts = [str(part or "").strip() for part in value if str(part or "").strip()]
    else:
        parts = []
    return ",".join(redact_status_text(part) for part in parts) if parts else "<none>"


def redact_status_text(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for pattern, replacement in STATUS_SECRET_REDACTIONS:
        text = pattern.sub(replacement, text)
    text = STATUS_URL_CREDENTIAL_RE.sub(_redacted_status_url_credentials, text)
    return text.replace("\r", " ").replace("\n", " ")


def _redacted_status_url_credentials(match: re.Match[str]) -> str:
    value = match.group(0)
    if "://" not in value:
        return ""
    return value.split("://", maxsplit=1)[0] + "://"


def _mcp_tool_status_label(name: str, policy: MCPToolPolicy) -> str:
    suffixes: list[str] = []
    if policy.private_chat_only:
        suffixes.append("private")
    if policy.requires_confirmation:
        suffixes.append("confirm")
    if policy.requires_admin:
        suffixes.append("admin")
    if policy.sandbox_required:
        suffixes.append("sandbox")
    return f"{name} ({', '.join(suffixes)})" if suffixes else name


def _mcp_policy_directly_callable(policy: MCPToolPolicy) -> bool:
    return policy.enabled and policy.read_only and not policy.requires_confirmation and not policy.requires_admin and not policy.sandbox_required


def _status_display_name(instance_name: str) -> str:
    return redact_status_text(instance_name) or "TeeBotus"


def _safe_instance_name_for_accounts(instance_name: str) -> str:
    text = str(instance_name or "").strip()
    if not text:
        raise ValueError("instance_name must not be empty")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in text):
        raise ValueError("instance_name contains invalid control characters")
    if text in {".", ".."} or "/" in text or "\\" in text:
        raise ValueError("instance_name must be a single path segment")
    return text


def _memory_status_text(*, account_resolved: bool, memory_size: int | None) -> str:
    if not account_resolved:
        return "Account nicht zugeordnet"
    if memory_size is None:
        return "nicht verfuegbar (Memory-Backend-Fehler)"
    return format_byte_size(memory_size)


def _resolve_status_account_id(*, sender_id: str, account_id: str, account_store: AccountStore | None) -> str:
    if account_id:
        candidate = str(account_id).strip().lower()
        return candidate if TOKEN_HEX_RE.fullmatch(candidate) else ""
    if account_store is None or not sender_id:
        return ""
    try:
        return account_store.get_account_for_identity(telegram_identity_key(sender_id)) or ""
    except (AccountStoreError, OSError):
        LOGGER.exception("Failed to resolve account id for status.")
        return ""


def _account_memory_dir_from_store(account_store: AccountStore, account_id: str) -> Path | None:
    try:
        account_dir = account_store.account_dir(account_id)
    except (AccountStoreError, OSError):
        LOGGER.exception("Failed to resolve account memory directory from store.")
        return None
    return account_dir if account_dir.is_dir() else None


def _proactive_agent_status_lines(
    *,
    account_store: AccountStore | None,
    account_id: str,
    instance_name: str,
    proactive_model_planner: str,
    env: Mapping[str, str] | None,
) -> list[str]:
    scheduler_enabled = proactive_agent_instance_enabled(instance_name, env=env or os.environ)
    planner = _proactive_model_planner_status(proactive_model_planner)
    if account_store is None or not account_id:
        return [
            "Proactive Agent",
            "- Agent enabled: unbekannt",
            "- Outbox queued: unbekannt",
            "- Review pending: unbekannt",
            "- Outbox dispatching: unbekannt",
            f"- Scheduler enabled: {'ja' if scheduler_enabled else 'nein'}",
            f"- Model planner: {planner}",
        ]
    try:
        state = account_store.read_agent_state(account_id)
        outbox = account_store.read_proactive_outbox(account_id)
    except (AccountStoreError, OSError):
        LOGGER.exception("Failed to read proactive agent status.")
        return [
            "Proactive Agent",
            "- Agent enabled: Fehler beim Lesen",
            "- Outbox queued: Fehler beim Lesen",
            "- Review pending: Fehler beim Lesen",
            "- Outbox dispatching: Fehler beim Lesen",
            f"- Scheduler enabled: {'ja' if scheduler_enabled else 'nein'}",
            f"- Model planner: {planner}",
        ]
    proactive = state.get("proactive") if isinstance(state, dict) else {}
    if not isinstance(proactive, dict):
        proactive = {}
    enabled = bool(proactive.get("enabled"))
    paused = bool(proactive.get("paused"))
    queued = sum(1 for item in outbox if isinstance(item, dict) and str(item.get("status") or "queued").strip().casefold() == "queued")
    review_pending = sum(1 for item in outbox if isinstance(item, dict) and str(item.get("status") or "").strip().casefold() == "review_pending")
    dispatching = sum(1 for item in outbox if isinstance(item, dict) and str(item.get("status") or "").strip().casefold() == "dispatching")
    return [
        "Proactive Agent",
        f"- Agent enabled: {'ja' if enabled else 'nein'}",
        f"- Agent paused: {'ja' if paused else 'nein'}",
        f"- Outbox queued: {queued}",
        f"- Review pending: {review_pending}",
        f"- Outbox dispatching: {dispatching}",
        f"- Scheduler enabled: {'ja' if scheduler_enabled else 'nein'}",
        f"- Model planner: {planner}",
    ]


def _proactive_model_planner_status(value: str) -> str:
    planner = str(value or "").strip().casefold()
    if planner in {"tool", "llm", "none"}:
        return planner
    return "unbekannt"


def github_commit_history_url(project_root: Path) -> str:
    repo_url = github_repo_url(project_root)
    if not repo_url:
        repo_url = DEFAULT_REPO_URL
    return f"{repo_url.rstrip('/')}/commits/main"


def github_release_log_url(project_root: Path | None = None) -> str:
    repo_url = github_repo_url(project_root) if project_root is not None else DEFAULT_REPO_URL
    if not repo_url:
        repo_url = DEFAULT_REPO_URL
    return f"{repo_url.rstrip('/')}/releases"


def account_memory_dir_for_account(account_id: str, *, instance_name: str, project_root: Path) -> Path | None:
    if not account_id or not instance_name:
        return None
    try:
        safe_instance_name = _safe_instance_name_for_accounts(instance_name)
    except ValueError:
        return None
    safe_account_id = str(account_id or "").strip()
    if not TOKEN_HEX_RE.fullmatch(safe_account_id):
        return None
    account_dir = project_root / "instances" / safe_instance_name / "data" / "accounts" / "accounts" / safe_account_id
    return account_dir if account_dir.is_dir() else None


def account_memory_dir_for_sender(sender_id: str, *, instance_name: str, project_root: Path) -> Path | None:
    if not sender_id or not instance_name:
        return None
    try:
        safe_instance_name = _safe_instance_name_for_accounts(instance_name)
    except ValueError:
        return None
    try:
        store = AccountStore(
            project_root / "instances" / safe_instance_name / "data" / "accounts",
            safe_instance_name,
            secret_provider=SecretToolInstanceSecretProvider(create_if_missing=False),
            create_dirs=False,
        )
        account_id = store.get_account_for_identity(telegram_identity_key(sender_id))
    except (AccountStoreError, OSError):
        LOGGER.exception("Failed to resolve account memory directory for status.")
        return None
    if not account_id:
        return None
    return account_memory_dir_for_account(account_id, instance_name=safe_instance_name, project_root=project_root)


def memory_files_size(directory: Path | None) -> int | None:
    if directory is None or not directory.exists():
        return 0
    total = 0
    try:
        for path in directory.rglob("*"):
            try:
                if not path.is_file() or path.name not in ACCOUNT_MEMORY_FILENAMES:
                    continue
                total += path.stat().st_size
            except OSError:
                LOGGER.exception("Failed to inspect user memory file %s.", path)
                return None
    except OSError:
        LOGGER.exception("Failed to list user memory files in %s.", directory)
        return None
    return total


def account_memory_payload_size(*, account_store: AccountStore | None, account_id: str, fallback_directory: Path | None) -> int | None:
    if account_store is not None and account_id:
        try:
            backend = account_store.account_memory_backend
        except (AccountStoreError, OSError):
            LOGGER.exception("Failed to resolve account memory backend for status size.")
            return None
        try:
            entries = account_store.read_memory_entries(account_id)
            index = account_store.read_memory_index(account_id)
        except (AccountStoreError, OSError):
            LOGGER.exception("Failed to read account memory payload size from store.")
            return None
        else:
            backend_error = ""
            if backend is not None:
                backend_error = str(
                    getattr(backend, "last_entry_read_error", "")
                    or getattr(backend, "last_index_read_error", "")
                    or ""
                ).strip()
            if backend_error:
                LOGGER.error("Account memory backend returned partial data for status size: %s", backend_error)
                return None
            payload: dict[str, Any] = {"entries": entries}
            if index:
                payload["index"] = index
            try:
                raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            except (TypeError, ValueError, OverflowError, RecursionError):
                LOGGER.exception("Failed to serialize account memory payload for status size.")
                return None
            return len(raw)
    return memory_files_size(fallback_directory)


def memory_encryption_status(directory: Path | None, *, account_store: AccountStore | None = None, account_id: str = "") -> str:
    if account_store is not None and account_id:
        try:
            backend = account_store.account_memory_backend
        except (AccountStoreError, OSError):
            LOGGER.exception("Failed to resolve account memory backend encryption status.")
            return "Datenbank-Backend nicht verfuegbar"
        if backend is not None:
            return "Datenbank-Backend, Payloads verschluesselt"
    if directory is None or not directory.exists():
        return "kein Account-Memory gefunden"
    structured_files = [directory / USER_MEMORY_INDEX_FILENAME, directory / USER_MEMORY_ENTRIES_FILENAME]
    existing_structured = [path for path in structured_files if path.exists()]
    if not existing_structured:
        return "keine strukturierten Userfiles"
    states = [_encrypted_payload_state(path) for path in existing_structured]
    if any(state is None for state in states):
        return "Userfiles nicht verfuegbar (Lesefehler)"
    if all(state is True for state in states):
        return "Userfiles verschluesselt"
    return "Userfiles nicht vollstaendig verschluesselt"


def account_memory_index_health_lines(*, instance_name: str, project_root: Path, secret_provider: object | None = None) -> list[str]:
    if not instance_name:
        return []
    try:
        safe_instance_name = _safe_instance_name_for_accounts(instance_name)
    except ValueError:
        return [
            f"account_memory={redact_status_text(instance_name)} status=unknown error=invalid_instance_name"
        ]
    project_root = project_root.resolve()
    root = project_root / "instances" / safe_instance_name / "data" / "accounts"
    try:
        account_dirs = _account_memory_account_dirs(root / ACCOUNTS_DIRNAME)
    except (AccountStoreError, OSError) as exc:
        error = redact_status_text(f"{type(exc).__name__}: {exc}")
        return [
            f"account_memory={safe_instance_name} status=broken error=account_directories_unreadable:{error}",
            *_account_memory_recovery_lines(instance_name=safe_instance_name, project_root=project_root),
        ]
    try:
        store = AccountStore(
            root,
            safe_instance_name,
            secret_provider=secret_provider or SecretToolInstanceSecretProvider(create_if_missing=False),
            create_dirs=False,
            memory_backend_enabled=_status_memory_backend_enabled(root),
        )
    except Exception as exc:
        error = redact_status_text(f"{type(exc).__name__}: {exc}")
        lines = [f"account_memory={safe_instance_name} status=broken error={error}"]
        for account_dir in account_dirs:
            lines.append(f"account_memory={safe_instance_name}/{account_dir.name} status=broken error=account_store_unavailable:{error}")
        lines.extend(_account_memory_recovery_lines(instance_name=safe_instance_name, project_root=project_root))
        return lines
    lines: list[str] = []
    has_broken_memory = False
    has_broken_metadata = False
    metadata_lines = _account_metadata_health_lines(store, account_dirs, instance_name=safe_instance_name)
    if metadata_lines:
        lines.extend(metadata_lines)
        has_broken_metadata = True
    instance_fallback_warning = _account_memory_fallback_warning(store, INSTANCE_STATE_ACCOUNT_ID)
    if instance_fallback_warning:
        lines.append(f"account_memory={safe_instance_name}/__instance_state status=warning{instance_fallback_warning}")
    if not account_dirs:
        if has_broken_metadata:
            lines.extend(_account_memory_recovery_lines(instance_name=safe_instance_name, project_root=project_root))
        return lines or [f"account_memory={safe_instance_name} status=none"]
    for account_dir in account_dirs:
        account_id = account_dir.name
        profile_error = ""
        require_resolvable = True
        try:
            store._read_account_profile(account_id)
        except AccountStoreError as exc:
            profile_error = f"profile_unreadable:{redact_status_text(exc)}"
            has_broken_metadata = True
        except OSError as exc:
            profile_error = f"profile_unreadable:{redact_status_text(exc)}"
            has_broken_metadata = True
        try:
            with _suppress_expected_account_memory_health_logs():
                health = store.check_structured_memory_index(account_id, require_resolvable=require_resolvable and not profile_error)
        except AccountStoreError as exc:
            lines.append(
                f"account_memory={safe_instance_name}/{account_id} status=broken "
                f"error={redact_status_text(exc)}"
            )
            has_broken_memory = True
            continue
        except OSError as exc:
            lines.append(
                f"account_memory={safe_instance_name}/{account_id} status=broken "
                f"error={redact_status_text(exc)}"
            )
            has_broken_memory = True
            continue
        fallback_warning = _account_memory_fallback_warning(store, account_id)
        if health.ok:
            if profile_error:
                lines.append(f"account_memory={safe_instance_name}/{account_id} status=broken error={profile_error}{fallback_warning}")
                has_broken_memory = True
            else:
                lines.append(f"account_memory={safe_instance_name}/{account_id} status=ok{fallback_warning}")
        else:
            errors = list(health.errors)
            if profile_error:
                errors.insert(0, profile_error)
            lines.append(
                f"account_memory={safe_instance_name}/{account_id} status=broken "
                f"error={redact_status_text('; '.join(errors))}{fallback_warning}"
            )
            has_broken_memory = True
    if has_broken_memory or has_broken_metadata:
        lines.extend(_account_memory_recovery_lines(instance_name=safe_instance_name, project_root=project_root))
    return lines


def _status_memory_backend_enabled(root: Path) -> bool:
    try:
        from TeeBotus.runtime.sqlite_memory import SQLiteMemoryConfig

        sqlite_config = SQLiteMemoryConfig.from_env(root)
    except Exception:  # noqa: BLE001 - status must stay diagnostic.
        return True
    if sqlite_config is None:
        return True
    sqlite_paths = [sqlite_config.path]
    if sqlite_config.fallback_path is not None:
        sqlite_paths.append(sqlite_config.fallback_path)
    return any(path.exists() for path in sqlite_paths)


def _account_memory_recovery_lines(*, instance_name: str, project_root: Path) -> list[str]:
    instances_dir = project_root / "instances"
    recovery_command = shlex.join(
        [
            "python3",
            "-m",
            "TeeBotus.admin",
            "memory-recovery",
            "--instances-dir",
            str(instances_dir),
            "--instances",
            instance_name,
        ]
    )
    lines = [f'account_memory_recovery={instance_name} status=needed command="{recovery_command}"']
    legacy = _find_legacy_plaintext_backup(project_root=project_root, instance_name=instance_name)
    if legacy:
        legacy_artifact_name = safe_artifact_name(instance_name, default="instance")
        legacy_preflight_json = legacy_import_preflight_path(legacy_artifact_name, ext=".json")
        legacy_preflight_md = legacy_import_preflight_path(legacy_artifact_name, ext=".md")
        legacy_command = shlex.join(
            [
                "python3",
                "scripts/import_legacy_user_memory.py",
                "--legacy-instances-dir",
                str(legacy["requested_path"]),
                "--target-instances-dir",
                str(instances_dir),
                "--instance",
                instance_name,
                "--replace-unreadable",
                "--replace-unreadable-account-metadata",
                "--json-output",
                str(legacy_preflight_json),
                "--markdown-output",
                str(legacy_preflight_md),
            ]
        )
        legacy_apply_command = shlex.join(
            [
                "python3",
                "scripts/import_legacy_user_memory.py",
                "--legacy-instances-dir",
                str(legacy["requested_path"]),
                "--target-instances-dir",
                str(instances_dir),
                "--instance",
                instance_name,
                "--replace-unreadable",
                "--replace-unreadable-account-metadata",
                "--apply",
            ]
        )
        lines.append(
            f'account_memory_recovery_legacy={instance_name} status=available '
            f'sources={legacy["sources"]} entries={legacy["entries"]} path={legacy["effective_path"]} '
            f'command="{legacy_command}" apply_command="{legacy_apply_command}"'
        )
    return lines


def _account_metadata_health_lines(store: AccountStore, account_dirs: list[Path], *, instance_name: str) -> list[str]:
    root = getattr(store, "root", None)
    vault = getattr(store, "vault", None)
    if not isinstance(root, Path) or vault is None or not hasattr(vault, "read_json"):
        return []
    checks = (
        ("account_index", root / ACCOUNT_INDEX_FILENAME),
        ("identity_mapping", root / ACCOUNT_IDENTITIES_FILENAME),
        ("account_secrets", root / ACCOUNT_SECRETS_FILENAME),
    )
    lines: list[str] = []
    for kind, path in checks:
        if not path.exists():
            continue
        try:
            vault.read_json(path, {})
        except (AccountStoreError, OSError) as exc:
            lines.append(_account_metadata_broken_line(instance_name=instance_name, kind=kind, path=path, error=str(exc)))

    unreadable_profiles: list[str] = []
    profile_errors: list[str] = []
    for account_dir in account_dirs:
        profile_path = account_dir / ACCOUNT_PROFILE_FILENAME
        if not profile_path.exists():
            continue
        try:
            vault.read_json(profile_path, {})
        except (AccountStoreError, OSError) as exc:
            unreadable_profiles.append(account_dir.name)
            profile_errors.append(str(exc))
    if unreadable_profiles:
        accounts = ",".join(account_id[:12] for account_id in unreadable_profiles[:5])
        if len(unreadable_profiles) > 5:
            accounts += f",+{len(unreadable_profiles) - 5}"
        error = profile_errors[0] if profile_errors else "unreadable account profile"
        lines.append(
            _account_metadata_broken_line(
                instance_name=instance_name,
                kind="accounts_dir",
                path=store.accounts_dir,
                error=error,
                extra=f" accounts={accounts}",
            )
        )
    return lines


def _account_metadata_broken_line(*, instance_name: str, kind: str, path: Path, error: str, extra: str = "") -> str:
    return (
        f"account_memory_metadata={instance_name} status=broken item={kind} "
        f"path={path}{extra} error={redact_status_text(error)}"
    )


def _account_memory_fallback_warning(store: AccountStore, account_id: str) -> str:
    try:
        backend = store.account_memory_backend
    except (AccountStoreError, OSError) as exc:
        LOGGER.exception("Failed to resolve account memory backend fallback status.")
        detail = redact_status_text(exc)
        suffix = f":{detail}" if detail else ""
        return f" warning=memory_backend_unavailable{suffix}"
    if backend is None:
        return ""
    stale_entries = set(getattr(backend, "stale_fallback_entry_account_ids", ()) or ())
    stale_indexes = set(getattr(backend, "stale_fallback_index_account_ids", ()) or ())
    stale_collections = set(getattr(backend, "stale_fallback_collection_account_ids", ()) or ())
    stale_parts: list[str] = []
    if account_id in stale_entries:
        stale_parts.append("entries")
    if account_id in stale_indexes:
        stale_parts.append("index")
    if account_id in stale_collections:
        stale_parts.append("collections")
    if not stale_parts:
        return ""
    error_for_account = getattr(backend, "fallback_sync_error_for_account", None)
    if callable(error_for_account):
        error = redact_status_text(str(error_for_account(account_id) or ""))
    else:
        error = redact_status_text(getattr(backend, "last_fallback_sync_error", "") or "")
    suffix = f":{error}" if error else ""
    return f" warning=fallback_sync_stale:{'+'.join(stale_parts)}{suffix}"


@contextlib.contextmanager
def _suppress_expected_account_memory_health_logs():
    previous_disabled = LOGGER.disabled
    LOGGER.disabled = True
    try:
        yield
    finally:
        LOGGER.disabled = previous_disabled


def _account_memory_account_dirs(accounts_dir: Path) -> list[Path]:
    try:
        if not accounts_dir.exists():
            return []
        children = list(accounts_dir.iterdir())
        return sorted(
            path
            for path in children
            if path.is_dir()
            and TOKEN_HEX_RE.fullmatch(path.name)
            and not (path / "Account_Tombstone.json").exists()
            and not _account_memory_account_dir_is_stale(path)
        )
    except OSError as exc:
        LOGGER.exception("Failed to list account memory directories.")
        raise AccountStoreError(f"could not list account memory directories: {exc}") from exc


def _account_memory_account_dir_is_stale(account_dir: Path) -> bool:
    try:
        saw_file = False
        for path in account_dir.iterdir():
            if not path.is_file():
                return False
            saw_file = True
            if not path.name.endswith(".lock"):
                return False
        return saw_file
    except OSError:
        LOGGER.exception("Failed to inspect account memory account directory.")
        return False


def _find_legacy_plaintext_backup(*, project_root: Path, instance_name: str) -> dict[str, str | int] | None:
    candidates: list[dict[str, str | int]] = []
    env_path = os.environ.get("TEEBOTUS_LEGACY_INSTANCES_DIR", "").strip()
    if env_path:
        candidate = _legacy_plaintext_backup_candidate(Path(env_path).expanduser(), instance_name)
        if candidate:
            candidates.append(candidate)
    try:
        sibling_candidates = sorted(project_root.parent.glob(f"{project_root.name}.bak*"))
    except OSError:
        sibling_candidates = []
    for path in sibling_candidates:
        candidate = _legacy_plaintext_backup_candidate(path, instance_name)
        if candidate:
            candidates.append(candidate)
    backup_collection = project_root.parent / f"{project_root.name}_Backups"
    try:
        collection_candidates = sorted(backup_collection.glob(f"{project_root.name}*")) if backup_collection.exists() else []
    except OSError:
        collection_candidates = []
    for path in collection_candidates:
        candidate = _legacy_plaintext_backup_candidate(path, instance_name)
        if candidate:
            candidates.append(candidate)
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (
            int(item["entries"]),
            int(item["sources"]),
            _legacy_backup_priority(str(item["effective_path"])),
            _requested_backup_priority(str(item["requested_path"])),
        ),
    )


def _legacy_plaintext_backup_candidate(path: Path, instance_name: str) -> dict[str, str | int] | None:
    effective_path = _resolve_legacy_backup_instances_dir(path, instance_name)
    users_dir = effective_path / instance_name / "data" / "users"
    if not users_dir.exists():
        return None
    sources = 0
    entries = 0
    try:
        user_dirs = sorted(user_dir for user_dir in users_dir.iterdir() if user_dir.is_dir())
    except OSError:
        return None
    for user_dir in user_dirs:
        source_entries = _count_plaintext_legacy_entries(user_dir / USER_MEMORY_ENTRIES_FILENAME)
        if source_entries <= 0:
            continue
        sources += 1
        entries += source_entries
    if sources <= 0:
        return None
    return {
        "requested_path": str(path),
        "effective_path": str(effective_path),
        "sources": sources,
        "entries": entries,
    }


def _resolve_legacy_backup_instances_dir(path: Path, instance_name: str) -> Path:
    if (path / instance_name / "data" / "users").exists():
        return path
    candidates: list[tuple[int, int, str, Path]] = []
    try:
        children = sorted(path.iterdir()) if path.exists() and path.is_dir() else []
    except OSError:
        children = []
    for child in children:
        if not child.is_dir() or not child.name.startswith("instances"):
            continue
        users_dir = child / instance_name / "data" / "users"
        if not users_dir.exists():
            continue
        sources = 0
        entries = 0
        try:
            user_dirs = sorted(user_dir for user_dir in users_dir.iterdir() if user_dir.is_dir())
        except OSError:
            continue
        for user_dir in user_dirs:
            source_entries = _count_plaintext_legacy_entries(user_dir / USER_MEMORY_ENTRIES_FILENAME)
            if source_entries <= 0:
                continue
            sources += 1
            entries += source_entries
        if sources:
            candidates.append((entries, sources, child.name, child))
    if not candidates:
        return path
    candidates.sort(key=lambda item: (item[0], item[1], _legacy_backup_priority(item[2])), reverse=True)
    return candidates[0][3]


def _count_plaintext_legacy_entries(path: Path) -> int:
    if not path.exists():
        return 0
    entries = 0
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return 0
    for line in lines:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return 0
        if not isinstance(data, dict):
            return 0
        if {"version", "nonce", "ciphertext"}.issubset(data):
            return 0
        entries += 1
    return entries


def _legacy_backup_priority(name: str) -> int:
    path_name = Path(name).name
    if path_name == "instances.bak":
        return 3
    if path_name.startswith("instances.bak"):
        return 2
    if path_name == "instances":
        return 1
    return 0


def _requested_backup_priority(name: str) -> int:
    path_name = Path(name).name
    marker = ".bak"
    if marker not in path_name:
        return 0
    suffix = path_name.rsplit(marker, 1)[1]
    if not suffix:
        priority = 1
    else:
        try:
            priority = 1 + int(suffix)
        except ValueError:
            priority = 1
    if "kopie" in path_name.casefold() or "copy" in path_name.casefold():
        priority -= 1
    return max(0, priority)


def looks_like_encrypted_payload(path: Path) -> bool:
    return _encrypted_payload_state(path) is True


def _encrypted_payload_state(path: Path) -> bool | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if not raw.lstrip().startswith(b"{"):
        return False
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("magic") == "TMBMAP1" and isinstance(payload.get("ciphertext"), str)


def format_byte_size(size: int) -> str:
    value = float(max(0, size))
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{value:.2f} TB"
