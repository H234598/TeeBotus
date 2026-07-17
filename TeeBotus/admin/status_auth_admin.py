from __future__ import annotations

import argparse
import json
import os
import sys
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from TeeBotus.admin.accounts_report import DEFAULT_INSTANCES_DIR, discover_instances, parse_csv
from TeeBotus.core.status import redact_status_text
from TeeBotus.runtime.accounts import (
    ACCOUNT_MEMORY_KEY_PURPOSE,
    AccountStore,
    AccountStoreError,
    INSTANCE_MAPPING_KEY_PURPOSE,
    InstanceSecretProvider,
    runtime_secret_provider,
)
from TeeBotus.runtime.dotenv import load_project_dotenv_for_instances
from TeeBotus.runtime.proactive_agent import select_proactive_route
from TeeBotus.runtime.status_auth import DEFAULT_STATUS_AUTH_INSTANCES

REPORT_SCHEMA_VERSION = 1
STATUS_AUTH_BOOTSTRAP_PURPOSES = (INSTANCE_MAPPING_KEY_PURPOSE, ACCOUNT_MEMORY_KEY_PURPOSE)
_REDACTED_VALUE = "<redacted>"
_SENSITIVE_REDACTION_KEYS = {
    "secret",
    "secret_verifier",
    "verifier",
    "token",
    "api_key",
    "apikey",
    "password",
    "passphrase",
    "bearer_token",
    "auth_token",
    "cookie",
    "session_id",
    "account_secret",
    "openai_api_key",
    "instance_secret",
}
_SENSITIVE_REDACTION_KEY_FRAGMENTS = ("token", "secret", "apikey", "passphrase", "password", "api_key", "secret_key", "verifier", "cookie")
_SENSITIVE_TEXT_FRAGMENTS = ("token", "secret", "apikey", "passphrase", "password", "api_key", "secret_key", "verifier", "cookie")
_SENSITIVE_FIELD_ALLOWLIST = {"account_id", "linked_identities", "identity_key"}
_SAFE_PATH_SEGMENT_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*)")


def _split_safe_relative_parts(value: str, *, operation: str) -> tuple[bool, tuple[str, ...]]:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{operation} must not be empty")
    if "\x00" in text or "\r" in text or "\n" in text or "\t" in text:
        raise ValueError(f"{operation} contains invalid control characters")
    if "\\" in text:
        raise ValueError(f"{operation} contains invalid path separator: \\")
    if text == "/":
        return True, tuple()
    is_absolute = text.startswith("/")
    normalized = text[1:] if is_absolute else text
    if not normalized:
        raise ValueError(f"{operation} must not be empty")
    raw_parts = normalized.split("/")
    parts: list[str] = []
    for part in raw_parts:
        if part in {"", "."}:
            continue
        if part == "..":
            raise ValueError(f"{operation} contains forbidden relative segment: {part}")
        if not _SAFE_PATH_SEGMENT_RE.fullmatch(part):
            raise ValueError(f"{operation} contains invalid path segment: {part}")
        parts.append(part)
    return is_absolute, tuple(parts)


def _sanitize_output(payload: Any) -> Any:
    if isinstance(payload, str):
        lowered = payload.casefold()
        if any(fragment in lowered for fragment in _SENSITIVE_TEXT_FRAGMENTS):
            return _REDACTED_VALUE
        return payload
    if isinstance(payload, list):
        return [_sanitize_output(item) for item in payload]
    if isinstance(payload, tuple):
        return tuple(_sanitize_output(item) for item in payload)
    if isinstance(payload, dict):
        result: dict[str, Any] = {}
        for key, value in payload.items():
            lowered = str(key).casefold()
            should_redact = (
                lowered in _SENSITIVE_REDACTION_KEYS
                or (lowered not in _SENSITIVE_FIELD_ALLOWLIST and any(fragment in lowered for fragment in _SENSITIVE_REDACTION_KEY_FRAGMENTS))
            )
            if should_redact:
                result[str(key)] = _REDACTED_VALUE
            else:
                result[str(key)] = _sanitize_output(value)
        if "account_id" in result:
            result["account_id"] = _REDACTED_VALUE
        return result
    return payload


