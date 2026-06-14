#!/usr/bin/env python3
from __future__ import annotations

import importlib.metadata
import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path


LOCKFILE = Path(__file__).resolve().parents[1] / "adapter-dependencies.lock"
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    pins = _read_pins(LOCKFILE)
    checks = [
        _check_python_package("signalbot", pins["signalbot"]),
        _check_python_package("nio-bot", pins["nio-bot"]),
        _check_python_package("matrix-nio", pins["matrix-nio"]),
        _check_python_package("blurhash-python", pins["blurhash-python"]),
        _check_executable_version("signal-cli", pins["signal-cli"], ["--version"]),
        _check_cargo_binary("signal-cli-api", pins["signal-cli-api"]),
    ]
    for ok, message in checks:
        print(("OK " if ok else "FAIL ") + message)
    return 0 if all(ok for ok, _message in checks) else 1


def _read_pins(path: Path) -> dict[str, str]:
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


def _check_python_package(name: str, expected: str) -> tuple[bool, str]:
    try:
        installed = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return False, f"{name} missing, expected {expected}"
    import_name = {"nio-bot": "niobot", "matrix-nio": "nio", "blurhash-python": "blurhash"}.get(
        name, name.replace("-", "_")
    )
    try:
        module = importlib.import_module(import_name)
    except Exception as exc:
        module = None
        import_detail = f" import_error={type(exc).__name__}: {exc}"
    else:
        import_detail = f" import={getattr(module, '__file__', '<unknown>')}"
    ok = installed == expected and module is not None
    return ok, f"{name} installed={installed} expected={expected}{import_detail}"

def _check_executable_version(binary: str, expected: str, args: list[str]) -> tuple[bool, str]:
    path = _which(binary)
    if path is None:
        return False, f"{binary} missing from PATH, expected {expected}"
    try:
        result = subprocess.run(
            [path, *args],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"{binary} could not be executed: {exc}"
    output = " ".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    ok = result.returncode == 0 and expected in output
    return ok, f"{binary} path={path} version_output={output or '<empty>'} expected={expected}"


def _check_cargo_binary(binary: str, expected: str) -> tuple[bool, str]:
    path = _which(binary)
    if path is None:
        return False, f"{binary} missing from PATH, expected {expected}"
    cargo = _which("cargo")
    if cargo is None:
        return False, f"{binary} path={path}, but cargo is missing; cannot verify expected {expected}"
    try:
        result = subprocess.run(
            [cargo, "install", "--list"],
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"{binary} could not be verified through cargo: {exc}"
    expected_line = f"{binary} v{expected}:"
    ok = result.returncode == 0 and expected_line in result.stdout
    return ok, f"{binary} path={path} cargo_pin={'found' if ok else 'missing'} expected={expected}"


def _which(binary: str) -> str | None:
    path = shutil.which(binary)
    if path is not None:
        return path
    for directory in (Path.home() / ".local" / "bin", Path.home() / ".cargo" / "bin"):
        candidate = directory / binary
        if os.access(candidate, os.X_OK):
            return str(candidate)
    return None


if __name__ == "__main__":
    raise SystemExit(main())
