#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.metadata
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"
PLAN2_OPTIONAL_EXTRAS = ("llm", "rag", "agents", "tools")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inventory optional Plan2 extras without installing or contacting services.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument(
        "--require-installed",
        action="store_true",
        help="Fail when any Plan2 optional dependency is not installed.",
    )
    args = parser.parse_args(argv)

    report = build_optional_extras_report(require_installed=args.require_installed)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_text_report(report)
    return 0 if report["ok"] else 1


def build_optional_extras_report(*, require_installed: bool = False, pyproject_path: Path = PYPROJECT) -> dict[str, Any]:
    payload = _read_pyproject(pyproject_path)
    optional = payload.get("project", {}).get("optional-dependencies", {})
    errors: list[str] = []
    extras: dict[str, Any] = {}
    for extra in PLAN2_OPTIONAL_EXTRAS:
        raw_deps = optional.get(extra)
        if not isinstance(raw_deps, list) or not raw_deps:
            errors.append(f"missing optional extra: {extra}")
            extras[extra] = {"declared": [], "installed": [], "missing": []}
            continue
        installed: list[dict[str, str]] = []
        missing: list[str] = []
        for requirement in raw_deps:
            package = _distribution_name(str(requirement))
            if not package:
                errors.append(f"could not parse requirement in {extra}: {requirement!r}")
                continue
            try:
                version = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                missing.append(package)
            else:
                installed.append({"name": package, "version": version})
        if require_installed and missing:
            errors.append(f"{extra} missing installed packages: {', '.join(missing)}")
        extras[extra] = {
            "declared": list(raw_deps),
            "installed": installed,
            "missing": missing,
            "complete": not missing,
        }
    return {
        "schema_version": 1,
        "ok": not errors,
        "require_installed": bool(require_installed),
        "pyproject": str(pyproject_path),
        "extras": extras,
        "errors": errors,
    }


def _read_pyproject(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _distribution_name(requirement: str) -> str:
    head = requirement.split(";", 1)[0].strip()
    match = re.match(r"^([A-Za-z0-9_.-]+)", head)
    return match.group(1).replace("_", "-") if match else ""


def _print_text_report(report: dict[str, Any]) -> None:
    print("Plan2 optional extras inventory")
    print(f"pyproject={report['pyproject']}")
    print(f"require_installed={str(report['require_installed']).lower()}")
    for extra, info in report["extras"].items():
        declared = ", ".join(info["declared"]) or "-"
        installed = ", ".join(f"{item['name']}=={item['version']}" for item in info["installed"]) or "-"
        missing = ", ".join(info["missing"]) or "-"
        status = "complete" if info["complete"] else "partial"
        print(f"{extra}: status={status} declared=[{declared}] installed=[{installed}] missing=[{missing}]")
    for error in report["errors"]:
        print(f"ERROR {error}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