def _safe_output_path(output: str, *, base_dir: str | Path = ".") -> Path:
    is_absolute, parts = _split_safe_relative_parts(output, operation="output path")
    if is_absolute:
        raise ValueError(f"output path must be a safe relative path: {output}")
    base_path = Path(base_dir)
    base_symlink = _first_symlinked_path_component(base_path)
    if base_symlink is not None:
        raise ValueError(f"output base must not use symlinked components: {base_symlink}")
    try:
        root = base_path.resolve()
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"output base could not be resolved: {base_dir}") from exc
    output_path = Path(*parts)
    lexical_target = root / output_path
    symlink_component = _first_symlinked_path_component(lexical_target)
    if symlink_component is not None:
        raise ValueError(f"output path must not use symlinked components: {symlink_component}")
    try:
        target = lexical_target.resolve()
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"output path could not be resolved: {output}") from exc
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"output path escapes the working directory: {output}") from exc
    if target.exists() and target.is_dir():
        raise ValueError(f"output path must be a file path: {output}")
    return target


def _write_status_auth_report(output_path: Path, report: dict[str, Any], *, as_json: bool) -> None:
    output = _build_status_auth_report_output(report, as_json=as_json)
    safe_output = redact_status_text(output)
    data = safe_output.encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(output_path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)


def _build_status_auth_report_output(report: dict[str, Any], *, as_json: bool) -> str:
    safe_report = _sanitize_output(report)
    output = (
        json.dumps(safe_report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if as_json
        else render_text_report(safe_report)
    )
    return _sanitize_status_auth_output(output)


def _sanitize_status_auth_output(output: str) -> str:
    return redact_status_text(str(output or ""))


def _first_symlinked_path_component(path: Path) -> Path | None:
    absolute = Path(os.path.abspath(os.fspath(path)))
    for candidate in (absolute, *absolute.parents):
        try:
            if candidate.is_symlink():
                return candidate
        except OSError:
            return candidate
    return None


def _emit_status_auth_report(output: str) -> None:
    safe_output = redact_status_text(str(output or ""))
    sys.stdout.buffer.write(safe_output.encode("utf-8"))


@dataclass(frozen=True)
class StatusAuthReportOptions:
    instances_dir: Path
    instances: tuple[str, ...] = ()
    provider: InstanceSecretProvider | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_status_auth_report(
    *,
    instances_dir: str | Path = DEFAULT_INSTANCES_DIR,
    instances: Sequence[str] = (),
    provider: InstanceSecretProvider | None = None,
) -> dict[str, Any]:
    options = StatusAuthReportOptions(
        instances_dir=Path(instances_dir),
        instances=tuple(instances),
        provider=provider or runtime_secret_provider(),
    )
    selected_instances = discover_instances(options.instances_dir, options.instances)
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "scope": "status_auth",
        "generated_at": utc_now(),
        "instances_dir": str(options.instances_dir),
        "instance_count": len(selected_instances),
        "instances": [],
        "totals": {
            "accounts": 0,
            "authorized_accounts": 0,
            "outbox_items": 0,
            "dispatch_results": 0,
            "store_errors": 0,
        },
    }
    for instance_name in selected_instances:
        instance_report = build_instance_status_auth_report(
            instances_dir=options.instances_dir,
            instance_name=instance_name,
            provider=options.provider,
        )
        report["instances"].append(instance_report)
        _add_totals(report["totals"], instance_report)
    return report


