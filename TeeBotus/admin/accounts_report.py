from __future__ import annotations

import argparse
import base64
import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from TeeBotus.runtime.accounts import (
    ACCOUNT_IDENTITIES_FILENAME,
    ACCOUNT_INDEX_FILENAME,
    ACCOUNT_PROFILE_FILENAME,
    ACCOUNT_SECRETS_FILENAME,
    ACCOUNTS_DIRNAME,
    INSTANCE_KEY_SIZE_BYTES,
    INSTANCE_MAPPING_KEY_PURPOSE,
    INSTANCE_PEPPER_PURPOSE,
    INSTANCE_SECRET_SERVICE,
    SECRET_TOOL_COMMAND,
    USER_HABITS_FILENAME,
    USER_MEMORY_ENTRIES_FILENAME,
    USER_MEMORY_INDEX_FILENAME,
    AccountStore,
    AccountStoreError,
    InstanceSecretProvider,
    SecretToolInstanceSecretProvider,
    TOKEN_HEX_RE,
    telegram_identity_key,
)

BOT_INSTRUCTION_FILENAME = "Bot_Verhalten.md"
DEFAULT_INSTANCES_DIR = "instances"
LEGACY_USER_FILES = (USER_MEMORY_INDEX_FILENAME, USER_MEMORY_ENTRIES_FILENAME, USER_HABITS_FILENAME)
LEGACY_ENCRYPTION_MAGICS = {"TMBMEM1", "TMBKEY1", "TMBMAP1"}
REPORT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ReadOnlySecretToolInstanceSecretProvider:
    """Read-only Secret Service provider for admin reports.

    Unlike ``SecretToolInstanceSecretProvider``, this provider never creates missing
    secrets. Reports must not mutate the host keyring merely because an operator asked
    what would happen during migration.
    """

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
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "instances_dir": str(resolved_instances_dir),
        "instance_count": len(selected_instances),
        "instances": [],
        "totals": {
            "account_dirs": 0,
            "indexed_accounts": 0,
            "linked_identities": 0,
            "legacy_user_dirs": 0,
            "migration_create_account": 0,
            "migration_already_mapped": 0,
            "migration_requires_live_legacy_key": 0,
            "migration_empty_legacy_dir": 0,
            "migration_blocked_by_unreadable_account_store": 0,
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
    store_report = _build_store_report(store)
    legacy_report = _build_legacy_report(
        data_dir,
        store if store_report["readable"] else None,
        account_store_readable=bool(store_report["readable"]),
    )
    return {
        "instance": instance_name,
        "instance_dir": str(instance_dir),
        "instruction_file_exists": (instance_dir / BOT_INSTRUCTION_FILENAME).exists(),
        "data_dir": str(data_dir),
        "data_dir_exists": data_dir.exists(),
        "accounts_root": str(accounts_root),
        "account_store": store_report,
        "legacy_users": legacy_report,
        "migration_plan": _build_migration_plan(legacy_report),
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


def _build_legacy_report(data_dir: Path, store: AccountStore | None, *, account_store_readable: bool = True) -> dict[str, Any]:
    users_root = data_dir / "users"
    legacy_dirs = _legacy_user_dirs(users_root)
    entries: list[dict[str, Any]] = []
    for legacy_dir in legacy_dirs:
        entries.append(_inspect_legacy_user_dir(legacy_dir, store, account_store_readable=account_store_readable))
    by_action: dict[str, int] = {}
    for entry in entries:
        action = str(entry.get("recommended_action") or "unknown")
        by_action[action] = by_action.get(action, 0) + 1
    return {
        "root": str(users_root),
        "root_exists": users_root.exists(),
        "legacy_user_dir_count": len(legacy_dirs),
        "recommended_actions": by_action,
        "users": entries,
    }


def _inspect_legacy_user_dir(legacy_dir: Path, store: AccountStore | None, *, account_store_readable: bool = True) -> dict[str, Any]:
    sender_id = legacy_dir.name
    identity_key = telegram_identity_key(sender_id)
    files = {filename: (legacy_dir / filename).exists() for filename in LEGACY_USER_FILES}
    encrypted_structured = any(_looks_like_legacy_encrypted_payload(legacy_dir / filename) for filename in (USER_MEMORY_INDEX_FILENAME, USER_MEMORY_ENTRIES_FILENAME))
    existing_account_id = store.get_account_for_identity(identity_key) if store is not None else None
    if existing_account_id:
        action = "already_mapped"
        reason = "telegram identity is already linked to an account"
    elif not any(files.values()):
        action = "empty_legacy_dir"
        reason = "legacy user directory contains no known memory files"
    elif not account_store_readable:
        action = "blocked_by_unreadable_account_store"
        reason = "account store is not readable, so migration must not create duplicate accounts"
    elif encrypted_structured:
        action = "requires_live_legacy_key_migration"
        reason = "legacy structured memory appears encrypted and must be migrated by the live bot with the legacy key backend"
    else:
        action = "create_account_and_migrate"
        reason = "plaintext legacy memory can be migrated to an account directory"
    return {
        "sender_id": sender_id,
        "identity_key": identity_key,
        "existing_account_id": existing_account_id or "",
        "files": files,
        "encrypted_structured_memory": encrypted_structured,
        "recommended_action": action,
        "reason": reason,
    }


def _build_migration_plan(legacy_report: Mapping[str, Any]) -> dict[str, Any]:
    actions = legacy_report.get("recommended_actions") if isinstance(legacy_report, Mapping) else {}
    if not isinstance(actions, Mapping):
        actions = {}
    return {
        "mode": "dry_run_report_only",
        "destructive": False,
        "would_create_accounts": int(actions.get("create_account_and_migrate", 0)),
        "already_mapped": int(actions.get("already_mapped", 0)),
        "requires_live_legacy_key_migration": int(actions.get("requires_live_legacy_key_migration", 0)),
        "empty_legacy_dirs": int(actions.get("empty_legacy_dir", 0)),
        "blocked_by_unreadable_account_store": int(actions.get("blocked_by_unreadable_account_store", 0)),
        "actual_migration_implemented": False,
        "next_step": "Run the live bot migration path or a dedicated migration command after reviewing this report.",
    }


def _add_instance_totals(totals: dict[str, int], instance_report: Mapping[str, Any]) -> None:
    store = instance_report.get("account_store", {}) if isinstance(instance_report, Mapping) else {}
    legacy = instance_report.get("legacy_users", {}) if isinstance(instance_report, Mapping) else {}
    migration = instance_report.get("migration_plan", {}) if isinstance(instance_report, Mapping) else {}
    if isinstance(store, Mapping):
        totals["account_dirs"] += int(store.get("account_directories", 0) or 0)
        totals["indexed_accounts"] += int(store.get("indexed_accounts", 0) or 0)
        totals["linked_identities"] += int(store.get("linked_identities", 0) or 0)
        if store.get("errors"):
            totals["store_errors"] += 1
    if isinstance(legacy, Mapping):
        totals["legacy_user_dirs"] += int(legacy.get("legacy_user_dir_count", 0) or 0)
    if isinstance(migration, Mapping):
        totals["migration_create_account"] += int(migration.get("would_create_accounts", 0) or 0)
        totals["migration_already_mapped"] += int(migration.get("already_mapped", 0) or 0)
        totals["migration_requires_live_legacy_key"] += int(migration.get("requires_live_legacy_key_migration", 0) or 0)
        totals["migration_empty_legacy_dir"] += int(migration.get("empty_legacy_dirs", 0) or 0)
        totals["migration_blocked_by_unreadable_account_store"] += int(migration.get("blocked_by_unreadable_account_store", 0) or 0)


def _account_dirs(accounts_dir: Path) -> list[Path]:
    if not accounts_dir.exists():
        return []
    return sorted(path for path in accounts_dir.iterdir() if path.is_dir() and TOKEN_HEX_RE.fullmatch(path.name))


def _legacy_user_dirs(users_root: Path) -> list[Path]:
    if not users_root.exists():
        return []
    excluded = {"telegram", "signal", "accounts", "runtime"}
    return sorted(
        path
        for path in users_root.iterdir()
        if path.is_dir() and not path.name.startswith(".") and path.name not in excluded
    )


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


def _looks_like_legacy_encrypted_payload(path: Path) -> bool:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return False
    if not raw.lstrip().startswith(b"{"):
        return False
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and str(payload.get("magic") or "") in LEGACY_ENCRYPTION_MAGICS and isinstance(payload.get("ciphertext"), str)


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
        legacy = instance.get("legacy_users", {})
        plan = instance.get("migration_plan", {})
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
        if isinstance(legacy, Mapping):
            lines.append(f"  legacy_user_dirs: {legacy.get('legacy_user_dir_count', 0)}")
            actions = legacy.get("recommended_actions", {})
            if isinstance(actions, Mapping):
                for key in sorted(actions):
                    lines.append(f"    {key}: {actions[key]}")
        if isinstance(plan, Mapping):
            lines.extend([
                f"  migration_would_create_accounts: {plan.get('would_create_accounts', 0)}",
                f"  migration_requires_live_legacy_key: {plan.get('requires_live_legacy_key_migration', 0)}",
                f"  migration_blocked_by_unreadable_account_store: {plan.get('blocked_by_unreadable_account_store', 0)}",
                f"  actual_migration_implemented: {plan.get('actual_migration_implemented', False)}",
            ])
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

    migrate_parser = accounts_subparsers.add_parser("migrate")
    _add_common_report_args(migrate_parser)
    migrate_parser.add_argument("--dry-run", action="store_true", help="Only print the migration report. Actual migration is not implemented in this patch.")

    args = parser.parse_args(list(argv) if argv is not None else None)
    instances = parse_csv(getattr(args, "instances", None))
    report = build_accounts_admin_report(instances_dir=args.instances_dir, instances=instances)
    if args.area == "accounts" and args.command == "migrate" and not args.dry_run:
        print("Actual account migration is intentionally not implemented in this admin-report patch. Re-run with --dry-run.")
        return 2
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
