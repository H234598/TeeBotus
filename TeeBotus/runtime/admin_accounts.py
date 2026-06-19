from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from inspect import isawaitable
from pathlib import Path
from typing import Any, Callable
from TeeBotus import __version__

from TeeBotus.runtime.accounts import AccountStore, AccountStoreError, SecretToolInstanceSecretProvider, TOKEN_HEX_RE
from TeeBotus.runtime.actions import SendText
from TeeBotus.runtime.proactive_agent import ProactiveSender, select_proactive_route
from TeeBotus.runtime.status_auth import status_auth_recipient_account_ids

ADMIN_ACCOUNT_IDS_ENV = "TEEBOTUS_ADMIN_ACCOUNT_IDS"
ADMIN_ACCOUNT_IDS_INSTANCE_ENV_PREFIX = "TEEBOTUS_ADMIN_ACCOUNT_IDS_"
DEFAULT_ADMIN_ACCOUNT_IDS = (
    "1013d6b22588708b4ea30ce8fcd7fe877e937adbfec740621b2ec2fe47fb2db343cac2181652efb27e55fb268693acd4782eb5c6f5e923c0e53fe3141a410790",
    "799c5b02f5e92c5a19ead998b6a4b42064c6e2827039249e1bc98ef7423ccd81ad0452f4f63b8424d5654455a069384717d5a5d8a4f3ad8905d42f768411a390",
)

_ADMIN_ID_SEPARATOR_RE = re.compile(r"[\s,;]+")
_RUNTIME_STATUS_PROBLEM_RE = re.compile(
    r"\bstatus=(?:broken|warning|unreachable|unavailable|missing|missing_key|invalid|config_conflict|degraded|stale|unsupported|failed|fallback_defaults|partial)\b"
)


@dataclass(frozen=True)
class AdminAccountGroup:
    account_ids: tuple[str, ...]
    invalid_ids: tuple[str, ...] = ()
    source: str = "default"


@dataclass(frozen=True)
class AdminNotificationResult:
    instance_name: str
    account_id: str
    status: str
    reason: str = ""
    channel: str = ""


StoreFactory = Callable[[Path, str], AccountStore]
SenderFactory = Callable[[str, AccountStore], Mapping[str, ProactiveSender]]


def resolve_admin_account_group(*, instance_name: str = "", env: Mapping[str, str] | None = None) -> AdminAccountGroup:
    source = os.environ if env is None else env
    env_names = _admin_account_env_names(instance_name)
    for env_name in env_names:
        if env_name not in source:
            continue
        ids, invalid = _parse_admin_account_ids((source[env_name],))
        return AdminAccountGroup(account_ids=ids, invalid_ids=invalid, source=env_name)
    return AdminAccountGroup(account_ids=DEFAULT_ADMIN_ACCOUNT_IDS, source="default")


def admin_account_group_status_lines(
    *,
    instance_name: str,
    project_root: Path,
    env: Mapping[str, str] | None = None,
    store: AccountStore | None = None,
) -> tuple[str, ...]:
    group = resolve_admin_account_group(instance_name=instance_name, env=env)
    if not group.account_ids and not group.invalid_ids:
        return (f"admin_accounts={instance_name} status=disabled source={group.source} accounts=0",)
    try:
        resolved_store = store or _default_account_store(project_root / "instances" / instance_name / "data" / "accounts", instance_name)
    except Exception as exc:  # noqa: BLE001 - runtime-status should diagnose store problems.
        return (
            f"admin_accounts={instance_name} status=broken source={group.source} accounts={len(group.account_ids)} "
            f"invalid={len(group.invalid_ids)} error={_status_token(f'{type(exc).__name__}:{exc}')}",
        )

    account_lines: list[str] = []
    local_count = 0
    routable_count = 0
    not_local_count = 0
    warning_count = 0
    for account_id in group.account_ids:
        account_dir = resolved_store.account_dir(account_id)
        if not account_dir.is_dir():
            not_local_count += 1
            continue
        local_count += 1
        try:
            route = select_proactive_route(resolved_store, account_id)
        except (AccountStoreError, OSError) as exc:
            warning_count += 1
            account_lines.append(
                f"admin_account={instance_name}/{account_id} status=warning reason=route_lookup_failed "
                f"error={_status_token(f'{type(exc).__name__}:{exc}')}"
            )
            continue
        if route is None:
            warning_count += 1
            account_lines.append(f"admin_account={instance_name}/{account_id} status=warning reason=no_private_route")
            continue
        routable_count += 1
        channel = _status_token(route.get("channel") or "unknown")
        slot = _status_token(route.get("adapter_slot") if route.get("adapter_slot") is not None else "unknown")
        account_lines.append(f"admin_account={instance_name}/{account_id} status=routable channel={channel} slot={slot}")

    status = "broken" if group.invalid_ids else "configured"
    lines = [
        f"admin_accounts={instance_name} status={status} source={group.source} accounts={len(group.account_ids)} "
        f"local={local_count} not_local={not_local_count} routable={routable_count} warnings={warning_count} invalid={len(group.invalid_ids)}"
    ]
    for invalid_id in group.invalid_ids:
        lines.append(f"admin_account={instance_name}/{_status_token(invalid_id)} status=broken reason=invalid_account_id")
    lines.extend(account_lines)
    return tuple(lines)


