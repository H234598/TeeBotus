from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from TeeBotus.runtime.accounts import AccountStore, TOKEN_HEX_RE
from TeeBotus.runtime.proactive_agent import (
    due_proactive_outbox_items,
    proactive_agent_instance_enabled,
    proactive_policy_decision,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run TeeBotus Proactive Agent scheduler checks.")
    parser.add_argument("--instances-dir", default="instances", help="TeeBotus instances directory.")
    parser.add_argument("--instance", action="append", default=[], help="Instance name to check. Can be repeated.")
    parser.add_argument("--dry-run", action="store_true", help="Select due items but do not send or mutate outbox state.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args(argv)
    if not args.dry_run:
        print("Proactive dispatch is not implemented yet. Use --dry-run.", file=sys.stderr)
        return 2
    report = run_proactive_agent_dry_run(instances_dir=Path(args.instances_dir), selected_instances=tuple(args.instance))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_dry_run_report(report)
    return 0 if report["ok"] else 1


StoreFactory = Callable[[Path, str], AccountStore]


def run_proactive_agent_dry_run(
    *,
    instances_dir: Path,
    selected_instances: Iterable[str] = (),
    env: Mapping[str, str] | None = None,
    store_factory: StoreFactory | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
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
                decision = proactive_policy_decision(store, account_id, category=category, now=resolved_now)
                items.append(
                    {
                        "id": str(item.get("id") or ""),
                        "category": category,
                        "intent": str(item.get("intent") or ""),
                        "due_at": str(item.get("due_at") or ""),
                        "policy_allowed": decision.allowed,
                        "policy_reason": decision.reason,
                        "route": decision.route or item.get("route") or {},
                    }
                )
            instance_report["accounts"].append({"account_id": account_id, "due_items": items})
        instances.append(instance_report)
    return {"ok": True, "dry_run": True, "generated_at": resolved_now.isoformat(timespec="seconds"), "instances": instances}


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


def _print_dry_run_report(report: dict[str, Any]) -> None:
    print(f"proactive_dry_run generated_at={report['generated_at']}")
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


if __name__ == "__main__":
    raise SystemExit(main())
