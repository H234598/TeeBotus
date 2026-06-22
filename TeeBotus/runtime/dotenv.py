from __future__ import annotations

import os
from collections.abc import MutableMapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DotenvLoadResult:
    path: Path
    exists: bool
    loaded_keys: tuple[str, ...] = ()
    preserved_keys: tuple[str, ...] = ()


def load_dotenv_defaults(path: str | Path, *, environ: MutableMapping[str, str] | None = None) -> DotenvLoadResult:
    """Load dotenv values as defaults without overriding the real process env."""

    env = os.environ if environ is None else environ
    dotenv_path = Path(path).expanduser()
    if not dotenv_path.exists():
        return DotenvLoadResult(path=dotenv_path, exists=False)
    values = _read_dotenv_values(dotenv_path)
    loaded: list[str] = []
    preserved: list[str] = []
    for key, value in values.items():
        if key in env:
            preserved.append(key)
            continue
        env[key] = value
        loaded.append(key)
    return DotenvLoadResult(
        path=dotenv_path,
        exists=True,
        loaded_keys=tuple(sorted(loaded)),
        preserved_keys=tuple(sorted(preserved)),
    )


def load_project_dotenv_for_instances(
    instances_dir: str | Path,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> DotenvLoadResult:
    return load_dotenv_defaults(project_root_for_instances_dir(instances_dir) / ".env", environ=environ)


def project_root_for_instances_dir(instances_dir: str | Path) -> Path:
    path = Path(instances_dir).expanduser()
    return _project_root_candidates(path)[0]


def _read_dotenv_values(path: Path) -> dict[str, str]:
    try:
        from dotenv import dotenv_values
    except Exception:  # noqa: BLE001
        return _read_dotenv_values_fallback(path)
    parsed = dotenv_values(path)
    values: dict[str, str] = {}
    for key, value in parsed.items():
        normalized_key = str(key or "").strip()
        if not normalized_key or value is None:
            continue
        values[normalized_key] = str(value)
    return values


def _read_dotenv_values_fallback(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = _clean_dotenv_value(value.strip())
    return values


def _clean_dotenv_value(value: str) -> str:
    cleaned = _strip_unquoted_inline_comment(str(value or "").strip()).strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        return cleaned[1:-1]
    return cleaned


def _project_root_candidates(path: Path) -> tuple[Path, ...]:
    candidates: list[Path] = []
    seen: set[str] = set()

    def add(candidate: Path) -> None:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            candidates.append(candidate)

    for candidate in (path, *path.parents):
        if candidate.name == "instances":
            add(candidate.parent if str(candidate.parent) else Path("."))
    if _looks_like_project_root(path):
        add(path)
    add(path.parent if str(path.parent) else Path("."))
    for candidate in (path, *path.parents):
        if _looks_like_project_root(candidate):
            add(candidate)
    return tuple(candidates) or (Path("."),)


def _looks_like_project_root(path: Path) -> bool:
    return (path / ".env").exists() or (path / "pyproject.toml").exists() or (path / ".git").exists()


def _strip_unquoted_inline_comment(value: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_double:
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if char == "#" and not in_single and not in_double and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
    return value
