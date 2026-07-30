from __future__ import annotations

from pathlib import Path


PATH = Path("scripts/check_plan2_acceptance.py")
OLD = '    "tests/test_history_dispatcher_provider_v2.py",\n'
NEW = '    "tests/test_history_dispatcher_provider_v2*.py",\n'


def main() -> None:
    source = PATH.read_text(encoding="utf-8")
    count = source.count(OLD)
    if count != 1:
        raise SystemExit(f"expected one provider-v2 inventory entry, found {count}")
    PATH.write_text(source.replace(OLD, NEW, 1), encoding="utf-8")


if __name__ == "__main__":
    main()
