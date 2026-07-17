from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from TeeBotus.runtime.accounts import AccountStore, AccountStoreError, TOKEN_HEX_RE
from TeeBotus.runtime.proactive_agent import approve_proactive_review_item, reject_proactive_review_item

StoreFactory = Callable[[Path, str], AccountStore]
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None, *, store_factory: StoreFactory | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review TeeBotus Proactive Agent human-review outbox items.")
    parser.add_argument("--instances-dir", default=str(PROJECT_ROOT / "instances"), help="TeeBotus instances directory.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    subparsers = parser.add_subparsers(dest="command")

    list_parser = subparsers.add_parser("list", help="List review_pending items.")
    list_parser.add_argument("--instance", action="append", default=[], help="Instance name to inspect. Can be repeated.")

    approve_parser = subparsers.add_parser("approve", help="Approve one review_pending item and queue it for dispatch.")
    _add_review_target_args(approve_parser)
    approve_parser.add_argument("--reviewer", default="operator", help="Reviewer name stored in the audit fields.")
    approve_parser.add_argument("--reason", default="", help="Short review reason stored in the audit fields.")

    reject_parser = subparsers.add_parser("reject", help="Reject one review_pending item and cancel it.")
    _add_review_target_args(reject_parser)
    reject_parser.add_argument("--reviewer", default="operator", help="Reviewer name stored in the audit fields.")
    reject_parser.add_argument("--reason", default="", help="Short review reason stored in the audit fields.")

    args = parser.parse_args(argv)
    command = args.command or "list"
    resolved_factory = store_factory or AccountStore
    instances_dir = Path(args.instances_dir)
    if command == "list":
        report = list_proactive_review_items(
            instances_dir=instances_dir,
            selected_instances=tuple(args.instance),
            store_factory=resolved_factory,
        )
        _print_or_json(report, json_output=args.json)
        return 0 if report["ok"] else 1
    if command in {"approve", "reject"}:
        report = review_proactive_item(
            instances_dir=instances_dir,
            instance_name=args.instance,
            account_id=args.account_id,
            item_id=args.item_id,
            action=command,
            reviewer=args.reviewer,
            reason=args.reason,
            store_factory=resolved_factory,
        )
        _print_or_json(report, json_output=args.json)
        return 0 if report["ok"] else 1
    print("Use one of: list, approve, reject.", file=sys.stderr)
    return 2


def list_proactive_review_items(
    *,
    instances_dir: Path,
    selected_instances: Iterable[str] = (),
    store_factory: StoreFactory | None = None,
) -> dict[str, Any]:
    resolved_factory = store_factory or AccountStore
    selected = tuple(
        dict.fromkeys(str(name or "").strip() for name in selected_instances if str(name or "").strip())
    )
    items: list[dict[str, Any]] = []
    errors = [f"{name}: invalid_instance_name" for name in selected if not _is_safe_instance_name(name)]
    try:
        instance_dirs = _instance_dirs(instances_dir, selected)
    except (OSError, ValueError) as exc:
        errors.append(f"instance_discovery_failed: {type(exc).__name__}: {exc}")
        instance_dirs = []
    for instance_dir in instance_dirs:
        if selected and instance_dir.is_symlink():
            errors.append(f"{instance_dir.name}: selected_instance_symlink")
            continue
        if selected and (not instance_dir.is_dir() or not (instance_dir / "data" / "accounts").is_dir()):
            errors.append(f"{instance_dir.name}: selected_instance_not_found")
            continue
        try:
            store = resolved_factory(instance_dir / "data" / "accounts", instance_dir.name)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{instance_dir.name}: {type(exc).__name__}: {exc}")
            continue
        try:
            account_ids = _account_ids(store)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{instance_dir.name}: {type(exc).__name__}: {exc}")
            continue
        for account_id in account_ids:
            try:
                rows = store.read_proactive_outbox(account_id)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{instance_dir.name}/{account_id}: {type(exc).__name__}: {exc}")
                continue
            for item in rows:
                if not isinstance(item, dict):
                    continue
                if str(item.get("status") or "").strip().casefold() != "review_pending":
                    continue
                items.append(_review_item_summary(instance_dir.name, account_id, item))
    return {"ok": not errors, "review_pending_count": len(items), "items": items, "errors": errors}


def review_proactive_item(
    *,
    instances_dir: Path,
    instance_name: str,
    account_id: str,
    item_id: str,
    action: str,
    reviewer: str = "operator",
    reason: str = "",
    store_factory: StoreFactory | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    resolved_factory = store_factory or AccountStore
    timestamp = now or datetime.now(timezone.utc)
    normalized_action = str(action or "").strip().casefold()
    if normalized_action not in {"approve", "reject"}:
        return {
            "ok": False,
            "action": normalized_action,
            "instance": str(instance_name or "").strip(),
            "account_id": account_id,
            "item_id": item_id,
            "reason": "unsupported_action",
            "route": {},
        }
    normalized_instance_name = str(instance_name or "").strip()
    if not _is_safe_instance_name(normalized_instance_name):
        return {
            "ok": False,
            "action": normalized_action,
            "instance": normalized_instance_name,
            "account_id": account_id,
            "item_id": item_id,
            "reason": "invalid_instance_name",
            "route": {},
        }
    instance_dir = instances_dir / normalized_instance_name
    if instances_dir.is_symlink():
        instance_error = "instances_root_symlink"
    elif instance_dir.is_symlink():
        instance_error = "instance_symlink"
    elif not instance_dir.is_dir() or not (instance_dir / "data" / "accounts").is_dir():
        instance_error = "instance_not_found"
    else:
        instance_error = ""
    if instance_error:
        return {
            "ok": False,
            "action": normalized_action,
            "instance": normalized_instance_name,
            "account_id": account_id,
            "item_id": item_id,
            "reason": instance_error,
            "route": {},
        }
    try:
        store = resolved_factory(instance_dir / "data" / "accounts", normalized_instance_name)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "action": normalized_action,
            "instance": normalized_instance_name,
            "account_id": account_id,
            "item_id": item_id,
            "reason": f"store_error:{type(exc).__name__}: {exc}",
            "route": {},
        }
    try:
        if normalized_action == "approve":
            decision = approve_proactive_review_item(store, account_id, item_id, reviewer=reviewer, reason=reason, now=timestamp)
        else:
            decision = reject_proactive_review_item(store, account_id, item_id, reviewer=reviewer, reason=reason, now=timestamp)
    except (AccountStoreError, OSError, ValueError) as exc:
        return {
            "ok": False,
            "action": normalized_action,
            "instance": normalized_instance_name,
            "account_id": account_id,
            "item_id": item_id,
            "reason": f"review_store_error:{type(exc).__name__}: {exc}",
            "route": {},
        }
    return {
        "ok": decision.allowed,
        "action": normalized_action,
        "instance": normalized_instance_name,
        "account_id": account_id,
        "item_id": item_id,
        "reason": decision.reason,
        "route": decision.route or {},
    }


def _add_review_target_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--instance", required=True, help="Instance name.")
    parser.add_argument("--account-id", required=True, help="Account id.")
    parser.add_argument("--item-id", required=True, help="Proactive outbox item id.")


def _review_item_summary(instance_name: str, account_id: str, item: dict[str, Any]) -> dict[str, Any]:
    route = item.get("route") if isinstance(item.get("route"), dict) else {}
    return {
        "instance": instance_name,
        "account_id": account_id,
        "item_id": str(item.get("id") or ""),
        "category": str(item.get("category") or ""),
        "intent": str(item.get("intent") or ""),
        "risk_gate": str(item.get("risk_gate") or ""),
        "due_at": str(item.get("due_at") or ""),
        "message_text": str(item.get("message_text") or ""),
        "reason_memory_ids": [str(value) for value in item.get("reason_memory_ids", []) if str(value or "").strip()]
        if isinstance(item.get("reason_memory_ids"), list)
        else [],
        "route": {
            "channel": str(route.get("channel") or ""),
            "chat_id": str(route.get("chat_id") or ""),
            "chat_type": str(route.get("chat_type") or ""),
            "adapter_slot": route.get("adapter_slot", 1),
        },
    }


def _print_or_json(report: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(report, indent=2, sort_keys=True))
        return
    if "items" in report:
        print(f"review_pending={report['review_pending_count']}")
        for item in report["items"]:
            print(
                f"- {item['instance']} account={item['account_id']} item={item['item_id']} "
                f"category={item['category']} risk_gate={item['risk_gate']}"
            )
            print(f"  intent={item['intent']} due_at={item['due_at']}")
            print(f"  route={item['route']['channel']}:{item['route']['chat_id']}")
            print(f"  text={item['message_text']}")
        for error in report["errors"]:
            print(f"ERROR {error}", file=sys.stderr)
        return
    state = "ok" if report["ok"] else "ERROR"
    print(
        f"{state} action={report['action']} instance={report.get('instance', '')} "
        f"account={report.get('account_id', '')} item={report.get('item_id', '')} reason={report['reason']}"
    )


def _instance_dirs(instances_dir: Path, selected: tuple[str, ...]) -> list[Path]:
    if instances_dir.is_symlink():
        raise ValueError("symlinked instances root")
    if selected:
        return [instances_dir / name for name in selected if _is_safe_instance_name(name)]
    if not instances_dir.exists():
        return []
    return sorted(
        path
        for path in instances_dir.iterdir()
        if not path.is_symlink() and path.is_dir() and (path / "data" / "accounts").exists()
    )


def _is_safe_instance_name(value: str) -> bool:
    path = Path(value)
    return (
        value not in {".", ".."}
        and not path.is_absolute()
        and path.name == value
        and "/" not in value
        and "\\" not in value
        and "\0" not in value
    )


def _account_dirs(accounts_dir: Path) -> list[Path]:
    if not accounts_dir.exists():
        return []
    return sorted(path for path in accounts_dir.iterdir() if path.is_dir() and TOKEN_HEX_RE.fullmatch(path.name))


def _account_ids(store: AccountStore) -> tuple[str, ...]:
    ids = {
        path.name
        for path in _account_dirs(store.accounts_dir)
        if TOKEN_HEX_RE.fullmatch(path.name)
    }
    list_account_ids = getattr(store, "list_account_ids", None)
    if callable(list_account_ids):
        listed_ids = list_account_ids(include_unresolvable=False)
        ids.update(
            account_id
            for account_id in (str(value or "").strip().casefold() for value in listed_ids)
            if TOKEN_HEX_RE.fullmatch(account_id)
        )
    return tuple(sorted(ids))


if __name__ == "__main__":
    raise SystemExit(main())
