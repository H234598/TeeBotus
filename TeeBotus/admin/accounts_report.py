from __future__ import annotations

import argparse
import base64
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from TeeBotus.runtime.accounts import (
    ACCOUNT_IDENTITIES_FILENAME,
    ACCOUNT_INDEX_FILENAME,
    ACCOUNT_PROFILE_FILENAME,
    ACCOUNT_SECRETS_FILENAME,
    INSTANCE_KEY_SIZE_BYTES,
    INSTANCE_SECRET_SERVICE,
    SECRET_TOOL_COMMAND,
    AccountStore,
    AccountStoreError,
    InstanceSecretProvider,
    TOKEN_HEX_RE,
)

BOT_INSTRUCTION_FILENAME = "Bot_Verhalten.md"
DEFAULT_INSTANCES_DIR = "instances"
REPORT_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class ReadOnlySecretToolInstanceSecretProvider:
    """Read-only Secret Service provider for admin reports."""

    command: str = SECRET_TOOL_COMMAND

    def get_secret(self, instance_name: str, purpose: str) -> bytes:
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
) -> dict[str, Any]:
    resolved_instances_dir = Path(instances_dir)
    provider = provider or ReadOnlySecretToolInstanceSecretProvider()
    selected_instances = discover_instances(resolved_instances_dir, instances)
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "instances_dir": str(resolved_instances_dir),
        "instance_count": len(selected_instances),
        "instances": [],
        "totals": {
            "account_dirs": 0,
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
        )
        report["instances"].append(instance_report)
        _add_instance_totals(report["totals"], instance_report)
    return report


def build_instance_admin_report(
    *,
    instances_dir: Path,
    instance_name: str,
    provider: InstanceSecretProvider,
) -> dict[str, Any]:
    instance_dir = instances_dir / instance_name
    data_dir = instance_dir / "data"
    accounts_root = data_dir / "accounts"
    store = AccountStore(accounts_root, instance_name, secret_provider=provider, create_dirs=False)
    return {
        "instance": instance_name,
        "instance_dir": str(instance_dir),
        "instruction_file_exists": (instance_dir / BOT_INSTRUCTION_FILENAME).exists(),
        "data_dir": str(data_dir),
        "data_dir_exists": data_dir.exists(),
        "accounts_root": str(accounts_root),
        "account_store": _build_store_report(store),
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


def _account_dirs(accounts_dir: Path) -> list[Path]:
    if not accounts_dir.exists():
        return []
    return sorted(path for path in accounts_dir.iterdir() if path.is_dir() and TOKEN_HEX_RE.fullmatch(path.name))


def _encrypted_store_files_present(store: AccountStore) -> dict[str, bool]:
    return {
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
                f"  active_secrets: {store.get('active_secrets', 0)}",
            ])
            for error in store.get("errors", []) if isinstance(store.get("errors"), list) else []:
                lines.append(f"  error: {error}")
    return "\n".join(lines) + "\n"


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
    report = build_accounts_admin_report(instances_dir=args.instances_dir, instances=instances)
    output = _json_dump(report) if args.format == "json" else render_text_report(report)
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
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
]
