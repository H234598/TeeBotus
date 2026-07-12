from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from TeeBotus.runtime.accounts import (
    ACCOUNT_IDENTITIES_FILENAME,
    ACCOUNT_INDEX_FILENAME,
    ACCOUNT_KEYRING_FILENAME,
    ACCOUNT_PROFILE_FILENAME,
    ACCOUNT_SECRETS_FILENAME,
    INSTANCE_MAPPING_KEY_PURPOSE,
    INSTANCE_KEY_SIZE_BYTES,
    INSTANCE_SECRET_SERVICE,
    SECRET_TOOL_COMMAND,
    AccountStore,
    AccountStoreError,
    InstanceSecretProvider,
    TOKEN_HEX_RE,
)
from TeeBotus.runtime.config import RuntimeConfigError, build_account_run_configs
from TeeBotus.runtime.dotenv import load_project_dotenv_for_instances, project_root_for_instances_dir

BOT_INSTRUCTION_FILENAME = "Bot_Verhalten.md"
DEFAULT_INSTANCES_DIR = "instances"
DEFAULT_RUNTIME_CHANNELS = ("telegram", "signal", "matrix")
REPORT_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class ReadOnlySecretToolInstanceSecretProvider:
    """Read-only Secret Service provider for admin reports."""

    command: str = SECRET_TOOL_COMMAND
    _cache: dict[tuple[str, str], bytes] = field(default_factory=dict, init=False, repr=False, compare=False)

    def get_secret(self, instance_name: str, purpose: str) -> bytes:
        cache_key = (str(instance_name), str(purpose))
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        binary = shutil.which(self.command)
        if binary is None:
            raise AccountStoreError("secret-tool is not installed")
        result = subprocess.run(
            [
                binary,
                "lookup",
                "application",
                INSTANCE_SECRET_SERVICE,
                "instance",
                instance_name,
                "purpose",
                purpose,
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise AccountStoreError(f"instance secret is missing for purpose={purpose}")
        try:
            secret = base64.urlsafe_b64decode(result.stdout.strip().encode("ascii"))
        except Exception as exc:  # noqa: BLE001
            raise AccountStoreError("secret-tool returned invalid instance secret data") from exc
        if len(secret) != INSTANCE_KEY_SIZE_BYTES:
            raise AccountStoreError("instance secret has invalid length")
        self._cache[cache_key] = secret
        return secret


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_csv(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def discover_instances(instances_dir: Path, explicit: Sequence[str] = ()) -> tuple[str, ...]:
    if explicit:
        return tuple(dict.fromkeys(str(name).strip() for name in explicit if str(name).strip()))
    if not instances_dir.exists():
        return ()
    return tuple(
        sorted(
            path.name
            for path in instances_dir.iterdir()
            if path.is_dir() and (path / BOT_INSTRUCTION_FILENAME).exists()
        )
    )


def build_accounts_admin_report(
    *,
    instances_dir: str | Path = DEFAULT_INSTANCES_DIR,
    instances: Sequence[str] = (),
    provider: InstanceSecretProvider | None = None,
    env: Mapping[str, str] | None = None,
    runtime_channels: Sequence[str] = DEFAULT_RUNTIME_CHANNELS,
) -> dict[str, Any]:
    resolved_instances_dir = Path(instances_dir)
    provider = provider or ReadOnlySecretToolInstanceSecretProvider()
    env = {} if env is None else env
    selected_instances = discover_instances(resolved_instances_dir, instances)
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "instances_dir": str(resolved_instances_dir),
        "instance_count": len(selected_instances),
        "instances": [],
        "totals": {
            "account_dirs": 0,
            "identity_warnings": 0,
            "indexed_accounts": 0,
            "linked_identities": 0,
            "store_errors": 0,
        },
    }
    for instance_name in selected_instances:
        instance_report = build_instance_admin_report(
            instances_dir=resolved_instances_dir,
            instance_name=instance_name,
            provider=provider,
            env=env,
            runtime_channels=runtime_channels,
        )
        report["instances"].append(instance_report)
        _add_instance_totals(report["totals"], instance_report)
    return report


def build_instance_admin_report(
    *,
    instances_dir: Path,
    instance_name: str,
    provider: InstanceSecretProvider,
    env: Mapping[str, str],
    runtime_channels: Sequence[str],
) -> dict[str, Any]:
    instance_dir = instances_dir / instance_name
    data_dir = instance_dir / "data"
    accounts_root = data_dir / "accounts"
    store = AccountStore(
        accounts_root,
        instance_name,
        secret_provider=provider,
        create_dirs=False,
        secret_guard_purposes=(INSTANCE_MAPPING_KEY_PURPOSE,),
    )
    runtime_slots = _build_runtime_slot_report(instance_name, env=env, runtime_channels=runtime_channels)
    account_store = _build_store_report(store)
    return {
        "instance": instance_name,
        "instance_dir": str(instance_dir),
        "instruction_file_exists": (instance_dir / BOT_INSTRUCTION_FILENAME).exists(),
        "data_dir": str(data_dir),
        "data_dir_exists": data_dir.exists(),
        "accounts_root": str(accounts_root),
        "runtime_slots": runtime_slots,
        "account_store": account_store,
        "identity_health": _build_identity_health(account_store, runtime_slots),
    }


def _build_store_report(store: AccountStore) -> dict[str, Any]:
    accounts_dir = store.accounts_dir
    account_dirs = _account_dirs(accounts_dir)
    report: dict[str, Any] = {
        "readable": True,
        "errors": [],
        "accounts_root_exists": store.root.exists(),
        "account_directories": len(account_dirs),
        "account_directory_ids": [path.name for path in account_dirs],
        "account_index_readable": False,
        "identity_mapping_readable": False,
        "secrets_readable": False,
        "indexed_accounts": 0,
        "registered_accounts": 0,
        "unregistered_accounts": 0,
        "orphaned_accounts": 0,
        "tombstoned_account_dirs": 0,
        "dangling_account_dirs": 0,
        "warnings": [],
        "linked_identities": 0,
        "identities_by_channel": {},
        "active_secrets": 0,
        "encrypted_files_present": _encrypted_store_files_present(store),
    }
    try:
        index = store.vault.read_json(store.account_index_path, {"schema_version": 1, "accounts": {}})
        report["account_index_readable"] = True
        accounts = index.get("accounts") if isinstance(index, dict) else {}
        report["indexed_accounts"] = len(accounts) if isinstance(accounts, dict) else 0
    except AccountStoreError as exc:
        report["readable"] = False
        report["errors"].append(f"account_index: {exc}")

    try:
        identities = store.vault.read_json(store.identities_path, {})
        report["identity_mapping_readable"] = True
        if isinstance(identities, dict):
            report["linked_identities"] = len(identities)
            report["identities_by_channel"] = _count_identities_by_channel(identities)
    except AccountStoreError as exc:
        report["readable"] = False
        report["errors"].append(f"identity_mapping: {exc}")

    try:
        secrets_doc = store.vault.read_json(store.secrets_path, {})
        report["secrets_readable"] = True
        if isinstance(secrets_doc, dict):
            report["active_secrets"] = sum(1 for item in secrets_doc.values() if isinstance(item, dict) and item.get("active") is True)
    except AccountStoreError as exc:
        report["readable"] = False
        report["errors"].append(f"secrets: {exc}")

    for account_dir in account_dirs:
        profile_path = account_dir / ACCOUNT_PROFILE_FILENAME
        tombstone_path = account_dir / "Account_Tombstone.json"
        if tombstone_path.exists() and not profile_path.exists():
            report["tombstoned_account_dirs"] += 1
            continue
        if not profile_path.exists():
            report["dangling_account_dirs"] += 1
            report["warnings"].append("account directory has no Account_Profile.json")
            continue
        try:
            summary = store.account_summary(account_dir.name)
        except AccountStoreError as exc:
            report["readable"] = False
            report["errors"].append(f"account {account_dir.name}: {exc}")
            continue
        if summary.get("registered"):
            report["registered_accounts"] += 1
        else:
            report["unregistered_accounts"] += 1
        if summary.get("status") == "orphaned":
            report["orphaned_accounts"] += 1
    return report


def _add_instance_totals(totals: dict[str, int], instance_report: Mapping[str, Any]) -> None:
    store = instance_report.get("account_store", {}) if isinstance(instance_report, Mapping) else {}
    if isinstance(store, Mapping):
        totals["account_dirs"] += int(store.get("account_directories", 0) or 0)
        totals["indexed_accounts"] += int(store.get("indexed_accounts", 0) or 0)
        totals["linked_identities"] += int(store.get("linked_identities", 0) or 0)
        if store.get("errors"):
            totals["store_errors"] += 1
    identity_health = instance_report.get("identity_health", {}) if isinstance(instance_report, Mapping) else {}
    if isinstance(identity_health, Mapping):
        totals["identity_warnings"] = totals.get("identity_warnings", 0) + int(identity_health.get("warning_count", 0) or 0)


def _build_runtime_slot_report(
    instance_name: str,
    *,
    env: Mapping[str, str],
    runtime_channels: Sequence[str],
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "configured_channels": {},
        "configured_slot_labels_by_channel": {},
        "configured_slots": 0,
        "errors": [],
    }
    try:
        accounts = build_account_run_configs(instance_name, runtime_channels, env)
    except RuntimeConfigError as exc:
        report["errors"].append(str(exc))
        return report
    counts: dict[str, int] = {}
    labels_by_channel: dict[str, list[str]] = {}
    for account in accounts:
        channel = str(getattr(account, "channel", "") or "unknown")
        counts[channel] = counts.get(channel, 0) + 1
        label = str(getattr(account, "label", "") or "").strip()
        if label:
            labels_by_channel.setdefault(channel, []).append(label)
    report["configured_channels"] = dict(sorted(counts.items()))
    report["configured_slot_labels_by_channel"] = {
        channel: sorted(labels)
        for channel, labels in sorted(labels_by_channel.items())
    }
    report["configured_slots"] = sum(counts.values())
    return report


def _build_identity_health(account_store: Mapping[str, Any], runtime_slots: Mapping[str, Any]) -> dict[str, Any]:
    warnings: list[dict[str, Any]] = []
    identity_counts = _string_int_mapping(account_store.get("identities_by_channel", {}))
    runtime_counts = _string_int_mapping(runtime_slots.get("configured_channels", {}))
    runtime_labels = _string_list_mapping(runtime_slots.get("configured_slot_labels_by_channel", {}))
    linked_identities = int(account_store.get("linked_identities", 0) or 0)
    store_warnings = tuple(
        str(warning or "").strip()
        for warning in account_store.get("warnings", [])
        if str(warning or "").strip()
    )
    if store_warnings:
        warnings.append(
            {
                "code": "account_store_integrity_warning",
                "configured_runtime_slots": "<none>",
                "configured_runtime_labels": [],
                "linked_identities": linked_identities,
                "identity_channels": dict(sorted(identity_counts.items())),
                "message": (
                    f"Account store contains {len(store_warnings)} dangling account directory(ies) without readable profile metadata."
                ),
                "recommended_action": "Review the account-memory recovery report before quarantining the directories.",
            }
        )
    runtime_errors = tuple(str(error or "").strip() for error in runtime_slots.get("errors", []) if str(error or "").strip())
    if runtime_errors:
        warnings.append(
            {
                "code": "runtime_channel_config_error",
                "message": "Runtime channel configuration could not be fully evaluated; identity fragmentation checks may be incomplete.",
                "errors": list(runtime_errors),
            }
        )
    if linked_identities > 0 and runtime_counts:
        for channel, slot_count in sorted(runtime_counts.items()):
            identity_count = identity_counts.get(channel, 0)
            other_identity_count = _other_identity_count(identity_counts, channel)
            if slot_count > 0 and identity_count == 0 and other_identity_count > 0:
                warnings.append(
                    {
                        "code": "runtime_channel_without_identity",
                        "channel": channel,
                        "configured_runtime_slots": slot_count,
                        "configured_runtime_labels": runtime_labels.get(channel, []),
                        "linked_identities": 0,
                        "other_linked_identities": other_identity_count,
                        "identity_channels": dict(sorted(identity_counts.items())),
                        "message": (
                            f"{channel} runtime is configured, but no {channel} identities are linked. "
                            "Incoming chats on this channel will use a separate account until the user links it."
                        ),
                        "recommended_action": (
                            "First run /register or /rotate_secret in an already linked private chat, then open a private "
                            f"{channel} chat and link the existing account with /login <account_id> <secret>; "
                            "use /register there only for a deliberately separate account."
                        ),
                    }
                )
    if runtime_counts:
        for channel, identity_count in sorted(identity_counts.items()):
            if identity_count > 0 and runtime_counts.get(channel, 0) == 0:
                warnings.append(
                    {
                        "code": "identity_channel_without_runtime_slot",
                        "channel": channel,
                        "configured_runtime_slots": 0,
                        "configured_runtime_labels": [],
                        "linked_identities": identity_count,
                        "identity_channels": dict(sorted(identity_counts.items())),
                        "runtime_channels": dict(sorted(runtime_counts.items())),
                        "message": f"{channel} identities exist, but no {channel} runtime slot is configured.",
                        "recommended_action": (
                            f"Enable a {channel} runtime slot again or unlink/merge the stale {channel} identities after review."
                        ),
                    }
                )
    return {
        "status": "warning" if warnings else "ok",
        "warning_count": len(warnings),
        "warnings": warnings,
    }


def _string_int_mapping(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, int] = {}
    for key, item in value.items():
        channel = str(key or "").strip()
        if not channel:
            continue
        try:
            count = int(item or 0)
        except (TypeError, ValueError):
            count = 0
        result[channel] = count
    return result


def _string_list_mapping(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, list[str]] = {}
    for key, item in value.items():
        channel = str(key or "").strip()
        if not channel:
            continue
        if isinstance(item, str):
            labels = [part.strip() for part in item.split(",") if part.strip()]
        elif isinstance(item, (list, tuple, set)):
            labels = [str(part or "").strip() for part in item if str(part or "").strip()]
        else:
            labels = []
        result[channel] = sorted(dict.fromkeys(labels))
    return result


def _other_identity_count(identity_counts: Mapping[str, int], channel: str) -> int:
    return sum(count for name, count in identity_counts.items() if name != channel)


def _account_dirs(accounts_dir: Path) -> list[Path]:
    if not accounts_dir.exists():
        return []
    return sorted(
        path
        for path in accounts_dir.iterdir()
        if path.is_dir()
        and TOKEN_HEX_RE.fullmatch(path.name)
        and not _account_dir_contains_only_transient_locks(path)
    )


def _account_dir_contains_only_transient_locks(path: Path) -> bool:
    try:
        children = list(path.iterdir())
    except OSError:
        return False
    return bool(children) and all(
        child.is_file()
        and not child.is_symlink()
        and child.name.startswith(".")
        and child.name.endswith(".lock")
        for child in children
    )


def _encrypted_store_files_present(store: AccountStore) -> dict[str, bool]:
    return {
        ACCOUNT_KEYRING_FILENAME: (store.root / ACCOUNT_KEYRING_FILENAME).exists(),
        ACCOUNT_INDEX_FILENAME: store.account_index_path.exists(),
        ACCOUNT_IDENTITIES_FILENAME: store.identities_path.exists(),
        ACCOUNT_SECRETS_FILENAME: store.secrets_path.exists(),
    }


def _count_identities_by_channel(identities: Mapping[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key, payload in identities.items():
        channel = "unknown"
        if isinstance(payload, Mapping) and isinstance(payload.get("channel"), str) and payload["channel"]:
            channel = str(payload["channel"])
        else:
            channel = str(key).split(":", maxsplit=1)[0] if ":" in str(key) else "unknown"
        counts[channel] = counts.get(channel, 0) + 1
    return dict(sorted(counts.items()))


def render_text_report(report: Mapping[str, Any]) -> str:
    lines = [
        "TeeBotus Account Admin Report",
        f"Generated: {report.get('generated_at', '')}",
        f"Instances dir: {report.get('instances_dir', '')}",
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
        store = instance.get("account_store", {})
        lines.extend([
            "",
            f"Instance: {instance.get('instance', '')}",
            f"  instruction_file_exists: {instance.get('instruction_file_exists', False)}",
        ])
        if isinstance(store, Mapping):
            lines.extend([
                f"  account_store_readable: {store.get('readable', False)}",
                f"  account_directories: {store.get('account_directories', 0)}",
                f"  indexed_accounts: {store.get('indexed_accounts', 0)}",
                f"  linked_identities: {store.get('linked_identities', 0)}",
                f"  identities_by_channel: {_format_counts(store.get('identities_by_channel', {}))}",
                f"  active_secrets: {store.get('active_secrets', 0)}",
                f"  dangling_account_dirs: {store.get('dangling_account_dirs', 0)}",
            ])
            for error in store.get("errors", []) if isinstance(store.get("errors"), list) else []:
                lines.append(f"  error: {error}")
            for warning in store.get("warnings", []) if isinstance(store.get("warnings"), list) else []:
                lines.append(f"  account_store_warning: {warning}")
        runtime_slots = instance.get("runtime_slots", {})
        if isinstance(runtime_slots, Mapping):
            lines.append(f"  runtime_slots_by_channel: {_format_counts(runtime_slots.get('configured_channels', {}))}")
            for error in runtime_slots.get("errors", []) if isinstance(runtime_slots.get("errors"), list) else []:
                lines.append(f"  runtime_slot_error: {error}")
        identity_health = instance.get("identity_health", {})
        if isinstance(identity_health, Mapping):
            lines.append(f"  identity_health: {identity_health.get('status', 'unknown')}")
            for warning in identity_health.get("warnings", []) if isinstance(identity_health.get("warnings"), list) else []:
                if isinstance(warning, Mapping):
                    lines.append(
                        "  identity_warning: "
                        f"{warning.get('code', 'unknown')}"
                        f" channel={warning.get('channel', '<none>')}"
                        f" slots={warning.get('configured_runtime_slots', '<none>')}"
                        f" labels={_format_sequence(warning.get('configured_runtime_labels', []))}"
                        f" identities={_format_counts(warning.get('identity_channels', {}))}"
                        f" message={warning.get('message', '')}"
                        f" action={warning.get('recommended_action', '')}"
                    )
    return "\n".join(lines) + "\n"


def runtime_report_env(instances_dir: str | Path, *, base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base_env is None else base_env)
    load_project_dotenv_for_instances(instances_dir, environ=env)
    return env


def _project_root_for_instances_dir(instances_dir: str | Path) -> Path:
    return project_root_for_instances_dir(instances_dir)


def _format_counts(value: Any) -> str:
    counts = _string_int_mapping(value)
    if not counts:
        return "<none>"
    return ", ".join(f"{key}={counts[key]}" for key in sorted(counts))


def _format_sequence(value: Any) -> str:
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",") if part.strip()]
    elif isinstance(value, (list, tuple, set)):
        parts = [str(part or "").strip() for part in value if str(part or "").strip()]
    else:
        parts = []
    return ",".join(parts) if parts else "<none>"


def _json_dump(data: Mapping[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m TeeBotus admin")
    subparsers = parser.add_subparsers(dest="area", required=True)
    accounts_parser = subparsers.add_parser("accounts")
    accounts_subparsers = accounts_parser.add_subparsers(dest="command", required=True)

    report_parser = accounts_subparsers.add_parser("report")
    _add_common_report_args(report_parser)

    args = parser.parse_args(list(argv) if argv is not None else None)
    instances = parse_csv(getattr(args, "instances", None))
    report = build_accounts_admin_report(
        instances_dir=args.instances_dir,
        instances=instances,
        env=runtime_report_env(args.instances_dir),
    )
    output = _json_dump(report) if args.format == "json" else render_text_report(report)
    if args.output:
        try:
            Path(args.output).write_text(output, encoding="utf-8")
        except OSError as exc:
            print(f"accounts: unable to write output: {exc}", file=sys.stderr)
            return 2
    else:
        print(output, end="")
    return 0


def _add_common_report_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--instances-dir", default=DEFAULT_INSTANCES_DIR)
    parser.add_argument("--instances", default="", help="Comma-separated instance list. Defaults to all folders with Bot_Verhalten.md.")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--output", default="")


__all__ = [
    "ReadOnlySecretToolInstanceSecretProvider",
    "build_accounts_admin_report",
    "build_instance_admin_report",
    "discover_instances",
    "main",
    "render_text_report",
    "runtime_report_env",
]
