from __future__ import annotations

import logging
import os
import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from inspect import isawaitable
from pathlib import Path
from typing import Any, Callable

from TeeBotus import __version__

from TeeBotus.runtime.accounts import AccountStore, AccountStoreError, TOKEN_HEX_RE, runtime_secret_provider
from TeeBotus.runtime.actions import SendAttachment
from TeeBotus.runtime.proactive_agent import ProactiveSender, select_proactive_route
from TeeBotus.runtime.status_auth import status_auth_recipient_account_ids, status_auth_state_admin_opted_out

ADMIN_ACCOUNT_IDS_ENV = "TEEBOTUS_ADMIN_ACCOUNT_IDS"
ADMIN_ACCOUNT_IDS_INSTANCE_ENV_PREFIX = "TEEBOTUS_ADMIN_ACCOUNT_IDS_"
STATUS_SUMMARY_INSTANCE_NAME = "TeeBotus_Logger"
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


@dataclass(frozen=True)
class RuntimeStatusSummaryPayload:
    item_id: str
    message_text: str
    markdown_document: str
    markdown_filename: str


@dataclass(frozen=True)
class _AdminRouteResolution:
    status: str
    route: dict[str, Any] | None = None
    reason: str = ""
    source_store: AccountStore | None = None


StoreFactory = Callable[[Path, str], AccountStore]
SenderFactory = Callable[[str, AccountStore], Mapping[str, ProactiveSender]]

LOGGER = logging.getLogger("TeeBotus.runtime.admin_accounts")


def resolve_admin_account_group(*, instance_name: str = "", env: Mapping[str, str] | None = None) -> AdminAccountGroup:
    source = os.environ if env is None else env
    env_names = _admin_account_env_names(instance_name)
    for env_name in env_names:
        if env_name not in source:
            continue
        ids, invalid = _parse_admin_account_ids((source[env_name],))
        return AdminAccountGroup(account_ids=ids, invalid_ids=invalid, source=env_name)
    return AdminAccountGroup(account_ids=DEFAULT_ADMIN_ACCOUNT_IDS, source="default")


