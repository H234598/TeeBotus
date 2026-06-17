from __future__ import annotations

import importlib
import json
import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("Usage: python -m TeeBotus.admin {accounts|memory-recovery} ...", file=sys.stderr)
        return 2
    if args[0] == "memory-recovery":
        try:
            module = importlib.import_module("TeeBotus.admin.account_memory_recovery")
        except ModuleNotFoundError as exc:
            return _dependency_error(args[1:], exc)
        return module.main(args[1:])
    try:
        module = importlib.import_module("TeeBotus.admin.accounts_report")
    except ModuleNotFoundError as exc:
        return _dependency_error(args, exc)
    return module.main(args)


def _dependency_error(args: list[str], exc: ModuleNotFoundError) -> int:
    package = exc.name or "unknown"
    message = f"Missing Python dependency for TeeBotus admin command: {package}"
    if _requested_json(args):
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": message,
                    "missing_dependency": package,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    else:
        print(message, file=sys.stderr)
    return 2


def _requested_json(args: list[str]) -> bool:
    for index, arg in enumerate(args):
        if arg == "--format" and index + 1 < len(args):
            return args[index + 1] == "json"
        if arg.startswith("--format="):
            return arg.split("=", 1)[1] == "json"
    return False


if __name__ == "__main__":
    raise SystemExit(main())
