from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from TeeBotus.llm.hf_pool.errors import HFPoolConfigError
from TeeBotus.llm.hf_pool.targets import HFPoolTarget, TargetCapabilities
from TeeBotus.llm.profiles import normalize_llm_purpose

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_HF_POOL_CONFIG_PATH = PROJECT_ROOT / "config" / "hf_pool.yaml"


@dataclass(frozen=True)
class HFPool:
    name: str
    enabled: bool = True
    strategy: str = "purpose_weighted"
    max_retries: int = 1
    timeout_seconds: int = 60
    cooldown_seconds_on_429: int = 900
    cooldown_seconds_on_5xx: int = 120
    cooldown_seconds_on_timeout: int = 120
    targets: tuple[HFPoolTarget, ...] = ()


@dataclass(frozen=True)
class HFPoolConfig:
    pools: dict[str, HFPool]
    path: Path
    exists: bool = True
    error: str = ""

    def pool(self, name: str = "default") -> HFPool | None:
        return self.pools.get(str(name or "default").strip() or "default")


def load_hf_pool_config(path: str | Path = DEFAULT_HF_POOL_CONFIG_PATH, *, strict: bool = False) -> HFPoolConfig:
    config_path = Path(path)
    if not config_path.exists():
        return _config_error(config_path, f"{_display_path(config_path)} missing", strict=strict)
    try:
        payload = _load_mapping(config_path)
        pools = _parse_pools(payload.get("pools"))
    except HFPoolConfigError as exc:
        return _config_error(config_path, str(exc), strict=strict)
    except Exception as exc:  # noqa: BLE001 - nonfatal config surface by default.
        return _config_error(config_path, f"{type(exc).__name__}: {exc}", strict=strict)
    return HFPoolConfig(pools=pools, path=config_path, exists=True)


def _config_error(path: Path, error: str, *, strict: bool) -> HFPoolConfig:
    if strict:
        raise HFPoolConfigError(error)
    return HFPoolConfig(pools={}, path=path, exists=path.exists(), error=error)


def _load_mapping(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - depends on optional PyYAML.
            raise HFPoolConfigError("config is not JSON and PyYAML is not installed") from exc
        payload = yaml.safe_load(text) or {}
    if not isinstance(payload, Mapping):
        raise HFPoolConfigError("hf_pool config root must be a mapping")
    return dict(payload)


def _parse_pools(raw_pools: object) -> dict[str, HFPool]:
    if raw_pools is None:
        return {}
    if not isinstance(raw_pools, Mapping):
        raise HFPoolConfigError("hf_pool config pools must be a mapping")
    pools: dict[str, HFPool] = {}
    for name, raw_pool in raw_pools.items():
        if not isinstance(raw_pool, Mapping):
            continue
        pool_name = str(name or "").strip()
        if not pool_name:
            continue
        pools[pool_name] = HFPool(
            name=pool_name,
            enabled=_parse_bool(raw_pool.get("enabled"), default=True),
            strategy=str(raw_pool.get("strategy") or "purpose_weighted").strip(),
            max_retries=_parse_nonnegative_int(raw_pool.get("max_retries"), default=1),
            timeout_seconds=_parse_int(raw_pool.get("timeout_seconds"), default=60),
            cooldown_seconds_on_429=_parse_int(raw_pool.get("cooldown_seconds_on_429"), default=900),
            cooldown_seconds_on_5xx=_parse_int(raw_pool.get("cooldown_seconds_on_5xx"), default=120),
            cooldown_seconds_on_timeout=_parse_int(raw_pool.get("cooldown_seconds_on_timeout"), default=120),
            targets=tuple(_parse_targets(raw_pool.get("targets"))),
        )
    return pools


def _parse_targets(raw_targets: object) -> list[HFPoolTarget]:
    if raw_targets is None:
        return []
    if not isinstance(raw_targets, list):
        raise HFPoolConfigError("hf_pool targets must be a list")
    targets: list[HFPoolTarget] = []
    for item in raw_targets:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or "").strip()
        model = str(item.get("model") or "").strip()
        if not name or not model:
            continue
        required = dict(item.get("required") or {}) if isinstance(item.get("required"), Mapping) else {}
        targets.append(
            HFPoolTarget(
                name=name,
                kind=str(item.get("kind") or "hf_router_chat").strip(),
                base_url=str(item.get("base_url") or "https://router.huggingface.co/v1").strip(),
                api_key_env=str(item.get("api_key_env") or "").strip(),
                model=model,
                routed_model=str(item.get("routed_model") or "").strip(),
                weight=_parse_int(item.get("weight"), default=1),
                purposes=tuple(normalize_llm_purpose(value) for value in _parse_string_list(item.get("purposes"))),
                enabled=_parse_bool(item.get("enabled"), default=True),
                required=required,
                capabilities=TargetCapabilities(
                    supports_tools=_parse_bool(required.get("supports_tools"), default=False),
                    supports_structured_output=_parse_bool(required.get("supports_structured_output"), default=False),
                    context_length=_parse_optional_int(required.get("context_length")),
                ),
            )
        )
    return targets


def _parse_string_list(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(item or "").strip() for item in value if str(item or "").strip())
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    return ()


def _parse_bool(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().casefold()
    if text in {"1", "true", "yes", "ja", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "nein", "off", "disabled"}:
        return False
    return default


def _parse_int(value: object, *, default: int) -> int:
    parsed = _parse_optional_int(value)
    return parsed if parsed is not None else default


def _parse_nonnegative_int(value: object, *, default: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _parse_optional_int(value: object) -> int | None:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)