def bootstrap_status_auth_secrets(
    *,
    instances_dir: str | Path = DEFAULT_INSTANCES_DIR,
    instances: Sequence[str] = (),
    provider: InstanceSecretProvider | None = None,
) -> dict[str, Any]:
    resolved_instances_dir = Path(instances_dir)
    requested_instances = tuple(instances)
    requested_instances = requested_instances or DEFAULT_STATUS_AUTH_INSTANCES
    selected_instances = discover_instances(resolved_instances_dir, requested_instances)
    bootstrap_provider = provider or runtime_secret_provider()
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "scope": "status_auth_bootstrap",
        "generated_at": utc_now(),
        "instances_dir": str(resolved_instances_dir),
        "instance_count": len(selected_instances),
        "purposes": list(STATUS_AUTH_BOOTSTRAP_PURPOSES),
        "instances": [],
        "totals": {
            "created_purposes": 0,
            "existing_purposes": 0,
            "failed_purposes": 0,
            "missing_instances": 0,
        },
    }
    for instance_name in selected_instances:
        instance_report = bootstrap_instance_status_auth_secrets(
            instances_dir=resolved_instances_dir,
            instance_name=instance_name,
            provider=bootstrap_provider,
        )
        report["instances"].append(instance_report)
        _add_bootstrap_totals(report["totals"], instance_report)
    return report


def bootstrap_instance_status_auth_secrets(
    *,
    instances_dir: Path,
    instance_name: str,
    provider: InstanceSecretProvider,
) -> dict[str, Any]:
    instance_name = _validate_instance_name(instances_dir, instance_name)
    instance_dir = instances_dir / instance_name
    accounts_root = instance_dir / "data" / "accounts"
    bootstrap: dict[str, Any] = {
        "purposes": [],
        "created_purposes": 0,
        "existing_purposes": 0,
        "failed_purposes": 0,
        "errors": [],
    }
    instance_report: dict[str, Any] = {
        "instance": instance_name,
        "instance_dir": str(instance_dir),
        "instance_dir_exists": instance_dir.exists(),
        "accounts_root": str(accounts_root),
        "bootstrap": bootstrap,
    }
    if not instance_dir.exists():
        bootstrap["errors"].append("missing_instance_dir")
        return instance_report
    try:
        store = AccountStore(
            accounts_root,
            instance_name,
            secret_provider=provider,
            create_dirs=True,
            secret_guard_purposes=STATUS_AUTH_BOOTSTRAP_PURPOSES,
        )
    except (AccountStoreError, OSError, ValueError) as exc:
        bootstrap["errors"].append(f"store:{type(exc).__name__}:{exc}")
        return instance_report
    for purpose in STATUS_AUTH_BOOTSTRAP_PURPOSES:
        purpose_report = _bootstrap_purpose(store.secret_provider, instance_name, purpose)
        bootstrap["purposes"].append(purpose_report)
        status = str(purpose_report.get("status") or "")
        if status == "created":
            bootstrap["created_purposes"] += 1
        elif status == "existing":
            bootstrap["existing_purposes"] += 1
        elif status == "failed":
            bootstrap["failed_purposes"] += 1
    return instance_report