def runtime_status_problem_lines(status_output: str, *, limit: int = 40) -> tuple[str, ...]:
    problems: list[str] = []
    for raw_line in str(status_output or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("["):
            continue
        padded = f" {line}"
        if (
            line.startswith("account_identity_warning=")
            or " warning=" in padded
            or " error=" in padded
            or " route_error=" in padded
            or _RUNTIME_STATUS_PROBLEM_RE.search(line)
        ):
            problems.append(_redact_runtime_status_line(line))
            if len(problems) >= limit:
                break
    return tuple(problems)


async def notify_runtime_status_admin_accounts(
    *,
    instances_dir: Path,
    selected_instances: Sequence[str],
    status_output: str,
    env: Mapping[str, str] | None = None,
    store_factory: StoreFactory | None = None,
    sender_factory: SenderFactory | None = None,
    now: datetime | None = None,
) -> tuple[AdminNotificationResult, ...]:
    problem_lines = runtime_status_problem_lines(status_output)
    if not problem_lines:
        return (AdminNotificationResult(instance_name="runtime_status", account_id="", status="skipped", reason="no_problem_lines"),)
    source = os.environ if env is None else env
    resolved_store_factory = store_factory or _default_account_store
    resolved_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    message = _runtime_status_admin_message(problem_lines, selected_instances=selected_instances, now=resolved_now)
    results: list[AdminNotificationResult] = []
    for instance_name in selected_instances:
        try:
            store = resolved_store_factory(instances_dir / instance_name / "data" / "accounts", instance_name)
        except Exception as exc:  # noqa: BLE001 - runtime-status notify must not hide status output.
            results.append(AdminNotificationResult(instance_name, "", "failed", f"store:{type(exc).__name__}"))
            continue
        group = resolve_admin_account_group(instance_name=instance_name, env=source)
        for invalid_id in group.invalid_ids:
            results.append(AdminNotificationResult(instance_name, invalid_id, "failed", "invalid_account_id"))
        recipient_ids = group.account_ids
        if not recipient_ids and not group.invalid_ids and group.source != "default":
            env_value = str(source.get(group.source, "") if isinstance(source, Mapping) else "").strip()
            if not env_value:
                try:
                    recipient_ids = status_auth_recipient_account_ids(store)
                except Exception:  # noqa: BLE001 - status auth recipient enumeration should not block admin notify.
                    recipient_ids = ()
        candidates: list[tuple[str, dict[str, Any], str]] = []
        for account_id in recipient_ids:
            if not _account_dir_exists(store, account_id):
                results.append(AdminNotificationResult(instance_name, account_id, "skipped", "not_local"))
                continue
            try:
                route = select_proactive_route(store, account_id)
            except (AccountStoreError, OSError) as exc:
                results.append(AdminNotificationResult(instance_name, account_id, "failed", f"route:{type(exc).__name__}"))
                continue
            if route is None:
                results.append(AdminNotificationResult(instance_name, account_id, "skipped", "no_private_route"))
                continue
            channel = str(route.get("channel") or "").strip().casefold()
            if not channel:
                results.append(AdminNotificationResult(instance_name, account_id, "skipped", "no_channel"))
                continue
            candidates.append((account_id, route, channel))
        if not candidates:
            continue
        senders_by_channel: dict[str, ProactiveSender] = {}
        sender_errors_by_channel: dict[str, str] = {}
        candidate_channels = tuple(dict.fromkeys(channel for _account_id, _route, channel in candidates))
        if sender_factory is not None:
            try:
                senders = sender_factory(instance_name, store)
            except Exception as exc:  # noqa: BLE001 - injected factories have no per-channel selector.
                for channel in candidate_channels:
                    sender_errors_by_channel[channel] = f"sender_factory:{type(exc).__name__}"
            else:
                for channel in candidate_channels:
                    sender = senders.get(channel)
                    if sender is None:
                        sender_errors_by_channel[channel] = "no_sender"
                        continue
                    senders_by_channel[channel] = sender
        else:
            for channel in candidate_channels:
                try:
                    resolved_sender_factory = _runtime_sender_factory(instances_dir, source, channels=(channel,))
                    senders = resolved_sender_factory(instance_name, store)
                except Exception as exc:  # noqa: BLE001 - one runtime channel must not block other admin channels.
                    sender_errors_by_channel[channel] = f"sender_factory:{type(exc).__name__}"
                    continue
                sender = senders.get(channel)
                if sender is None:
                    sender_errors_by_channel[channel] = "no_sender"
                    continue
                senders_by_channel[channel] = sender
        for account_id, route, channel in candidates:
            sender_error = sender_errors_by_channel.get(channel)
            if sender_error == "no_sender":
                results.append(AdminNotificationResult(instance_name, account_id, "skipped", sender_error, channel=channel))
                continue
            if sender_error:
                results.append(AdminNotificationResult(instance_name, account_id, "failed", sender_error, channel=channel))
                continue
            sender = senders_by_channel[channel]
            chat_id = str(route.get("chat_id") or "").strip()
            summary_number = _next_status_summary_number(store, account_id)
            summary_prefix = f"v{__version__} #{summary_number:04d}"
            action_text = f"{summary_prefix} {message}"
            action = SendText(chat_id, action_text, track=False)
            dispatch_status = "sent"
            dispatch_reason = ""
            try:
                outcome = sender(route, action, {"source": "runtime_status_admin", "account_id": account_id})
                if isawaitable(outcome):
                    await outcome
            except Exception as exc:  # noqa: BLE001 - one failed admin must not block all admins.
                dispatch_status = "failed"
                dispatch_reason = f"send:{type(exc).__name__}"
                results.append(AdminNotificationResult(instance_name, account_id, dispatch_status, dispatch_reason, channel=channel))
                account_store_status_item = {
                    "schema_version": 1,
                    "summary_prefix": summary_prefix,
                    "summary_number": summary_number,
                    "message_text": action_text,
                    "status": dispatch_status,
                    "reason": dispatch_reason,
                    "instance_name": instance_name,
                    "account_id": account_id,
                    "channel": channel,
                    "created_at": resolved_now.isoformat(),
                    "updated_at": resolved_now.isoformat(),
                }
                store.append_status_outbox_item(account_id, account_store_status_item)
                store.append_status_dispatch_results(
                    account_id,
                    [
                        {
                            "schema_version": 1,
                            "summary_prefix": summary_prefix,
                            "summary_number": summary_number,
                            "status": dispatch_status,
                            "reason": dispatch_reason,
                            "instance_name": instance_name,
                            "account_id": account_id,
                            "channel": channel,
                            "created_at": resolved_now.isoformat(),
                            "updated_at": resolved_now.isoformat(),
                        }
                    ],
                )
                continue
            outbox_item = {
                "schema_version": 1,
                "summary_prefix": summary_prefix,
                "summary_number": summary_number,
                "message_text": action_text,
                "status": dispatch_status,
                "instance_name": instance_name,
                "account_id": account_id,
                "channel": channel,
                "created_at": resolved_now.isoformat(),
                "updated_at": resolved_now.isoformat(),
            }
            store.append_status_outbox_item(account_id, outbox_item)
            store.append_status_dispatch_results(
                account_id,
                [
                    {
                        "schema_version": 1,
                        "summary_prefix": summary_prefix,
                        "summary_number": summary_number,
                        "status": dispatch_status,
                        "instance_name": instance_name,
                        "account_id": account_id,
                        "channel": channel,
                        "created_at": resolved_now.isoformat(),
                        "updated_at": resolved_now.isoformat(),
                    }
                ],
            )
            results.append(AdminNotificationResult(instance_name, account_id, "sent", channel=channel))
    return tuple(results)


def _next_status_summary_number(account_store: AccountStore, account_id: str) -> int:
    max_number = 0
    for row in account_store.read_status_outbox(account_id):
        try:
            number = int(str(row.get("summary_number")).strip())
        except (TypeError, ValueError):
            continue
        if number > max_number:
            max_number = number
    return max_number + 1


def format_admin_notification_result_lines(results: Iterable[AdminNotificationResult]) -> tuple[str, ...]:
    lines: list[str] = []
    for result in results:
        parts = [
            f"admin_notify={_status_token(result.instance_name or 'runtime_status')}",
            f"status={_status_token(result.status)}",
        ]
        if result.account_id:
            parts.append(f"account_id={_status_token(result.account_id)}")
        if result.channel:
            parts.append(f"channel={_status_token(result.channel)}")
        if result.reason:
            parts.append(f"reason={_status_token(result.reason)}")
        lines.append(" ".join(parts))
    return tuple(lines)


def _admin_account_env_names(instance_name: str) -> tuple[str, ...]:
    instance_token = _env_instance_token(instance_name)
    if not instance_token:
        return (ADMIN_ACCOUNT_IDS_ENV,)
    return (f"{ADMIN_ACCOUNT_IDS_INSTANCE_ENV_PREFIX}{instance_token}", ADMIN_ACCOUNT_IDS_ENV)


def _parse_admin_account_ids(values: Iterable[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    account_ids: list[str] = []
    invalid_ids: list[str] = []
    seen: set[str] = set()
    invalid_seen: set[str] = set()
    for value in values:
        for token in _ADMIN_ID_SEPARATOR_RE.split(str(value or "").strip()):
            cleaned = token.strip().strip("'\"<>").casefold()
            if not cleaned:
                continue
            if TOKEN_HEX_RE.fullmatch(cleaned):
                if cleaned not in seen:
                    seen.add(cleaned)
                    account_ids.append(cleaned)
            elif cleaned not in invalid_seen:
                invalid_seen.add(cleaned)
                invalid_ids.append(cleaned)
    return tuple(account_ids), tuple(invalid_ids)


def _runtime_status_admin_message(problem_lines: Sequence[str], *, selected_instances: Sequence[str], now: datetime | None = None) -> str:
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    instance_text = ",".join(selected_instances) if selected_instances else "auto"
    lines = [
        "TeeBotus Runtime-Status Warnungen",
        f"Zeit: {timestamp}",
        f"Instanzen: {instance_text}",
        "",
        "Probleme:",
    ]
    lines.extend(f"- {line}" for line in problem_lines)
    message = "\n".join(lines)
    if len(message) <= 3500:
        return message
    return f"{message[:3470].rstrip()}\n... gekuerzt"


def _runtime_sender_factory(instances_dir: Path, env: Mapping[str, str], *, channels: Sequence[str]) -> SenderFactory:
    from TeeBotus.proactive import runtime_sender_factory

    return runtime_sender_factory(instances_dir, env=env, channels=channels)


def _default_account_store(root: Path, instance_name: str) -> AccountStore:
    return AccountStore(
        root,
        instance_name,
        secret_provider=SecretToolInstanceSecretProvider(create_if_missing=False),
        create_dirs=False,
        memory_backend_enabled=False,
    )


def _account_dir_exists(store: AccountStore, account_id: str) -> bool:
    return TOKEN_HEX_RE.fullmatch(str(account_id or "").strip().casefold()) is not None and store.account_dir(account_id).is_dir()


def _env_instance_token(instance_name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", str(instance_name or "").strip().upper()).strip("_")


def _status_token(value: object) -> str:
    text = str(value if value is not None else "").strip()
    if not text:
        return "<none>"
    return re.sub(r"\s+", "_", text.replace("\n", "_"))


def _redact_runtime_status_line(line: str) -> str:
    try:
        from TeeBotus.core.status import redact_status_text
    except Exception:  # pragma: no cover - fallback for import-time diagnostics.
        return str(line or "").replace("\r", " ").replace("\n", " ").strip()
    return redact_status_text(line)
