from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from TeeBotus.llm.hf_pool.config import HFPool, HFPoolConfig
from TeeBotus.llm.hf_pool.errors import HFPoolUnavailable
from TeeBotus.llm.hf_pool.targets import HFPoolTarget
from TeeBotus.llm.profiles import normalize_llm_purpose


@dataclass(frozen=True)
class ScheduledTarget:
    pool: HFPool
    target: HFPoolTarget
    api_key: str = ""


def select_target(
    config: HFPoolConfig,
    *,
    pool_name: str = "default",
    purpose: str = "normal_chat",
    env: Mapping[str, str] | None = None,
) -> ScheduledTarget:
    if config.error:
        raise HFPoolUnavailable(config.error)
    pool = config.pool(pool_name)
    if pool is None:
        raise HFPoolUnavailable(f"pool {pool_name or 'default'} not_configured")
    if not pool.enabled:
        raise HFPoolUnavailable(f"pool {pool.name} disabled")
    purpose_name = normalize_llm_purpose(purpose)
    source = os.environ if env is None else env
    candidates = [target for target in pool.targets if target.enabled and target.supports_purpose(purpose_name)]
    if not candidates:
        raise HFPoolUnavailable(f"pool {pool.name} has no enabled targets for purpose {purpose_name}")
    missing_key = 0
    for target in sorted(candidates, key=lambda item: item.weight, reverse=True):
        api_key = source.get(target.api_key_env, "").strip() if target.api_key_env else ""
        if target.api_key_env and not api_key:
            missing_key += 1
            continue
        return ScheduledTarget(pool=pool, target=target, api_key=api_key)
    if missing_key == len(candidates):
        raise HFPoolUnavailable(f"pool {pool.name} has no target with configured API key")
    raise HFPoolUnavailable(f"pool {pool.name} has no usable targets")