def build_instance_status_auth_report(
    *,
    instances_dir: Path,
    instance_name: str,
    provider: InstanceSecretProvider,
) -> dict[str, Any]:
    instance_name = _validate_instance_name(instances_dir, instance_name)
    accounts_root = instances_dir / instance_name / "data" / "accounts"
    status_auth: dict[str, Any] = {
        "accounts": [],
        "account_count": 0,
        "authorized_accounts": 0,
        "outbox_items": 0,
        "dispatch_results": 0,
        "outbox_status_counts": {},
        "dispatch_status_counts": {},
        "errors": [],
    }
    try:
        store = AccountStore(
            accounts_root,
            instance_name,
            secret_provider=provider,
            create_dirs=False,
            secret_guard_purposes=(INSTANCE_MAPPING_KEY_PURPOSE,),
        )
    except (AccountStoreError, OSError, ValueError) as exc:
        status_auth["errors"].append(f"store:{type(exc).__name__}:{exc}")
        return {
            "instance": instance_name,
            "accounts_root": str(accounts_root),
            "accounts_root_exists": accounts_root.exists(),
            "status_auth": status_auth,
        }
    try:
        account_ids = store.list_account_ids(include_unresolvable=False)
    except (AccountStoreError, OSError, ValueError) as exc:
        status_auth["errors"].append(f"account_list:{type(exc).__name__}:{exc}")
        account_ids = ()
    outbox_status_counts: Counter[str] = Counter()
    dispatch_status_counts: Counter[str] = Counter()
    for account_id in account_ids:
        account_report = _build_account_status_auth_report(store, account_id)
        if account_report is None:
            continue
        status_auth["accounts"].append(account_report)
        status_auth["account_count"] += 1
        if account_report.get("authorized"):
            status_auth["authorized_accounts"] += 1
        status_auth["outbox_items"] += int(account_report.get("outbox_items", 0) or 0)
        status_auth["dispatch_results"] += int(account_report.get("dispatch_results", 0) or 0)
        outbox_status_counts.update(account_report.get("outbox_status_counts", {}))
        dispatch_status_counts.update(account_report.get("dispatch_status_counts", {}))
    status_auth["outbox_status_counts"] = dict(sorted(outbox_status_counts.items()))
    status_auth["dispatch_status_counts"] = dict(sorted(dispatch_status_counts.items()))
    return {
        "instance": instance_name,
        "accounts_root": str(accounts_root),
        "accounts_root_exists": accounts_root.exists(),
        "status_auth": status_auth,
    }


def render_text_report(report: Mapping[str, Any]) -> str:
    if report.get("scope") == "status_auth_bootstrap":
        return render_bootstrap_text_report(report)
    lines = [
        "TeeBotus Status-Auth Admin Report",
        "",
        f"generated_at: {report.get('generated_at', '')}",
        f"instances_dir: {report.get('instances_dir', '')}",
        "",
        "Totals:",
    ]
    totals = report.get("totals", {})
    if isinstance(totals, Mapping):
        for key in sorted(totals):
            lines.append(f"  {key}: {totals[key]}")
    for instance in report.get("instances", []):
        if not isinstance(instance, Mapping):
            continue
        status_auth = instance.get("status_auth", {})
        if not isinstance(status_auth, Mapping):
            status_auth = {}
        lines.extend(["", f"Instance: {instance.get('instance', '')}"])
        lines.append(f"  authorized_accounts: {status_auth.get('authorized_accounts', 0)}")
        lines.append(f"  outbox_items: {status_auth.get('outbox_items', 0)}")
        for account in status_auth.get("accounts", []):
            if not isinstance(account, Mapping):
                continue
            route = account.get("route", {})
            if not isinstance(route, Mapping):
                route = {}
            lines.append(
                "  account: "
                f"{account.get('account_id', '')} authorized={_yes_no(account.get('authorized'))} "
                f"route={route.get('channel', '<none>')}:{route.get('chat_id', '<none>')} "
                f"outbox={account.get('outbox_items', 0)} dispatch={account.get('dispatch_results', 0)}"
            )
    return "\n".join(lines) + "\n"


