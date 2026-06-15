#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from TeeBotus.runtime.accounts import AccountStore, TOKEN_HEX_RE  # noqa: E402
from TeeBotus.runtime.proactive_agent import check_proactive_agent_account  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check TeeBotus proactive-agent account state and outbox invariants.")
    parser.add_argument("--instances-dir", default="instances", help="TeeBotus instances directory.")
    parser.add_argument("--instance", action="append", default=[], help="Instance name to check. Can be repeated.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args(argv)

    results = []
    for instance_dir in _instance_dirs(Path(args.instances_dir), args.instance):
        store = AccountStore(instance_dir / "data" / "accounts", instance_dir.name)
        for account_dir in _account_dirs(store.accounts_dir):
            health = check_proactive_agent_account(store, account_dir.name)
            results.append(
                {
                    "instance": instance_dir.name,
                    "account_id": health.account_id,
                    "ok": health.ok,
                    "errors": list(health.errors),
                }
            )
    if args.json:
        print(json.dumps({"ok": all(item["ok"] for item in results), "accounts": results}, indent=2, sort_keys=True))
    else:
        for item in results:
            state = "ok" if item["ok"] else "ERROR"
            print(f"{state} instance={item['instance']} account={item['account_id']}")
            for error in item["errors"]:
                print(f"  - {error}")
    return 0 if all(item["ok"] for item in results) else 1


def _instance_dirs(instances_dir: Path, selected: list[str]) -> list[Path]:
    if selected:
        return [instances_dir / name for name in selected]
    if not instances_dir.exists():
        return []
    return sorted(path for path in instances_dir.iterdir() if path.is_dir() and (path / "data" / "accounts").exists())


def _account_dirs(accounts_dir: Path) -> list[Path]:
    if not accounts_dir.exists():
        return []
    return sorted(path for path in accounts_dir.iterdir() if path.is_dir() and TOKEN_HEX_RE.fullmatch(path.name))


if __name__ == "__main__":
    raise SystemExit(main())
