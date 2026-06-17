from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.hf_pool.config import DEFAULT_HF_POOL_CONFIG_PATH, HFPool, HFPoolConfig, load_hf_pool_config
from TeeBotus.llm.hf_pool.errors import HFPoolRateLimited, HFPoolTargetUnavailable, HFPoolUnavailable
from TeeBotus.llm.hf_pool.executor import HFPoolOpener, OpenAICompatibleHFPoolExecutor
from TeeBotus.llm.hf_pool.metrics import HFPoolUsageEvent
from TeeBotus.llm.hf_pool.models_feed import (
    HFPoolModelInfo,
    HFPoolModelsFeed,
    HFPoolModelsOpener,
    fetch_hf_pool_models,
    model_info_by_id,
)
from TeeBotus.llm.hf_pool.redaction import redact_hf_secrets
from TeeBotus.llm.hf_pool.scheduler import ScheduledTarget
from TeeBotus.llm.hf_pool.state import HFPoolRuntimeState, HFPoolRuntimeStateStore, hf_pool_state_lookup
from TeeBotus.llm.hf_pool.targets import HFPoolTarget


@dataclass(frozen=True)
class HFPoolTargetHealth:
    pool: str
    name: str
    status: str
    model: str = ""
    api_key_env: str = ""
    error: str = ""
    cooldown_until: str = ""
    latency_ms: int | None = None
    successes: int = 0
    failures: int = 0
    avg_latency_ms: int | None = None
    models_feed_status: str = ""
    context_length: int | None = None
    supports_tools: bool | None = None
    supports_structured_output: bool | None = None


@dataclass(frozen=True)
class HFPoolHealth:
    pool: str
    status: str
    targets: tuple[HFPoolTargetHealth, ...] = ()
    error: str = ""

    @property
    def healthy_count(self) -> int:
        return sum(1 for target in self.targets if target.status in {"configured", "healthy"})

    def target_status_count(self, status: str) -> int:
        return sum(1 for target in self.targets if target.status == status)