def runtime_admin_account_ids(
    account_store: AccountStore,
    *,
    instance_name: str = "",
    env: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    group = resolve_admin_account_group(instance_name=instance_name, env=env)
    return _status_notification_candidate_account_ids(
        account_store,
        configured_account_ids=group.account_ids,
        include_status_auth_accounts=True,
    )


def is_runtime_admin_account(
    account_store: AccountStore,
    account_id: str,
    *,
    instance_name: str = "",
    env: Mapping[str, str] | None = None,
) -> bool:
    normalized = str(account_id or "").strip().casefold()
    if not normalized:
        return False
    return normalized in set(runtime_admin_account_ids(account_store, instance_name=instance_name, env=env))


def admin_account_group_status_lines(
    *,
    instance_name: str,
    project_root: Path,
    env: Mapping[str, str] | None = None,
    store: AccountStore | None = None,
    store_factory: StoreFactory | None = None,
) -> tuple[str, ...]:
    group = resolve_admin_account_group(instance_name=instance_name, env=env)
    if not group.account_ids and not group.invalid_ids:
        return (f"admin_accounts={instance_name} status=disabled source={group.source} accounts=0",)
    resolved_store_factory = store_factory or _default_account_store
    try:
        resolved_store = store or resolved_store_factory(project_root / "instances" / instance_name / "data" / "accounts", instance_name)
    except Exception as exc:  # noqa: BLE001 - runtime-status should diagnose store problems.
        return (
            f"admin_accounts={instance_name} status=broken source={group.source} accounts={len(group.account_ids)} "
            f"invalid={len(group.invalid_ids)} error={_status_token(f'{type(exc).__name__}:{exc}')}",
        )
    account_ids = _status_notification_candidate_account_ids(
        resolved_store,
        configured_account_ids=group.account_ids,
        include_status_auth_accounts=True,
    )

    account_lines: list[str] = []
    local_count = 0
    cross_instance_count = 0
    routable_count = 0
    not_local_count = 0
    warning_count = 0
    for account_id in account_ids:
        is_local = _account_dir_exists(resolved_store, account_id)
        if is_local:
            local_count += 1
        try:
            route_resolution = _resolve_admin_notification_route(
                resolved_store,
                account_id,
                instances_dir=project_root / "instances",
                summary_instance_name=instance_name,
                store_factory=resolved_store_factory,
            )
        except (AccountStoreError, OSError, ValueError) as exc:
            warning_count += 1
            account_lines.append(
                f"admin_account={instance_name}/{account_id} status=warning reason=route_lookup_failed "
                f"error={_status_token(f'{type(exc).__name__}:{exc}')}"
            )
            continue
        if route_resolution.status == "not_local":
            not_local_count += 1
            continue
        if route_resolution.status == "failed":
            warning_count += 1
            account_lines.append(f"admin_account={instance_name}/{account_id} status=warning reason={_status_token(route_resolution.reason)}")
            continue
        if route_resolution.route is None:
            warning_count += 1
            account_lines.append(
                f"admin_account={instance_name}/{account_id} status=warning "
                f"reason={_status_token(route_resolution.reason or 'no_private_route')}"
            )
            continue
        route = route_resolution.route
        source_instance = _status_token(route.get("route_source_instance") or instance_name)
        if source_instance != _status_token(instance_name):
            cross_instance_count += 1
        routable_count += 1
        channel = _status_token(route.get("channel") or "unknown")
        slot = _status_token(route.get("adapter_slot") if route.get("adapter_slot") is not None else "unknown")
        account_lines.append(f"admin_account={instance_name}/{account_id} status=routable channel={channel} slot={slot} source_instance={source_instance}")

    status = "broken" if group.invalid_ids else "configured"
    lines = [
        f"admin_accounts={instance_name} status={status} source={group.source} accounts={len(account_ids)} "
        f"local={local_count} cross_instance={cross_instance_count} not_local={not_local_count} "
        f"routable={routable_count} warnings={warning_count} invalid={len(group.invalid_ids)}"
    ]
    for invalid_id in group.invalid_ids:
        lines.append(f"admin_account={instance_name}/{_status_token(invalid_id)} status=broken reason=invalid_account_id")
    lines.extend(account_lines)
    return tuple(lines)


def runtime_status_problem_lines(status_output: str, *, limit: int = 40) -> tuple[str, ...]:
    if limit <= 0:
        return ()
    problems: list[str] = []
    for raw_line in str(status_output or "").splitlines():
        line = _redact_runtime_status_line(raw_line).strip()
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
            problems.append(line)
            if len(problems) >= limit:
                break
    return tuple(problems)


async def notify_runtime_status_admin_accounts(
    *,
    instances_dir: Path,
    selected_instances: Sequence[str],
    status_output: str = "",
    problem_lines: tuple[str, ...] | None = None,
    env: Mapping[str, str] | None = None,
    store_factory: StoreFactory | None = None,
    sender_factory: SenderFactory | None = None,
    now: datetime | None = None,
    summary_instance_name: str = STATUS_SUMMARY_INSTANCE_NAME,
) -> tuple[AdminNotificationResult, ...]:
    if problem_lines is None:
        problem_lines = runtime_status_problem_lines(status_output)
    if not problem_lines:
        return (AdminNotificationResult(instance_name="runtime_status", account_id="", status="skipped", reason="no_problem_lines"),)
    source = os.environ if env is None else env
    resolved_store_factory = store_factory or _default_account_store
    results: list[AdminNotificationResult] = []
    instance_name = _summary_instance_name(summary_instance_name)
    try:
        store = resolved_store_factory(instances_dir / instance_name / "data" / "accounts", instance_name)
    except Exception as exc:  # noqa: BLE001 - runtime-status notify must not hide status output.
        return (AdminNotificationResult(instance_name, "", "failed", f"store:{type(exc).__name__}"),)
    group = resolve_admin_account_group(instance_name=instance_name, env=source)
    for invalid_id in group.invalid_ids:
        results.append(AdminNotificationResult(instance_name, invalid_id, "failed", "invalid_account_id"))
    candidates: list[tuple[str, dict[str, Any], str, RuntimeStatusSummaryPayload, str]] = []
    for account_id in _status_notification_candidate_account_ids(
        store,
        configured_account_ids=group.account_ids,
        include_status_auth_accounts=True,
    ):
        try:
            route_resolution = _resolve_admin_notification_route(
                store,
                account_id,
                instances_dir=instances_dir,
                summary_instance_name=instance_name,
                store_factory=resolved_store_factory,
            )
        except (AccountStoreError, OSError, ValueError) as exc:
            results.append(AdminNotificationResult(instance_name, account_id, "failed", f"route:{type(exc).__name__}"))
            continue
        if route_resolution.status == "not_local":
            results.append(AdminNotificationResult(instance_name, account_id, "skipped", "not_local"))
            continue
        if route_resolution.status == "failed":
            results.append(AdminNotificationResult(instance_name, account_id, "failed", route_resolution.reason or "route:failed"))
            continue
        if route_resolution.route is None:
            results.append(AdminNotificationResult(instance_name, account_id, "skipped", route_resolution.reason or "no_private_route"))
            continue
        if route_resolution.source_store is not None and status_auth_state_admin_opted_out(route_resolution.source_store, account_id):
            results.append(AdminNotificationResult(instance_name, account_id, "skipped", "admin_opt_out"))
            continue
        route = route_resolution.route
        channel = str(route.get("channel") or "").strip().casefold()
        if not channel:
            results.append(AdminNotificationResult(instance_name, account_id, "skipped", "no_channel"))
            continue
        try:
            summary_payload = _queue_runtime_status_summary(
                store,
                account_id,
                problem_lines=problem_lines,
                selected_instances=selected_instances,
                route=route,
                now=now,
            )
        except Exception as exc:  # noqa: BLE001 - one broken status store must not hide runtime-status output.
            results.append(AdminNotificationResult(instance_name, account_id, "failed", f"outbox:{type(exc).__name__}", channel=channel))
            continue
        candidates.append((account_id, route, channel, summary_payload, _route_sender_instance(route, instance_name)))
    if not candidates:
        return tuple(results)
    candidate_targets = tuple(
        dict.fromkeys((sender_instance, channel) for _account_id, _route, channel, _summary_payload, sender_instance in candidates)
    )
    senders_by_target, sender_errors_by_target = _resolve_admin_senders(
        instances_dir=instances_dir,
        env=source,
        store=store,
        candidate_targets=candidate_targets,
        sender_factory=sender_factory,
    )
    for account_id, route, channel, summary_payload, sender_instance in candidates:
        target = (sender_instance, channel)
        sender_error = sender_errors_by_target.get(target)
        if sender_error == "no_sender":
            _record_runtime_status_dispatch(store, account_id, summary_payload.item_id, status="skipped", reason=sender_error, channel=channel, now=now)
            results.append(AdminNotificationResult(instance_name, account_id, "skipped", sender_error, channel=channel))
            continue
        if sender_error:
            _record_runtime_status_dispatch(store, account_id, summary_payload.item_id, status="failed", reason=sender_error, channel=channel, now=now)
            results.append(AdminNotificationResult(instance_name, account_id, "failed", sender_error, channel=channel))
            continue
        sender = senders_by_target[target]
        chat_id = str(route.get("chat_id") or "").strip()
        action = SendAttachment(
            chat_id,
            summary_payload.markdown_document.encode("utf-8"),
            summary_payload.markdown_filename,
            "text/markdown",
            caption=summary_payload.message_text,
            track=False,
        )
        try:
            outcome = sender(route, action, {"source": "runtime_status_admin", "account_id": account_id})
            if isawaitable(outcome):
                await outcome
        except Exception as exc:  # noqa: BLE001 - one failed admin must not block all admins.
            reason = f"send:{type(exc).__name__}"
            _record_runtime_status_dispatch(store, account_id, summary_payload.item_id, status="failed", reason=reason, channel=channel, now=now)
            results.append(AdminNotificationResult(instance_name, account_id, "failed", reason, channel=channel))
            continue
        _record_runtime_status_dispatch(store, account_id, summary_payload.item_id, status="sent", channel=channel, now=now)
        results.append(AdminNotificationResult(instance_name, account_id, "sent", channel=channel))
    return tuple(results)


async def notify_benchmark_admin_accounts(
    *,
    instances_dir: Path,
    markdown_document: str,
    markdown_filename: str = "teebotus-benchmarks-latest.md",
    json_artifact_path: Path | str = "",
    benchmark_suite: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    store_factory: StoreFactory | None = None,
    sender_factory: SenderFactory | None = None,
    now: datetime | None = None,
    summary_instance_name: str = STATUS_SUMMARY_INSTANCE_NAME,
) -> tuple[AdminNotificationResult, ...]:
    if not str(markdown_document or "").strip():
        return (AdminNotificationResult(instance_name="benchmark", account_id="", status="skipped", reason="empty_markdown"),)
    source = os.environ if env is None else env
    resolved_store_factory = store_factory or _default_account_store
    results: list[AdminNotificationResult] = []
    instance_name = _summary_instance_name(summary_instance_name)
    try:
        store = resolved_store_factory(instances_dir / instance_name / "data" / "accounts", instance_name)
    except Exception as exc:  # noqa: BLE001 - benchmark notify must not hide the benchmark report.
        return (AdminNotificationResult(instance_name, "", "failed", f"store:{type(exc).__name__}"),)
    group = resolve_admin_account_group(instance_name=instance_name, env=source)
    for invalid_id in group.invalid_ids:
        results.append(AdminNotificationResult(instance_name, invalid_id, "failed", "invalid_account_id"))
    candidates: list[tuple[str, dict[str, Any], str, RuntimeStatusSummaryPayload, str]] = []
    for account_id in _status_notification_candidate_account_ids(
        store,
        configured_account_ids=group.account_ids,
        include_status_auth_accounts=True,
    ):
        try:
            route_resolution = _resolve_admin_notification_route(
                store,
                account_id,
                instances_dir=instances_dir,
                summary_instance_name=instance_name,
                store_factory=resolved_store_factory,
            )
        except (AccountStoreError, OSError, ValueError) as exc:
            results.append(AdminNotificationResult(instance_name, account_id, "failed", f"route:{type(exc).__name__}"))
            continue
        if route_resolution.status == "not_local":
            results.append(AdminNotificationResult(instance_name, account_id, "skipped", "not_local"))
            continue
        if route_resolution.status == "failed":
            results.append(AdminNotificationResult(instance_name, account_id, "failed", route_resolution.reason or "route:failed"))
            continue
        if route_resolution.route is None:
            results.append(AdminNotificationResult(instance_name, account_id, "skipped", route_resolution.reason or "no_private_route"))
            continue
        if route_resolution.source_store is not None and status_auth_state_admin_opted_out(route_resolution.source_store, account_id):
            results.append(AdminNotificationResult(instance_name, account_id, "skipped", "admin_opt_out"))
            continue
        route = route_resolution.route
        channel = str(route.get("channel") or "").strip().casefold()
        if not channel:
            results.append(AdminNotificationResult(instance_name, account_id, "skipped", "no_channel"))
            continue
        try:
            summary_payload = _queue_runtime_benchmark_summary(
                store,
                account_id,
                markdown_document=markdown_document,
                markdown_filename=markdown_filename,
                json_artifact_path=json_artifact_path,
                benchmark_suite=benchmark_suite,
                route=route,
                now=now,
            )
        except Exception as exc:  # noqa: BLE001 - one broken admin outbox must not block benchmark output.
            results.append(AdminNotificationResult(instance_name, account_id, "failed", f"outbox:{type(exc).__name__}", channel=channel))
            continue
        candidates.append((account_id, route, channel, summary_payload, _route_sender_instance(route, instance_name)))
    if not candidates:
        return tuple(results)
    candidate_targets = tuple(
        dict.fromkeys((sender_instance, channel) for _account_id, _route, channel, _summary_payload, sender_instance in candidates)
    )
    senders_by_target, sender_errors_by_target = _resolve_admin_senders(
        instances_dir=instances_dir,
        env=source,
        store=store,
        candidate_targets=candidate_targets,
        sender_factory=sender_factory,
    )
    for account_id, route, channel, summary_payload, sender_instance in candidates:
        target = (sender_instance, channel)
        sender_error = sender_errors_by_target.get(target)
        if sender_error == "no_sender":
            _record_runtime_status_dispatch(store, account_id, summary_payload.item_id, status="skipped", reason=sender_error, channel=channel, now=now)
            results.append(AdminNotificationResult(instance_name, account_id, "skipped", sender_error, channel=channel))
            continue
        if sender_error:
            _record_runtime_status_dispatch(store, account_id, summary_payload.item_id, status="failed", reason=sender_error, channel=channel, now=now)
            results.append(AdminNotificationResult(instance_name, account_id, "failed", sender_error, channel=channel))
            continue
        sender = senders_by_target[target]
        chat_id = str(route.get("chat_id") or "").strip()
        action = SendAttachment(
            chat_id,
            summary_payload.markdown_document.encode("utf-8"),
            summary_payload.markdown_filename,
            "text/markdown",
            caption=summary_payload.message_text,
            track=False,
        )
        try:
            outcome = sender(route, action, {"source": "benchmark_admin", "account_id": account_id})
            if isawaitable(outcome):
                await outcome
        except Exception as exc:  # noqa: BLE001 - one failed admin must not block all admins.
            reason = f"send:{type(exc).__name__}"
            _record_runtime_status_dispatch(store, account_id, summary_payload.item_id, status="failed", reason=reason, channel=channel, now=now)
            results.append(AdminNotificationResult(instance_name, account_id, "failed", reason, channel=channel))
            continue
        _record_runtime_status_dispatch(store, account_id, summary_payload.item_id, status="sent", channel=channel, now=now)
        results.append(AdminNotificationResult(instance_name, account_id, "sent", channel=channel))
    return tuple(results)


def _status_notification_candidate_account_ids(
    store: AccountStore,
    *,
    configured_account_ids: Sequence[str],
    include_status_auth_accounts: bool = False,
) -> tuple[str, ...]:
    candidates: list[str] = []
    seen: set[str] = set()
    try:
        status_auth_account_ids = status_auth_recipient_account_ids(store)
    except Exception:  # noqa: BLE001 - status auth recipient enumeration should not block configured admins.
        status_auth_account_ids = ()
    candidate_ids: tuple[str, ...] = tuple(configured_account_ids)
    if include_status_auth_accounts:
        candidate_ids += tuple(status_auth_account_ids)
    for account_id in candidate_ids:
        normalized = str(account_id or "").strip().casefold()
        if not normalized or normalized in seen:
            continue
        # Account-memory reads acquire a per-account lock and therefore create
        # the account directory. Do not turn a remote configured admin into a
        # local account merely to check local opt-out state.
        opted_out = False
        if _account_dir_exists(store, normalized):
            try:
                opted_out = status_auth_state_admin_opted_out(store, normalized)
            except Exception:  # noqa: BLE001 - configured admins should still be diagnosable when opt-out lookup fails.
                opted_out = False
        if opted_out:
            continue
        seen.add(normalized)
        candidates.append(normalized)
    return tuple(candidates)


def _resolve_admin_notification_route(
    store: AccountStore,
    account_id: str,
    *,
    instances_dir: Path,
    summary_instance_name: str,
    store_factory: StoreFactory,
) -> _AdminRouteResolution:
    local_route_error = ""
    local_account_exists = _account_dir_exists(store, account_id)
    local_account_without_route = False
    if local_account_exists:
        try:
            route = select_proactive_route(store, account_id)
        except (AccountStoreError, OSError, ValueError) as exc:
            local_route_error = f"{summary_instance_name}:{type(exc).__name__}"
        else:
            if route is None:
                local_account_without_route = True
            else:
                return _AdminRouteResolution("routable", route=dict(route), source_store=store)

    found_source_account = False
    route_errors: list[str] = []
    for source_instance_name, source_store in _admin_account_source_stores(
        instances_dir,
        account_id,
        summary_instance_name=summary_instance_name,
        store_factory=store_factory,
    ):
        found_source_account = True
        try:
            route = select_proactive_route(source_store, account_id)
        except (AccountStoreError, OSError, ValueError) as exc:
            route_errors.append(f"{source_instance_name}:{type(exc).__name__}")
            continue
        if route is None:
            continue
        resolved_route = dict(route)
        resolved_route.setdefault("route_source_instance", source_instance_name)
        return _AdminRouteResolution("routable", route=resolved_route, reason="cross_instance", source_store=source_store)
    if found_source_account:
        if route_errors:
            return _AdminRouteResolution("failed", reason=f"route:{route_errors[0]}")
        return _AdminRouteResolution("skipped", reason="no_private_route")
    if local_route_error:
        return _AdminRouteResolution("failed", reason=f"route:{local_route_error}")
    if local_account_exists or local_account_without_route:
        return _AdminRouteResolution("skipped", reason="no_private_route")
    return _AdminRouteResolution("not_local", reason="not_local")


def _admin_account_source_stores(
    instances_dir: Path,
    account_id: str,
    *,
    summary_instance_name: str,
    store_factory: StoreFactory,
) -> tuple[tuple[str, AccountStore], ...]:
    if TOKEN_HEX_RE.fullmatch(str(account_id or "").strip().casefold()) is None:
        return ()
    try:
        instance_dirs = sorted(
            (path for path in Path(instances_dir).iterdir() if path.is_dir()),
            key=lambda path: path.name.casefold(),
        )
    except OSError:
        return ()
    stores: list[tuple[str, AccountStore]] = []
    for instance_dir in instance_dirs:
        instance_name = instance_dir.name
        if instance_name == summary_instance_name:
            continue
        accounts_root = instance_dir / "data" / "accounts"
        if not (accounts_root / "accounts" / str(account_id).casefold()).is_dir():
            continue
        try:
            source_store = store_factory(accounts_root, instance_name)
        except Exception:  # noqa: BLE001 - broken source stores must not block other instances.
            continue
        stores.append((instance_name, source_store))
    return tuple(stores)


def _queue_runtime_status_summary(
    store: AccountStore,
    account_id: str,
    *,
    problem_lines: Sequence[str],
    selected_instances: Sequence[str],
    route: Mapping[str, Any],
    now: datetime | None = None,
) -> RuntimeStatusSummaryPayload:
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")
    with store.status_outbox_lock(account_id):
        rows = store.read_status_outbox(account_id)
        summary_number = _next_status_summary_number(rows)
        summary_prefix = _status_summary_prefix(summary_number)
        message_text = _runtime_status_admin_message_text()
        markdown_document = _runtime_status_admin_markdown(
            problem_lines,
            selected_instances=selected_instances,
            now=now,
            summary_prefix=summary_prefix,
        )
        markdown_filename = _runtime_status_markdown_filename(summary_number)
        item_id = _unique_status_item_id(rows)
        rows.append(
            {
                "id": item_id,
                "schema_version": 1,
                "kind": "runtime_status_summary",
                "status": "queued",
                "created_at": timestamp,
                "updated_at": timestamp,
                "summary_number": summary_number,
                "summary_prefix": summary_prefix,
                "program_name": "TeeBotus",
                "program_version": __version__,
                "tag": f"v{__version__}",
                "message_text": message_text,
                "markdown_document": markdown_document,
                "markdown_filename": markdown_filename,
                "markdown_content_type": "text/markdown",
                "problem_lines": list(problem_lines),
                "selected_instances": list(selected_instances),
                "route": dict(route),
                "status_history": [{"at": timestamp, "status": "queued", "reason": "runtime_status_problem"}],
            }
        )
        store.write_status_outbox(account_id, rows)
        return RuntimeStatusSummaryPayload(
            item_id=item_id,
            message_text=message_text,
            markdown_document=markdown_document,
            markdown_filename=markdown_filename,
        )


def _queue_runtime_benchmark_summary(
    store: AccountStore,
    account_id: str,
    *,
    markdown_document: str,
    markdown_filename: str,
    json_artifact_path: Path | str,
    benchmark_suite: Mapping[str, Any] | None,
    route: Mapping[str, Any],
    now: datetime | None = None,
) -> RuntimeStatusSummaryPayload:
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")
    with store.status_outbox_lock(account_id):
        rows = store.read_status_outbox(account_id)
        summary_number = _next_status_summary_number(rows)
        summary_prefix = _status_summary_prefix(summary_number)
        message_text = _benchmark_admin_message_text()
        safe_filename = _benchmark_markdown_filename(markdown_filename, summary_number)
        item_id = _unique_status_item_id(rows)
        suite = benchmark_suite if isinstance(benchmark_suite, Mapping) else {}
        result_count = len(suite.get("results") or []) if isinstance(suite.get("results"), list) else 0
        rows.append(
            {
                "id": item_id,
                "schema_version": 1,
                "kind": "benchmark_summary",
                "status": "queued",
                "created_at": timestamp,
                "updated_at": timestamp,
                "summary_number": summary_number,
                "summary_prefix": summary_prefix,
                "program_name": "TeeBotus",
                "program_version": __version__,
                "tag": f"v{__version__}",
                "message_text": message_text,
                "markdown_document": str(markdown_document or ""),
                "markdown_filename": safe_filename,
                "markdown_content_type": "text/markdown",
                "json_artifact_path": str(json_artifact_path or ""),
                "benchmark_ok": bool(suite.get("ok")) if suite else None,
                "benchmark_quick": bool(suite.get("quick")) if suite else None,
                "benchmark_result_count": result_count,
                "route": dict(route),
                "status_history": [{"at": timestamp, "status": "queued", "reason": "benchmark_completed"}],
            }
        )
        store.write_status_outbox(account_id, rows)
        return RuntimeStatusSummaryPayload(
            item_id=item_id,
            message_text=message_text,
            markdown_document=str(markdown_document or ""),
            markdown_filename=safe_filename,
        )


def _record_runtime_status_dispatch(
    store: AccountStore,
    account_id: str,
    item_id: str,
    *,
    status: str,
    reason: str = "",
    channel: str = "",
    now: datetime | None = None,
) -> None:
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")
    normalized_status = str(status or "").strip().casefold()
    normalized_reason = str(reason or "").strip()
    summary_prefix = ""
    summary_number: int | None = None
    try:
        with store.status_outbox_lock(account_id):
            rows = store.read_status_outbox(account_id)
            for item in rows:
                if not isinstance(item, dict) or str(item.get("id") or "") != str(item_id or ""):
                    continue
                summary_prefix = str(item.get("summary_prefix") or "")
                try:
                    summary_number = int(item.get("summary_number") or 0) or None
                except (TypeError, ValueError):
                    summary_number = None
                item["status"] = normalized_status
                item["updated_at"] = timestamp
                if normalized_status == "sent":
                    item["sent_at"] = timestamp
                if normalized_reason:
                    item["last_reason"] = normalized_reason
                history = item.get("status_history")
                if history is None:
                    history = []
                    item["status_history"] = history
                if isinstance(history, list):
                    history.append({"at": timestamp, "status": normalized_status, "reason": normalized_reason})
                break
            store.write_status_outbox(account_id, rows)
    except Exception:  # noqa: BLE001 - one broken status outbox must not block other admins.
        LOGGER.exception(
            "Runtime status outbox state persistence failed account_id=%s item_id=%s status=%s",
            account_id,
            item_id,
            normalized_status,
        )
    try:
        store.append_status_dispatch_result(
            account_id,
            {
                "schema_version": 1,
                "status_outbox_item_id": item_id,
                "status": normalized_status,
                "reason": normalized_reason,
                "channel": str(channel or "").strip().casefold(),
                "summary_prefix": summary_prefix,
                "summary_number": summary_number,
                "created_at": timestamp,
                "updated_at": timestamp,
            },
        )
    except Exception:  # noqa: BLE001 - external delivery state must not be reported as failed after it was sent.
        LOGGER.exception(
            "Runtime status dispatch result persistence failed account_id=%s item_id=%s status=%s",
            account_id,
            item_id,
            normalized_status,
        )


def _next_status_summary_number(rows: Sequence[Mapping[str, Any]]) -> int:
    max_number = 0
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        try:
            number = int(str(row.get("summary_number") or "").strip())
        except (TypeError, ValueError):
            continue
        if number > max_number:
            max_number = number
    return max_number + 1


def _status_summary_prefix(summary_number: int) -> str:
    return f"v{__version__} #{max(1, int(summary_number)):04d}"


def _unique_status_item_id(rows: Sequence[Mapping[str, Any]]) -> str:
    existing_ids = {str(row.get("id", "")).strip() for row in rows if isinstance(row, Mapping)}
    item_id = f"stat_{uuid.uuid4().hex}"
    while item_id in existing_ids:
        item_id = f"stat_{uuid.uuid4().hex}"
    return item_id


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


_SENDER_NOT_FOUND = object()


def _resolve_admin_senders(
    *,
    instances_dir: Path,
    env: Mapping[str, str],
    store: AccountStore,
    candidate_targets: Sequence[tuple[str, str]],
    sender_factory: SenderFactory | None,
) -> tuple[dict[tuple[str, str], ProactiveSender], dict[tuple[str, str], str]]:
    senders_by_target: dict[tuple[str, str], ProactiveSender] = {}
    sender_errors_by_target: dict[tuple[str, str], str] = {}

    def add_senders(sender_instance: str, channels: Sequence[str], senders: object) -> None:
        for channel in channels:
            target = (sender_instance, channel)
            try:
                sender = _sender_for_channel(senders, channel)
            except Exception as exc:  # noqa: BLE001 - one broken channel must not block other admin channels.
                sender_errors_by_target[target] = f"sender_factory:{type(exc).__name__}"
                continue
            if sender is None or sender is _SENDER_NOT_FOUND:
                sender_errors_by_target[target] = "no_sender"
                continue
            if not callable(sender):
                sender_errors_by_target[target] = "sender_factory:non_callable"
                continue
            senders_by_target[target] = sender

    if sender_factory is not None:
        channels_by_instance: dict[str, list[str]] = {}
        for sender_instance, channel in candidate_targets:
            channels_by_instance.setdefault(sender_instance, [])
            if channel not in channels_by_instance[sender_instance]:
                channels_by_instance[sender_instance].append(channel)
        for sender_instance, channels in channels_by_instance.items():
            try:
                senders = sender_factory(sender_instance, store)
            except Exception as exc:  # noqa: BLE001 - injected factories have no per-channel selector.
                for channel in channels:
                    sender_errors_by_target[(sender_instance, channel)] = f"sender_factory:{type(exc).__name__}"
                continue
            add_senders(sender_instance, channels, senders)
        return senders_by_target, sender_errors_by_target

    for sender_instance, channel in candidate_targets:
        target = (sender_instance, channel)
        try:
            resolved_sender_factory = _runtime_sender_factory(instances_dir, env, channels=(channel,))
            senders = resolved_sender_factory(sender_instance, store)
        except Exception as exc:  # noqa: BLE001 - one runtime channel must not block other admin channels.
            sender_errors_by_target[target] = f"sender_factory:{type(exc).__name__}"
            continue
        add_senders(sender_instance, (channel,), senders)
    return senders_by_target, sender_errors_by_target


def _sender_for_channel(senders: object, channel: str) -> Any | object:
    normalized_channel = str(channel or "").strip().casefold()
    try:
        sender = senders.get(normalized_channel)
    except Exception:
        if not isinstance(senders, Mapping):
            raise
        sender = _SENDER_NOT_FOUND
        for sender_channel, sender_value in senders.items():
            if str(sender_channel or "").strip().casefold() == normalized_channel:
                sender = sender_value
                break
    else:
        if sender is None and isinstance(senders, Mapping):
            for sender_channel, sender_value in senders.items():
                if str(sender_channel or "").strip().casefold() == normalized_channel:
                    sender = sender_value
                    break
            else:
                sender = _SENDER_NOT_FOUND
    return sender


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


def _runtime_status_admin_message_text() -> str:
    return f"Release TeeBotus {__version__}"


def _benchmark_admin_message_text() -> str:
    return f"Benchmark TeeBotus {__version__}"


def _summary_instance_name(value: str) -> str:
    text = str(value or "").strip() or STATUS_SUMMARY_INSTANCE_NAME
    if "/" in text or "\\" in text or text in {".", ".."}:
        raise ValueError("status summary instance must be a single path segment")
    return text


def _route_sender_instance(route: Mapping[str, Any], fallback: str) -> str:
    candidate = str(route.get("route_source_instance") or fallback).strip()
    try:
        return _summary_instance_name(candidate)
    except ValueError:
        return _summary_instance_name(fallback)


def _runtime_status_admin_markdown(
    problem_lines: Sequence[str],
    *,
    selected_instances: Sequence[str],
    now: datetime | None = None,
    summary_prefix: str = "",
) -> str:
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")
    instance_text = ",".join(selected_instances) if selected_instances else "auto"
    lines = [
        f"# Release TeeBotus {__version__}",
        "",
        f"**Summary:** `{_escape_markdown_inline(summary_prefix or f'v{__version__}')}`",
        "**Programm:** TeeBotus",
        f"**Version:** `{_escape_markdown_inline(__version__)}`",
        f"**Zeit:** `{_escape_markdown_inline(timestamp)}`",
        f"**Instanzen:** `{_escape_markdown_inline(instance_text)}`",
        "",
        "## Probleme",
        "",
    ]
    if problem_lines:
        lines.extend(f"- `{_escape_markdown_inline(line)}`" for line in problem_lines)
    else:
        lines.append("- Keine Probleme gemeldet.")
    lines.extend(["", "## Versand", "", "- Status: `queued` beim Erzeugen, danach `sent`/`failed` im Dispatch-Status."])
    return "\n".join(lines).rstrip() + "\n"


def _runtime_status_markdown_filename(summary_number: int) -> str:
    safe_version = re.sub(r"[^A-Za-z0-9._-]+", "_", __version__).strip("._-") or "unknown"
    return f"TeeBotus_release_{safe_version}_{max(1, int(summary_number)):04d}.md"


def _benchmark_markdown_filename(markdown_filename: str, summary_number: int) -> str:
    requested = Path(str(markdown_filename or "")).name.strip()
    if requested:
        return requested
    safe_version = re.sub(r"[^A-Za-z0-9._-]+", "_", __version__).strip("._-") or "unknown"
    return f"TeeBotus_benchmarks_{safe_version}_{max(1, int(summary_number)):04d}.md"


def _escape_markdown_inline(value: object) -> str:
    return str(value if value is not None else "").replace("`", r"\`").replace("\n", " ").strip()


def _runtime_sender_factory(instances_dir: Path, env: Mapping[str, str], *, channels: Sequence[str]) -> SenderFactory:
    from TeeBotus.proactive import runtime_sender_factory

    return runtime_sender_factory(instances_dir, env=env, channels=channels)


def _default_account_store(root: Path, instance_name: str) -> AccountStore:
    return AccountStore(
        root,
        instance_name,
        secret_provider=runtime_secret_provider(),
        create_dirs=False,
        memory_backend_enabled=False,
    )


def _account_dir_exists(store: AccountStore, account_id: str) -> bool:
    if TOKEN_HEX_RE.fullmatch(str(account_id or "").strip().casefold()) is None:
        return False
    account_dir = getattr(store, "account_dir", None)
    if not callable(account_dir):
        return False
    return account_dir(account_id).is_dir()


def _env_instance_token(instance_name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", str(instance_name or "").strip().upper()).strip("_")


def _status_token(value: object) -> str:
    text = str(value if value is not None else "").strip()
    if not text:
        return "<none>"
    redacted = _redact_runtime_status_line(text)
    return re.sub(r"\s+", "_", redacted.replace("\n", "_")) or "<none>"


def _redact_runtime_status_line(line: str) -> str:
    try:
        from TeeBotus.core.status import redact_status_text
    except Exception:  # pragma: no cover - fallback for import-time diagnostics.
        return str(line or "").replace("\r", " ").replace("\n", " ").strip()
    return redact_status_text(line)
