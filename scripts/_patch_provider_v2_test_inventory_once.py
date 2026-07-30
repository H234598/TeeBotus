from __future__ import annotations

from pathlib import Path


PLAN2 = Path("scripts/check_plan2_acceptance.py")
MAINTENANCE_TEST = Path("tests/test_runtime_maintenance.py")


def replace_once(source: str, old: str, new: str, *, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    plan = PLAN2.read_text(encoding="utf-8")
    plan = replace_once(
        plan,
        '    "tests/test_history_dispatcher_bridge.py",\n'
        '    "tests/test_history_dispatcher_migration.py",\n',
        '    "tests/test_history_dispatcher_bridge.py",\n'
        '    "tests/test_history_dispatcher_provider_v2.py",\n'
        '    "tests/test_history_dispatcher_migration.py",\n',
        label="Plan2 provider test inventory",
    )
    PLAN2.write_text(plan, encoding="utf-8")

    test = MAINTENANCE_TEST.read_text(encoding="utf-8")
    test = replace_once(
        test,
        '        if fd in broken_fds and mode == "rb":\n'
        '            raise RuntimeError("archive source fdopen failed")\n',
        '        if fd in broken_fds and mode == "rb":\n'
        '            broken_fds.remove(fd)\n'
        '            raise RuntimeError("archive source fdopen failed")\n',
        label="single-use broken archive fd",
    )
    MAINTENANCE_TEST.write_text(test, encoding="utf-8")


if __name__ == "__main__":
    main()