def render_bootstrap_text_report(report: Mapping[str, Any]) -> str:
    lines = [
        "TeeBotus Status-Auth Bootstrap Report",
        "",
        f"generated_at: {report.get('generated_at', '')}",
        f"instances_dir: {report.get('instances_dir', '')}",
        "",
        "Totals:",
    ]
    totals = report.get("totals", {})
    if isinstance(totals, Mapping):
        for key in sorted(totals):
            lines.append(f"  {key}: {totals[key]}")
    for instance in report.get("instances", []):
        if not isinstance(instance, Mapping):
            continue
        bootstrap = instance.get("bootstrap", {})
        if not isinstance(bootstrap, Mapping):
            bootstrap = {}
        lines.extend(["", f"Instance: {instance.get('instance', '')}"])
        lines.append(f"  instance_dir_exists: {_yes_no(instance.get('instance_dir_exists'))}")
        lines.append(f"  created_purposes: {bootstrap.get('created_purposes', 0)}")
        lines.append(f"  existing_purposes: {bootstrap.get('existing_purposes', 0)}")
        lines.append(f"  failed_purposes: {bootstrap.get('failed_purposes', 0)}")
        for purpose in bootstrap.get("purposes", []):
            if not isinstance(purpose, Mapping):
                continue
            lines.append(f"  purpose: {purpose.get('purpose', '')} status={purpose.get('status', '')}")
        for error in bootstrap.get("errors", []):
            lines.append(f"  error: {error}")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None, *, provider: InstanceSecretProvider | None = None) -> int:
    if provider is None:
        try:
            from TeeBotus.bot import _load_runtime_environment

            _load_runtime_environment()
        except Exception:
            pass
    parser = argparse.ArgumentParser(prog="python3 -m TeeBotus.admin status-auth")
    subparsers = parser.add_subparsers(dest="command", required=True)
    report_parser = subparsers.add_parser("report")
    report_parser.add_argument("--instances-dir", default=DEFAULT_INSTANCES_DIR)
    report_parser.add_argument("--instances", default="", help="Comma-separated instance list. Defaults to all folders with Bot_Verhalten.md.")
    report_parser.add_argument("--format", choices=("text", "json"), default="text")
    report_parser.add_argument("--output", default="")
    bootstrap_parser = subparsers.add_parser("bootstrap")
    bootstrap_parser.add_argument("--instances-dir", default=DEFAULT_INSTANCES_DIR)
    bootstrap_parser.add_argument("--instances", default="", help="Comma-separated instance list. Defaults to protected status-auth instances.")
    bootstrap_parser.add_argument("--format", choices=("text", "json"), default="text")
    bootstrap_parser.add_argument("--output", default="")

    args = parser.parse_args(list(argv) if argv is not None else None)
    load_project_dotenv_for_instances(args.instances_dir)
    instances = parse_csv(getattr(args, "instances", None))
    if args.command == "bootstrap":
        report = bootstrap_status_auth_secrets(
            instances_dir=args.instances_dir,
            instances=instances,
            provider=provider or runtime_secret_provider(),
        )
    else:
        report = build_status_auth_report(
            instances_dir=args.instances_dir,
            instances=instances,
            provider=provider or runtime_secret_provider(),
        )
    if args.output:
        try:
            output_path = _safe_output_path(args.output, base_dir=args.instances_dir)
        except ValueError as exc:
            print(f"status-auth: {exc}", file=sys.stderr)
            return 2
        try:
            _write_status_auth_report(output_path, report, as_json=(args.format == "json"))
        except OSError as exc:
            print(f"status-auth: unable to write output: {exc}", file=sys.stderr)
            return 2
    else:
        output = _build_status_auth_report_output(report, as_json=(args.format == "json"))
        _emit_status_auth_report(output)
    return 0


def _build_account_status_auth_report(store: AccountStore, account_id: str) -> dict[str, Any] | None:
    try:
        state = store.read_status_auth_state(account_id)
        outbox = store.read_status_outbox(account_id)
        dispatch_results = store.read_status_dispatch_results(account_id)
    except (AccountStoreError, OSError, ValueError) as exc:
        return {
            "account_id": account_id,
            "authorized": False,
            "error": f"{type(exc).__name__}:{exc}",
            "outbox_items": 0,
            "dispatch_results": 0,
        }
    if not isinstance(state, Mapping):
        state = {}
    authorized = bool(state.get("authorized") is True)
    if not authorized and not outbox and not dispatch_results:
        return None
    route = None
    route_error = ""
    if authorized:
        try:
            route = select_proactive_route(store, account_id)
        except (AccountStoreError, OSError) as exc:
            route_error = f"{type(exc).__name__}:{exc}"
            route = None
    return {
        "account_id": account_id,
        "authorized": authorized,
        "authorized_at": str(state.get("authorized_at") or ""),
        "updated_at": str(state.get("updated_at") or ""),
        "route_error": route_error,
        "route": _public_route(route),
        "outbox_items": len(outbox),
        "dispatch_results": len(dispatch_results),
        "outbox_status_counts": _status_counts(outbox),
        "dispatch_status_counts": _status_counts(dispatch_results),
    }