def check_hf_pool(
    *,
    pool_name: str = "default",
    config_path: str | Path = DEFAULT_HF_POOL_CONFIG_PATH,
    env: Mapping[str, str] | None = None,
    live: bool = False,
    opener: HFPoolOpener | None = None,
    validate_models: bool = False,
    models_opener: HFPoolModelsOpener | None = None,
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
    runtime_state, state_error = _load_state(state_store)
    models_cache: dict[tuple[str, str], HFPoolModelsFeed] = {}
    targets: list[HFPoolTargetHealth] = []
    for target in pool.targets:
        cooldown_until = ""
        models_feed_status = ""
        context_length = None
        supports_tools = None
        supports_structured_output = None
        successes, failures, avg_latency_ms = _target_runtime_metrics(runtime_state, pool.name, target.name)
        if not target.enabled:
            status = "disabled"
            error = ""
            latency_ms = None
        elif target.api_key_env and not source.get(target.api_key_env, "").strip():
            status = "missing_key"
            error = f"env={target.api_key_env}"
            latency_ms = None
        elif not live and runtime_state is not None and (cooldown_until := _active_cooldown_until(runtime_state, pool.name, target.name)):
            status = "cooldown"
            error = ""
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
        if validate_models and status in {"configured", "healthy"}:
            model_info, models_feed_status, model_error = _validate_target_model(
                target=target,
                api_key=source.get(target.api_key_env, "").strip() if target.api_key_env else "",
                timeout_seconds=pool.timeout_seconds,
                opener=models_opener,
                cache=models_cache,
            )
            if model_info is not None:
                context_length = model_info.context_length
                supports_tools = model_info.supports_tools
                supports_structured_output = model_info.supports_structured_output
            if model_error:
                status = "unavailable"
                error = model_error if not error else f"{error}; {model_error}"
        targets.append(
            HFPoolTargetHealth(
                pool=pool.name,
                name=target.name,
                status=status,
                model=target.model,
                api_key_env=target.api_key_env,
                error=error,
                cooldown_until=cooldown_until,
                latency_ms=latency_ms,
                successes=successes,
                failures=failures,
                avg_latency_ms=avg_latency_ms,
                models_feed_status=models_feed_status,
                context_length=context_length,
                supports_tools=supports_tools,
                supports_structured_output=supports_structured_output,
            )
        )
    if not targets:
        return HFPoolHealth(pool=pool.name, status="unavailable", targets=(), error="targets=0")
    if not any(target.status in {"configured", "healthy"} for target in targets):
        error = "all_configured_targets_in_cooldown" if any(target.status == "cooldown" for target in targets) else "no_configured_targets"
        if state_error:
            error = f"{error}; state_error={state_error}"
        return HFPoolHealth(pool=pool.name, status="unavailable", targets=tuple(targets), error=error)
    return HFPoolHealth(pool=pool.name, status="configured", targets=tuple(targets), error=f"state_error={state_error}" if state_error else "")


def format_hf_pool_status_lines(health: HFPoolHealth) -> list[str]:
    lines = [f"hf_pool={_status_text(health.pool)} status={_status_text(health.status)}"]
    if health.targets:
        lines[0] += (
            f" targets={len(health.targets)} healthy={health.healthy_count}"
            f" unavailable={health.target_status_count('unavailable')}"
            f" cooldown={health.target_status_count('cooldown')}"
            f" missing_key={health.target_status_count('missing_key')}"
            f" disabled={health.target_status_count('disabled')}"
        )
    if health.error:
        lines[0] += f" error={_status_text(health.error)}"
    for target in health.targets:
        line = f"hf_pool={_status_text(health.pool)} target={_status_text(target.name)} status={_status_text(target.status)}"
        if target.model:
            line += f" model={_status_text(target.model)}"
        if target.api_key_env:
            line += f" env={_status_text(target.api_key_env)}"
        if target.cooldown_until:
            line += f" until={_status_text(target.cooldown_until)}"
        if target.latency_ms is not None:
            line += f" latency_ms={max(0, int(target.latency_ms))}"
        if target.successes:
            line += f" successes={max(0, int(target.successes))}"
        if target.failures:
            line += f" failures={max(0, int(target.failures))}"
        if target.avg_latency_ms is not None:
            line += f" avg_latency_ms={max(0, int(target.avg_latency_ms))}"
        if target.models_feed_status:
            line += f" models_feed={_status_text(target.models_feed_status)}"
        if target.context_length is not None:
            line += f" context_length={max(0, int(target.context_length))}"
        if target.supports_tools is not None:
            line += f" tools={str(bool(target.supports_tools)).lower()}"
        if target.supports_structured_output is not None:
            line += f" structured_output={str(bool(target.supports_structured_output)).lower()}"
        if target.error and not target.error.startswith("env="):
            line += f" error={_status_text(target.error)}"
        lines.append(line)
    return lines


def _load_state(state_store: HFPoolRuntimeStateStore | None) -> tuple[HFPoolRuntimeState | None, str]:
    if state_store is None:
        return None, ""
    try:
        return state_store.load(), ""
    except Exception as exc:  # noqa: BLE001 - status must stay non-fatal for optional state.
        return None, redact_hf_secrets(f"{type(exc).__name__}: {exc}")


def _active_cooldown_until(state: HFPoolRuntimeState, pool_name: str, target_name: str) -> str:
    cooldown_until = str(hf_pool_state_lookup(state.cooldowns, pool_name, target_name, "") or "").strip()
    if not cooldown_until:
        return ""
    try:
        parsed = datetime.fromisoformat(cooldown_until)
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if parsed <= datetime.now(timezone.utc):
        return ""
    return cooldown_until


def _target_runtime_metrics(state: HFPoolRuntimeState | None, pool_name: str, target_name: str) -> tuple[int, int, int | None]:
    if state is None:
        return 0, 0, None
    successes = max(0, int(hf_pool_state_lookup(state.successes, pool_name, target_name, 0) or 0))
    failures = max(0, int(hf_pool_state_lookup(state.failures, pool_name, target_name, 0) or 0))
    raw_latency = hf_pool_state_lookup(state.avg_latency_ms, pool_name, target_name, None)
    if raw_latency is None:
        return successes, failures, None
    try:
        avg_latency_ms = max(0, int(round(float(raw_latency))))
    except (TypeError, ValueError):
        avg_latency_ms = None
    return successes, failures, avg_latency_ms


def _validate_target_model(
    *,
    target: HFPoolTarget,
    api_key: str,
    timeout_seconds: int,
    opener: HFPoolModelsOpener | None,
    cache: dict[tuple[str, str], HFPoolModelsFeed],
) -> tuple[HFPoolModelInfo | None, str, str]:
    cache_key = (target.base_url, api_key)
    feed = cache.get(cache_key)
    if feed is None:
        feed = fetch_hf_pool_models(target.base_url, api_key=api_key, timeout_seconds=timeout_seconds, opener=opener)
        cache[cache_key] = feed
    if feed.status != "ok":
        error = f"models_feed={feed.status}"
        if feed.error:
            error += f": {feed.error}"
        return None, feed.status, redact_hf_secrets(error)
    lookup = model_info_by_id(feed.models)
    model_info = lookup.get(target.request_model) or lookup.get(target.model)
    if model_info is None:
        return None, feed.status, f"models_feed_model_missing:{_status_text(target.request_model)}"
    error = _model_requirement_error(target, model_info)
    return model_info, feed.status, error


def _model_requirement_error(target: HFPoolTarget, model_info: HFPoolModelInfo) -> str:
    errors: list[str] = []
    required = target.capabilities
    if required.supports_tools and not model_info.supports_tools:
        errors.append("models_feed_missing_tools")
    if required.supports_structured_output and not model_info.supports_structured_output:
        errors.append("models_feed_missing_structured_output")
    if required.context_length:
        if model_info.context_length is None:
            errors.append(f"models_feed_missing_context_length:required={required.context_length}")
        elif model_info.context_length < required.context_length:
            errors.append(f"models_feed_context_length_too_small:required={required.context_length}:found={model_info.context_length}")
    return "; ".join(errors)


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
    return redact_hf_secrets(value).replace("\n", " ").replace("\r", " ").strip()
