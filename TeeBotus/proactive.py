from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from TeeBotus.runtime.accounts import AccountStore, TOKEN_HEX_RE
from TeeBotus.runtime.message_tracking import MessageTracker
from TeeBotus.runtime.proactive_agent import (
    ProactiveSender,
    dispatch_due_proactive_outbox_items,
    due_proactive_outbox_items,
    proactive_agent_instance_enabled,
    proactive_policy_decision,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run TeeBotus Proactive Agent scheduler checks.")
    parser.add_argument("--instances-dir", default="instances", help="TeeBotus instances directory.")
    parser.add_argument("--instance", action="append", default=[], help="Instance name to check. Can be repeated.")
    parser.add_argument("--dry-run", action="store_true", help="Select due items but do not send or mutate outbox state.")
    parser.add_argument("--dispatch", action="store_true", help="Dispatch due items using explicitly configured in-process senders.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args(argv)
    if args.dry_run == args.dispatch:
        print("Use exactly one of --dry-run or --dispatch.", file=sys.stderr)
        return 2
    if args.dispatch:
        print("CLI dispatch requires a runtime-provided sender registry; use --dry-run here.", file=sys.stderr)
        return 2
    report = run_proactive_agent_dry_run(instances_dir=Path(args.instances_dir), selected_instances=tuple(args.instance))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_dry_run_report(report)
    return 0 if report["ok"] else 1


StoreFactory = Callable[[Path, str], AccountStore]
SenderFactory = Callable[[str, AccountStore], Mapping[str, ProactiveSender]]
MessageTrackerFactory = Callable[[Path, str], MessageTracker | None]


def run_proactive_agent_dry_run(
    *,
    instances_dir: Path,
    selected_instances: Iterable[str] = (),
    env: Mapping[str, str] | None = None,
    store_factory: StoreFactory | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    return asyncio.run(
        run_proactive_agent_cycle(
            instances_dir=instances_dir,
            selected_instances=selected_instances,
            env=env,
            store_factory=store_factory,
            now=now,
            dispatch=False,
        )
    )


async def run_proactive_agent_cycle(
    *,
    instances_dir: Path,
    selected_instances: Iterable[str] = (),
    env: Mapping[str, str] | None = None,
    store_factory: StoreFactory | None = None,
    now: datetime | None = None,
    dispatch: bool = False,
    sender_factory: SenderFactory | None = None,
    message_tracker_factory: MessageTrackerFactory | None = None,
) -> dict[str, Any]:
    if dispatch and sender_factory is None:
        raise ValueError("sender_factory is required when dispatch=True")
    resolved_now = now or datetime.now(timezone.utc)
    resolved_store_factory = store_factory or AccountStore
    instances: list[dict[str, Any]] = []
    for instance_dir in _instance_dirs(instances_dir, tuple(selected_instances)):
        instance_report: dict[str, Any] = {
            "instance": instance_dir.name,
            "enabled": proactive_agent_instance_enabled(instance_dir.name, env=env),
            "accounts": [],
        }
        if not instance_report["enabled"]:
            instance_report["skipped_reason"] = "instance_not_enabled"
            instances.append(instance_report)
            continue
        store = resolved_store_factory(instance_dir / "data" / "accounts", instance_dir.name)
        for account_dir in _account_dirs(store.accounts_dir):
            account_id = account_dir.name
            items: list[dict[str, Any]] = []
            for item in due_proactive_outbox_items(store, account_id, now=resolved_now):
                category = str(item.get("category") or "")
                item_id = str(item.get("id") or "")
                decision = proactive_policy_decision(store, account_id, category=category, now=resolved_now, exclude_item_id=item_id)
                items.append(
                    {
                        "id": item_id,
                        "category": category,
                        "intent": str(item.get("intent") or ""),
                        "due_at": str(item.get("due_at") or ""),
                        "policy_allowed": decision.allowed,
                        "policy_reason": decision.reason,
                        "route": decision.route or item.get("route") or {},
                    }
                )
            instance_report["accounts"].append({"account_id": account_id, "due_items": items})
            if dispatch:
                senders = dict((sender_factory or _missing_sender_factory)(instance_dir.name, store))
                tracker = _message_tracker_for_instance(instance_dir, instance_dir.name, message_tracker_factory)
                results = await dispatch_due_proactive_outbox_items(
                    store,
                    account_id,
                    senders=senders,
                    now=resolved_now,
                    message_tracker=tracker,
                    instance_name=instance_dir.name,
                )
                instance_report["accounts"][-1]["dispatch_results"] = [
                    {
                        "account_id": result.account_id,
                        "item_id": result.item_id,
                        "status": result.status,
                        "reason": result.reason,
                        "channel": result.channel,
                        "message_ref": result.message_ref,
                    }
                    for result in results
                ]
        instances.append(instance_report)
    return {
        "ok": _cycle_ok(instances),
        "dry_run": not dispatch,
        "dispatch": dispatch,
        "generated_at": resolved_now.isoformat(timespec="seconds"),
        "instances": instances,
    }


def _instance_dirs(instances_dir: Path, selected: tuple[str, ...]) -> list[Path]:
    if selected:
        return [instances_dir / name for name in selected]
    if not instances_dir.exists():
        return []
    return sorted(path for path in instances_dir.iterdir() if path.is_dir() and (path / "data" / "accounts").exists())


def _account_dirs(accounts_dir: Path) -> list[Path]:
    if not accounts_dir.exists():
        return []
    return sorted(path for path in accounts_dir.iterdir() if path.is_dir() and TOKEN_HEX_RE.fullmatch(path.name))


def _missing_sender_factory(_instance_name: str, _store: AccountStore) -> Mapping[str, ProactiveSender]:
    return {}


def _message_tracker_for_instance(instance_dir: Path, instance_name: str, factory: MessageTrackerFactory | None) -> MessageTracker | None:
    if factory is not None:
        return factory(instance_dir, instance_name)
    return MessageTracker(instance_dir / "data" / "runtime" / "Sent_Message_Refs.json")


def _cycle_ok(instances: list[dict[str, Any]]) -> bool:
    for instance in instances:
        for account in instance.get("accounts", []):
            for result in account.get("dispatch_results", []):
                if result.get("status") == "failed":
                    return False
    return True


def _print_dry_run_report(report: dict[str, Any]) -> None:
    mode = "dispatch" if report.get("dispatch") else "dry_run"
    print(f"proactive_{mode} generated_at={report['generated_at']}")
    for instance in report["instances"]:
        enabled = "yes" if instance.get("enabled") else "no"
        print(f"instance={instance['instance']} enabled={enabled}")
        if instance.get("skipped_reason"):
            print(f"  skipped={instance['skipped_reason']}")
            continue
        for account in instance.get("accounts", []):
            due_items = account.get("due_items", [])
            print(f"  account={account['account_id']} due_items={len(due_items)}")
            for item in due_items:
                policy = "allowed" if item["policy_allowed"] else f"blocked:{item['policy_reason']}"
                print(f"    item={item['id']} category={item['category']} intent={item['intent']} policy={policy}")
            for result in account.get("dispatch_results", []):
                print(
                    f"    dispatch item={result['item_id']} status={result['status']} "
                    f"reason={result['reason']} channel={result['channel']}"
                )


if __name__ == "__main__":
    raise SystemExit(main())
