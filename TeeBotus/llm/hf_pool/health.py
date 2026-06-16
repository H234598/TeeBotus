from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from TeeBotus.llm.hf_pool.config import DEFAULT_HF_POOL_CONFIG_PATH, HFPoolConfig, load_hf_pool_config


@dataclass(frozen=True)
class HFPoolTargetHealth:
    pool: str
    name: str
    status: str
    model: str = ""
    api_key_env: str = ""
    error: str = ""


@dataclass(frozen=True)
class HFPoolHealth:
    pool: str
    status: str
    targets: tuple[HFPoolTargetHealth, ...] = ()
    error: str = ""

    @property
    def healthy_count(self) -> int:
        return sum(1 for target in self.targets if target.status in {"configured", "healthy"})


def check_hf_pool(
    *,
    pool_name: str = "default",
    config_path: str | Path = DEFAULT_HF_POOL_CONFIG_PATH,
    env: Mapping[str, str] | None = None,
) -> HFPoolHealth:
    config = load_hf_pool_config(config_path)
    if config.error:
        return HFPoolHealth(pool=pool_name or "default", status="not_configured" if not config.exists else "broken", error=config.error)
    pool = config.pool(pool_name)
    if pool is None:
        return HFPoolHealth(pool=pool_name or "default", status="not_configured", error=f"pool {pool_name or 'default'} missing")
    if not pool.enabled:
        return HFPoolHealth(pool=pool.name, status="disabled")
    source = os.environ if env is None else env
    targets: list[HFPoolTargetHealth] = []
    for target in pool.targets:
        if not target.enabled:
            status = "disabled"
            error = ""
        elif target.api_key_env and not source.get(target.api_key_env, "").strip():
            status = "missing_key"
            error = f"env={target.api_key_env}"
        else:
            status = "configured"
            error = ""
        targets.append(
            HFPoolTargetHealth(
                pool=pool.name,
                name=target.name,
                status=status,
                model=target.model,
                api_key_env=target.api_key_env,
                error=error,
            )
        )
    if not targets:
        return HFPoolHealth(pool=pool.name, status="unavailable", targets=(), error="targets=0")
    if not any(target.status == "configured" for target in targets):
        return HFPoolHealth(pool=pool.name, status="unavailable", targets=tuple(targets), error="no_configured_targets")
    return HFPoolHealth(pool=pool.name, status="configured", targets=tuple(targets))


def format_hf_pool_status_lines(health: HFPoolHealth) -> list[str]:
    lines = [f"hf_pool={health.pool} status={health.status}"]
    if health.targets:
        lines[0] += f" targets={len(health.targets)} healthy={health.healthy_count}"
    if health.error:
        lines[0] += f" error={_status_text(health.error)}"
    for target in health.targets:
        line = f"hf_pool={health.pool} target={target.name} status={target.status}"
        if target.model:
            line += f" model={_status_text(target.model)}"
        if target.api_key_env:
            line += f" env={_status_text(target.api_key_env)}"
        if target.error and not target.error.startswith("env="):
            line += f" error={_status_text(target.error)}"
        lines.append(line)
    return lines


def _status_text(value: object) -> str:
    return str(value or "").replace("\n", " ").replace("\r", " ").strip()
