from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
from typing import Iterable, Mapping

from TeeBotus.llm.hf_pool.config import HFPool, HFPoolConfig
from TeeBotus.llm.hf_pool.errors import HFPoolUnavailable
from TeeBotus.llm.hf_pool.state import HFPoolRuntimeState, hf_pool_state_lookup
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
    state: HFPoolRuntimeState | None = None,
    now: datetime | None = None,
    exclude_targets: Iterable[str] = (),
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
    excluded = {str(target or "").strip() for target in exclude_targets if str(target or "").strip()}
    candidates = [target for target in pool.targets if target.enabled and target.supports_purpose(purpose_name) and target.name not in excluded]
    if not candidates:
        raise HFPoolUnavailable(f"pool {pool.name} has no enabled targets for purpose {purpose_name}")
    missing_key = 0
    cooldown = 0
    for target in _ordered_weighted_candidates(pool, candidates, state):
        api_key = source.get(target.api_key_env, "").strip() if target.api_key_env else ""
        if target.api_key_env and not api_key:
            missing_key += 1
            continue
        if _target_in_cooldown(pool, target, state, now=now):
            cooldown += 1
            continue
        return ScheduledTarget(pool=pool, target=target, api_key=api_key)
    if missing_key == len(candidates):
        raise HFPoolUnavailable(f"pool {pool.name} has no target with configured API key")
    if cooldown and missing_key + cooldown == len(candidates):
        raise HFPoolUnavailable(f"pool {pool.name} has all configured targets in cooldown")
    raise HFPoolUnavailable(f"pool {pool.name} has no usable targets")


def _ordered_weighted_candidates(pool: HFPool, candidates: list[HFPoolTarget], state: HFPoolRuntimeState | None) -> list[HFPoolTarget]:
    indexed = list(enumerate(candidates))
    indexed.sort(key=lambda item: _weighted_candidate_key(pool, item[0], item[1], state))
    return [target for _index, target in indexed]


def _weighted_candidate_key(pool: HFPool, index: int, target: HFPoolTarget, state: HFPoolRuntimeState | None) -> tuple[Fraction, int, int]:
    weight = max(1, _int_value(target.weight, default=1))
    attempts = _target_attempt_count(pool, target.name, state)
    return Fraction(attempts + 1, weight), -weight, index


def _target_attempt_count(pool: HFPool, target_name: str, state: HFPoolRuntimeState | None) -> int:
    if state is None:
        return 0
    successes = hf_pool_state_lookup(state.successes, pool.name, target_name, 0)
    failures = hf_pool_state_lookup(state.failures, pool.name, target_name, 0)
    return max(0, _int_value(successes, default=0)) + max(0, _int_value(failures, default=0))


def _target_in_cooldown(pool: HFPool, target: HFPoolTarget, state: HFPoolRuntimeState | None, *, now: datetime | None = None) -> bool:
    if state is None:
        return False
    cooldown_until = str(hf_pool_state_lookup(state.cooldowns, pool.name, target.name, "") or "").strip()
    if not cooldown_until:
        return False
    try:
        parsed = datetime.fromisoformat(cooldown_until)
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return parsed > current


def _int_value(value: object, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
