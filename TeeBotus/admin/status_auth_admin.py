from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from TeeBotus.admin.accounts_report import DEFAULT_INSTANCES_DIR, ReadOnlySecretToolInstanceSecretProvider, discover_instances, parse_csv
from TeeBotus.runtime.accounts import AccountStore, AccountStoreError, INSTANCE_MAPPING_KEY_PURPOSE, InstanceSecretProvider
from TeeBotus.runtime.proactive_agent import select_proactive_route

REPORT_SCHEMA_VERSION = 1


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
        provider=provider or ReadOnlySecretToolInstanceSecretProvider(),
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


def build_instance_status_auth_report(
    *,
    instances_dir: Path,
    instance_name: str,
    provider: InstanceSecretProvider,
) -> dict[str, Any]:
    accounts_root = instances_dir / instance_name / "data" / "accounts"
    store = AccountStore(
        accounts_root,
        instance_name,
        secret_provider=provider,
        create_dirs=False,
        secret_guard_purposes=(INSTANCE_MAPPING_KEY_PURPOSE,),
    )
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


def main(argv: Sequence[str] | None = None, *, provider: InstanceSecretProvider | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m TeeBotus.admin status-auth")
    subparsers = parser.add_subparsers(dest="command", required=True)
    report_parser = subparsers.add_parser("report")
    report_parser.add_argument("--instances-dir", default=DEFAULT_INSTANCES_DIR)
    report_parser.add_argument("--instances", default="", help="Comma-separated instance list. Defaults to all folders with Bot_Verhalten.md.")
    report_parser.add_argument("--format", choices=("text", "json"), default="text")
    report_parser.add_argument("--output", default="")

    args = parser.parse_args(list(argv) if argv is not None else None)
    instances = parse_csv(getattr(args, "instances", None))
    report = build_status_auth_report(
        instances_dir=args.instances_dir,
        instances=instances,
        provider=provider,
    )
    output = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n" if args.format == "json" else render_text_report(report)
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output, end="")
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


def _yes_no(value: object) -> str:
    return "yes" if bool(value) else "no"


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
