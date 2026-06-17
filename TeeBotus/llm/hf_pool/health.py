from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.hf_pool.config import DEFAULT_HF_POOL_CONFIG_PATH, HFPool, HFPoolConfig, load_hf_pool_config
from TeeBotus.llm.hf_pool.errors import HFPoolRateLimited, HFPoolTargetUnavailable, HFPoolUnavailable
from TeeBotus.llm.hf_pool.executor import HFPoolOpener, OpenAICompatibleHFPoolExecutor
from TeeBotus.llm.hf_pool.metrics import HFPoolUsageEvent
from TeeBotus.llm.hf_pool.redaction import redact_hf_secrets
from TeeBotus.llm.hf_pool.scheduler import ScheduledTarget
from TeeBotus.llm.hf_pool.state import HFPoolRuntimeStateStore
from TeeBotus.llm.hf_pool.targets import HFPoolTarget


@dataclass(frozen=True)
class HFPoolTargetHealth:
    pool: str
    name: str
    status: str
    model: str = ""
    api_key_env: str = ""
    error: str = ""
    latency_ms: int | None = None


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
    live: bool = False,
    opener: HFPoolOpener | None = None,
    state_store: HFPoolRuntimeStateStore | None = None,
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
            latency_ms = None
        elif target.api_key_env and not source.get(target.api_key_env, "").strip():
            status = "missing_key"
            error = f"env={target.api_key_env}"
            latency_ms = None
        elif live:
            status, error, latency_ms = _live_target_status(
                pool=pool,
                target=target,
                api_key=source.get(target.api_key_env, "").strip() if target.api_key_env else "",
                opener=opener,
                state_store=state_store,
            )
        else:
            status = "configured"
            error = ""
            latency_ms = None
        targets.append(
            HFPoolTargetHealth(
                pool=pool.name,
                name=target.name,
                status=status,
                model=target.model,
                api_key_env=target.api_key_env,
                error=error,
                latency_ms=latency_ms,
            )
        )
    if not targets:
        return HFPoolHealth(pool=pool.name, status="unavailable", targets=(), error="targets=0")
    if not any(target.status in {"configured", "healthy"} for target in targets):
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
        if target.latency_ms is not None:
            line += f" latency_ms={max(0, int(target.latency_ms))}"
        if target.error and not target.error.startswith("env="):
            line += f" error={_status_text(target.error)}"
        lines.append(line)
    return lines


def _live_target_status(
    *,
    pool: HFPool,
    target: HFPoolTarget,
    api_key: str,
    opener: HFPoolOpener | None,
    state_store: HFPoolRuntimeStateStore | None,
) -> tuple[str, str, int | None]:
    usage_events: list[HFPoolUsageEvent] = []
    executor = OpenAICompatibleHFPoolExecutor(opener=opener, usage_events=usage_events, state_store=state_store)
    instructions = BotInstructions(
        openai_system_prompt="HF pool health check. Reply briefly.",
        openai_max_output_tokens=16,
    )
    try:
        executor.create_reply(
            ScheduledTarget(pool=pool, target=target, api_key=api_key),
            "Reply with exactly: ok",
            instructions,
        )
    except HFPoolRateLimited as exc:
        return "cooldown", redact_hf_secrets(str(exc)), _last_latency(usage_events)
    except (HFPoolTargetUnavailable, HFPoolUnavailable) as exc:
        return "unavailable", redact_hf_secrets(str(exc)), _last_latency(usage_events)
    except Exception as exc:  # noqa: BLE001 - live doctor must report and continue.
        return "error", redact_hf_secrets(f"{type(exc).__name__}: {exc}"), _last_latency(usage_events)
    return "healthy", "", _last_latency(usage_events)


def _last_latency(events: list[HFPoolUsageEvent]) -> int | None:
    if not events:
        return None
    latency = events[-1].latency_ms
    return None if latency is None else max(0, int(latency))


def _status_text(value: object) -> str:
    return str(value or "").replace("\n", " ").replace("\r", " ").strip()
