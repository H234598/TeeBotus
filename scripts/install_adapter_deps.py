#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from urllib.request import urlretrieve


LOCKFILE = Path(__file__).resolve().parents[1] / "adapter-dependencies.lock"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install pinned TeeBotus adapter dependencies.")
    parser.add_argument("--dry-run", action="store_true", help="Print pip commands without executing them.")
    parser.add_argument("--python", default=sys.executable, help="Python executable used to run pip.")
    parser.add_argument("--no-user", action="store_true", help="Do not pass --user to pip.")
    parser.add_argument("--python-only", action="store_true", help="Install only Python adapter dependencies.")
    parser.add_argument("--native-only", action="store_true", help="Install only native Signal adapter dependencies.")
    parser.add_argument("--bin-dir", default=str(Path.home() / ".local" / "bin"), help="User binary directory for signal-cli.")
    parser.add_argument("--opt-dir", default=str(Path.home() / ".local" / "opt"), help="User opt directory for signal-cli.")
    args = parser.parse_args(argv)
    if args.python_only and args.native_only:
        parser.error("--python-only and --native-only cannot be combined")

    pins = read_pins(LOCKFILE)
    if not args.native_only:
        commands = build_python_install_commands(pins, python=args.python, user=not args.no_user)
        for command in commands:
            print(shlex.join(command))
            if not args.dry_run:
                subprocess.run(command, check=True)
    if not args.python_only:
        install_signal_cli(pins["signal-cli"], bin_dir=Path(args.bin_dir), opt_dir=Path(args.opt_dir), dry_run=args.dry_run)
        install_signal_cli_api(pins["signal-cli-api"], dry_run=args.dry_run)
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


def signal_cli_release_url(version: str) -> str:
    return f"https://github.com/AsamK/signal-cli/releases/download/v{version}/signal-cli-{version}.tar.gz"


def install_signal_cli(version: str, *, bin_dir: Path, opt_dir: Path, dry_run: bool = False) -> None:
    archive_name = f"signal-cli-{version}.tar.gz"
    install_dir = opt_dir / f"signal-cli-{version}"
    link_path = bin_dir / "signal-cli"
    url = signal_cli_release_url(version)
    if dry_run:
        print(f"download {url} -> {opt_dir / archive_name}")
        print(f"tar -xzf {opt_dir / archive_name} -C {opt_dir}")
        print(f"ln -sfn {install_dir / 'bin' / 'signal-cli'} {link_path}")
        return
    opt_dir.mkdir(parents=True, exist_ok=True)
    bin_dir.mkdir(parents=True, exist_ok=True)
    archive_path = opt_dir / archive_name
    if not archive_path.exists():
        with tempfile.NamedTemporaryFile(prefix=archive_name + ".", dir=opt_dir, delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            urlretrieve(url, tmp_path)
            tmp_path.replace(archive_path)
        finally:
            tmp_path.unlink(missing_ok=True)
    if not (install_dir / "bin" / "signal-cli").exists():
        with tarfile.open(archive_path, "r:gz") as archive:
            _safe_extract_tar(archive, opt_dir)
    target = install_dir / "bin" / "signal-cli"
    if not target.exists():
        raise SystemExit(f"signal-cli install did not create expected binary: {target}")
    link_path.unlink(missing_ok=True)
    link_path.symlink_to(target)


def install_signal_cli_api(version: str, *, dry_run: bool = False) -> None:
    command = ["cargo", "install", "signal-cli-api", "--version", version, "--locked"]
    print(shlex.join(command))
    if not dry_run:
        subprocess.run(command, check=True)


def _safe_extract_tar(archive: tarfile.TarFile, destination: Path) -> None:
    resolved_destination = destination.resolve()
    for member in archive.getmembers():
        target = (destination / member.name).resolve()
        if target != resolved_destination and resolved_destination not in target.parents:
            raise SystemExit(f"Refusing to extract unsafe tar member: {member.name}")
    archive.extractall(destination)


if __name__ == "__main__":
    raise SystemExit(main())