def _public_route(route: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(route, Mapping):
        return {}
    result: dict[str, Any] = {
        "channel": str(route.get("channel") or ""),
        "chat_id": str(route.get("chat_id") or ""),
        "chat_type": str(route.get("chat_type") or ""),
    }
    if route.get("adapter_slot") is not None:
        result["adapter_slot"] = route.get("adapter_slot")
    return result


def _validate_instance_name(instances_dir: Path, instance_name: str) -> str:
    normalized = str(instance_name or "").strip()
    if not normalized or discover_instances(instances_dir, (normalized,)) != (normalized,):
        raise ValueError(f"invalid instance name: {instance_name}")
    return normalized


def _status_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        status = str(row.get("status") or "unknown").strip().casefold() or "unknown"
        counts[status] += 1
    return dict(sorted(counts.items()))


def _add_totals(totals: dict[str, int], instance_report: Mapping[str, Any]) -> None:
    status_auth = instance_report.get("status_auth", {})
    if not isinstance(status_auth, Mapping):
        return
    totals["accounts"] += int(status_auth.get("account_count", 0) or 0)
    totals["authorized_accounts"] += int(status_auth.get("authorized_accounts", 0) or 0)
    totals["outbox_items"] += int(status_auth.get("outbox_items", 0) or 0)
    totals["dispatch_results"] += int(status_auth.get("dispatch_results", 0) or 0)
    if status_auth.get("errors"):
        totals["store_errors"] += 1


def _bootstrap_purpose(provider: InstanceSecretProvider, instance_name: str, purpose: str) -> dict[str, Any]:
    existed_before = _provider_has_secret(provider, instance_name, purpose)
    try:
        _provider_get_or_create_secret(provider, instance_name, purpose)
    except (AccountStoreError, OSError, ValueError) as exc:
        return {
            "purpose": purpose,
            "status": "failed",
            "error": f"{type(exc).__name__}:{exc}",
        }
    exists_after = _provider_has_secret(provider, instance_name, purpose)
    return {
        "purpose": purpose,
        "status": "existing" if existed_before else ("created" if exists_after else "available"),
    }


def _provider_get_or_create_secret(provider: InstanceSecretProvider, instance_name: str, purpose: str) -> bytes:
    creator = getattr(provider, "get_or_create_secret", None)
    if callable(creator):
        return creator(instance_name, purpose, reason="status-auth bootstrap")
    return provider.get_secret(instance_name, purpose)


def _provider_has_secret(provider: InstanceSecretProvider, instance_name: str, purpose: str) -> bool:
    has_secret = getattr(provider, "has_secret", None)
    if callable(has_secret):
        try:
            return bool(has_secret(instance_name, purpose))
        except (AccountStoreError, OSError, ValueError):
            return False
    try:
        provider.get_secret(instance_name, purpose)
    except (AccountStoreError, OSError, ValueError):
        return False
    return True


def _add_bootstrap_totals(totals: dict[str, int], instance_report: Mapping[str, Any]) -> None:
    bootstrap = instance_report.get("bootstrap", {})
    if not isinstance(bootstrap, Mapping):
        return
    if not instance_report.get("instance_dir_exists"):
        totals["missing_instances"] += 1
    totals["created_purposes"] += int(bootstrap.get("created_purposes", 0) or 0)
    totals["existing_purposes"] += int(bootstrap.get("existing_purposes", 0) or 0)
    totals["failed_purposes"] += int(bootstrap.get("failed_purposes", 0) or 0)


def _yes_no(value: object) -> str:
    return "yes" if bool(value) else "no"


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
