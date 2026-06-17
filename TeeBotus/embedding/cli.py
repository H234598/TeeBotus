from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from TeeBotus.embedding.rebuild import rebuild_qdrant_memory_indexes


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "memory-rebuild":
        results = rebuild_qdrant_memory_indexes(
            instances_dir=args.instances_dir,
            instance_names=args.instance,
            account_ids=args.account_id,
            qdrant_url=args.qdrant_url or None,
            dry_run=args.dry_run,
        )
        if args.json:
            print(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2))
        else:
            for result in results:
                print(_format_memory_rebuild_result(result))
        return 1 if any(result.status == "error" for result in results) else 0
    parser.print_help()
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TeeBotus embedding and Qdrant cache maintenance.")
    parser.add_argument("--instances-dir", default="instances")
    parser.add_argument("--instance", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    subparsers = parser.add_subparsers(dest="command")

    memory = subparsers.add_parser("memory-rebuild", help="Rebuild Qdrant Usermemory cache from AccountStore.")
    memory.add_argument("--account-id", action="append", default=[], help="Limit rebuild to one or more account IDs.")
    memory.add_argument("--qdrant-url", default="", help="Override Qdrant URL. Defaults to TEEBOTUS_QDRANT_URL or localhost.")
    memory.add_argument("--dry-run", action="store_true", help="Count AccountStore entries without writing Qdrant.")
    memory.set_defaults(command="memory-rebuild")
    return parser


def _format_memory_rebuild_result(result: object) -> str:
    instance = str(getattr(result, "instance_name", "") or "default")
    account_id = str(getattr(result, "account_id", "") or "<all>")
    status = str(getattr(result, "status", "") or "unknown")
    point_count = int(getattr(result, "point_count", 0) or 0)
    error = str(getattr(result, "error", "") or "")
    suffix = f" error={error}" if error else ""
    return f"{instance}/{account_id}: status={status} points={point_count}{suffix}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
