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

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement


REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"
PLAN2_OPTIONAL_EXTRAS = ("llm", "rag", "agents", "tools")
BAD_LITELLM_VERSIONS = frozenset({"1.82.7", "1.82.8"})
MIN_SAFE_LITELLM_VERSION = "1.84.0"
PY314_COMPATIBLE_LITELLM_VERSION = "1.83.7"


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
        version_mismatches: list[dict[str, str]] = []
        skipped: list[str] = []
        active_declared: list[str] = []
        for requirement in raw_deps:
            if not _requirement_applies(str(requirement)):
                skipped.append(str(requirement))
                continue
            active_declared.append(str(requirement))
            package = _distribution_name(str(requirement))
            if not package:
                errors.append(f"could not parse requirement in {extra}: {requirement!r}")
                continue
            expected_version = _exact_pinned_version(str(requirement))
            if not expected_version:
                errors.append(f"{extra} {package} must be exactly pinned for Plan2")
            if package == "litellm" and expected_version in BAD_LITELLM_VERSIONS:
                errors.append(f"llm litellm pin {expected_version} is blocked due to known compromised PyPI releases")
            min_safe_litellm = _min_safe_litellm_version()
            if package == "litellm" and expected_version and _version_tuple(expected_version) < _version_tuple(min_safe_litellm):
                errors.append(f"llm litellm pin {expected_version} is below security minimum {min_safe_litellm}")
            try:
                version = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                missing.append(package)
            else:
                installed.append({"name": package, "version": version})
                if expected_version and version != expected_version:
                    version_mismatches.append({"name": package, "expected": expected_version, "installed": version})
                if package == "litellm" and version in BAD_LITELLM_VERSIONS:
                    errors.append(f"llm litellm installed {version} is blocked due to known compromised PyPI releases")
                if package == "litellm" and _version_tuple(version) < _version_tuple(min_safe_litellm):
                    errors.append(f"llm litellm installed {version} is below security minimum {min_safe_litellm}")
        if require_installed and missing:
            errors.append(f"{extra} missing installed packages: {', '.join(missing)}")
        if require_installed and version_mismatches:
            detail = ", ".join(f"{item['name']} expected {item['expected']} found {item['installed']}" for item in version_mismatches)
            errors.append(f"{extra} version mismatches: {detail}")
        extras[extra] = {
            "declared": list(raw_deps),
            "active_declared": active_declared,
            "skipped": skipped,
            "installed": installed,
            "missing": missing,
            "version_mismatches": version_mismatches,
            "complete": not missing and not version_mismatches,
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
    try:
        return Requirement(requirement).name.replace("_", "-")
    except InvalidRequirement:
        head = requirement.split(";", 1)[0].strip()
        match = re.match(r"^([A-Za-z0-9_.-]+)", head)
        return match.group(1).replace("_", "-") if match else ""


def _exact_pinned_version(requirement: str) -> str:
    try:
        parsed = Requirement(requirement)
    except InvalidRequirement:
        head = requirement.split(";", 1)[0].strip()
        match = re.match(r"^[A-Za-z0-9_.-]+\s*==\s*([A-Za-z0-9_.!+-]+)\s*$", head)
        return match.group(1) if match else ""
    specifiers = list(parsed.specifier)
    if len(specifiers) != 1:
        return ""
    specifier = specifiers[0]
    return specifier.version if specifier.operator == "==" else ""


def _requirement_applies(requirement: str) -> bool:
    try:
        parsed = Requirement(requirement)
    except InvalidRequirement:
        return True
    if parsed.marker is None:
        return True
    return bool(parsed.marker.evaluate(environment=default_environment()))


def _version_tuple(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in str(value or "").replace("-", ".").split("."):
        if not chunk.isdigit():
            break
        parts.append(int(chunk))
    return tuple(parts or [0])


def _min_safe_litellm_version() -> str:
    if sys.version_info >= (3, 14):
        return PY314_COMPATIBLE_LITELLM_VERSION
    return MIN_SAFE_LITELLM_VERSION


def _print_text_report(report: dict[str, Any]) -> None:
    print("Plan2 optional extras inventory")
    print(f"pyproject={report['pyproject']}")
    print(f"require_installed={str(report['require_installed']).lower()}")
    for extra, info in report["extras"].items():
        declared = ", ".join(info["declared"]) or "-"
        active = ", ".join(info.get("active_declared", [])) or "-"
        skipped = ", ".join(info.get("skipped", [])) or "-"
        installed = ", ".join(f"{item['name']}=={item['version']}" for item in info["installed"]) or "-"
        missing = ", ".join(info["missing"]) or "-"
        mismatches = ", ".join(f"{item['name']} expected {item['expected']} found {item['installed']}" for item in info.get("version_mismatches", [])) or "-"
        status = "complete" if info["complete"] else "partial"
        print(
            f"{extra}: status={status} declared=[{declared}] active=[{active}] skipped=[{skipped}] "
            f"installed=[{installed}] missing=[{missing}] mismatches=[{mismatches}]"
        )
    for error in report["errors"]:
        print(f"ERROR {error}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
