#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path


LOCKFILE = Path(__file__).resolve().parents[1] / "adapter-dependencies.lock"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install pinned TeeBotus adapter Python dependencies.")
    parser.add_argument("--dry-run", action="store_true", help="Print pip commands without executing them.")
    parser.add_argument("--python", default=sys.executable, help="Python executable used to run pip.")
    parser.add_argument("--no-user", action="store_true", help="Do not pass --user to pip.")
    args = parser.parse_args(argv)

    pins = read_pins(LOCKFILE)
    commands = build_python_install_commands(pins, python=args.python, user=not args.no_user)
    for command in commands:
        print(shlex.join(command))
        if not args.dry_run:
            subprocess.run(command, check=True)
    if not args.dry_run:
        subprocess.run([args.python, str(Path(__file__).with_name("check_adapter_deps.py"))], check=True)
    return 0


def read_pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, sep, version = stripped.partition("==")
        if not sep:
            raise SystemExit(f"Invalid lock line: {line}")
        pins[name.strip()] = version.strip()
    return pins


def build_python_install_commands(pins: dict[str, str], *, python: str, user: bool = True) -> list[list[str]]:
    pip_base = [python, "-m", "pip", "install", "--upgrade"]
    if user:
        pip_base.append("--user")
    return [
        [
            *pip_base,
            f"signalbot=={pins['signalbot']}",
            f"matrix-nio=={pins['matrix-nio']}",
            f"blurhash-python=={pins['blurhash-python']}",
            f"h11=={pins['h11']}",
            "marko==2.*",
            "python-magic>=0.4.27",
            "aiofiles>=23.1.0",
        ],
        [
            *pip_base,
            "--no-deps",
            f"nio-bot=={pins['nio-bot']}",
        ],
    ]


if __name__ == "__main__":
    raise SystemExit(main())
