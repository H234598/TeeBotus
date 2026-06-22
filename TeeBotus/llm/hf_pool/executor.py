from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from typing import Protocol

from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.base import LLMAPIError, LLMResponse
from TeeBotus.llm.hf_pool.errors import HFPoolRateLimited, HFPoolTargetUnavailable
from TeeBotus.llm.hf_pool.metrics import HFPoolUsageEvent
from TeeBotus.llm.hf_pool.redaction import redact_hf_secrets
from TeeBotus.llm.hf_pool.scheduler import ScheduledTarget
from TeeBotus.llm.hf_pool.state import HFPoolRuntimeState, HFPoolRuntimeStateStore, hf_pool_state_key, hf_pool_state_lookup, hf_pool_state_pop
from TeeBotus.llm.litellm_provider import LiteLLMSettings, LiteLLMTextClient
from TeeBotus.runtime.log_context import logging_context, next_llm_call_id


LOGGER = logging.getLogger("TeeBotus.llm.hf_pool.executor")


class HFPoolExecutor(Protocol):
    def create_reply(self, scheduled: ScheduledTarget, user_text: str, instructions: BotInstructions) -> LLMResponse:
        ...


@dataclass
class HFPoolMockExecutor:
    text: str = "hf_pool mock response"

    def create_reply(self, scheduled: ScheduledTarget, user_text: str, instructions: BotInstructions) -> LLMResponse:
        return LLMResponse(
            text=self.text,
            provider="hf_pool",
            model=scheduled.target.request_model,
            usage={"mock": True, "target": scheduled.target.name},
        )


HFPoolOpener = Callable[..., Any]


@dataclass
class LiteLLMHFPoolExecutor:
    """HF-pool executor whose provider calls are routed through LiteLLM."""

    opener: HFPoolOpener | None = None
    state: HFPoolRuntimeState | None = None
    usage_events: list[HFPoolUsageEvent] | None = None
    state_store: HFPoolRuntimeStateStore | None = None

    def create_reply(self, scheduled: ScheduledTarget, user_text: str, instructions: BotInstructions) -> LLMResponse:
        state = self._runtime_state()
        self._raise_if_in_cooldown(scheduled, state)
        started = time.monotonic()
        call_id = next_llm_call_id("hf_pool")
        provider = _target_litellm_provider(scheduled)
        model = scheduled.target.request_model
        api_base = str(scheduled.target.base_url or "").strip()
        context = logging_context(
            component="hf_pool",
            operation="litellm_completion",
            llm_call_id=call_id,
            provider="hf_pool",
            model=model,
            api_base=_safe_endpoint_for_log(api_base),
        )
        try:
            with context:
                LOGGER.info(
                    "HF pool LiteLLM request started call_id=%s pool=%s target=%s provider=%s model=%s api_base=%s timeout_seconds=%s request_chars=%s",
                    call_id,
                    scheduled.pool.name,
                    scheduled.target.name,
                    provider,
                    model,
                    _safe_endpoint_for_log(api_base),
                    max(1, int(scheduled.pool.timeout_seconds)),
                    len(user_text),
                )
                if self.opener is not None:
                    LOGGER.debug("HF pool opener argument is ignored because live calls are routed through LiteLLM.")
                litellm_response = self._litellm_client(scheduled, provider=provider, model=model).create_reply(
                    user_text,
                    instructions,
                    None,
                )
        except Exception as exc:  # noqa: BLE001 - executor boundary normalizes LiteLLM/provider failures.
            rate_limited = _is_rate_limited_error(exc)
            status_code = 429 if rate_limited else 0
            self._record_failure(scheduled, state, status_code)
            usage = {"http_status": status_code, "error_type": type(exc).__name__}
            self._append_usage(scheduled, "rate_limited" if rate_limited else "provider_error", started, usage, state)
            detail = _redact_executor_error(exc, scheduled)
            if rate_limited:
                raise HFPoolRateLimited(detail) from exc
            raise HFPoolTargetUnavailable(detail) from exc
        text = str(litellm_response.text or "").strip()
        if not text:
            self._record_failure(scheduled, state, 0)
            self._append_usage(scheduled, "empty_response", started, {}, state)
            raise HFPoolTargetUnavailable("hf_pool LiteLLM target returned no message content")
        state_key = hf_pool_state_key(scheduled.pool.name, scheduled.target.name)
        state.successes[state_key] = state.successes.get(state_key, 0) + 1
        hf_pool_state_pop(state.failures, scheduled.pool.name, scheduled.target.name)
        hf_pool_state_pop(state.cooldowns, scheduled.pool.name, scheduled.target.name)
        usage = dict(litellm_response.usage or {})
        usage.setdefault("litellm_provider", litellm_response.provider)
        usage.setdefault("litellm_model", litellm_response.model)
        self._append_usage(scheduled, "ok", started, usage, state)
        LOGGER.info(
            "HF pool LiteLLM request finished call_id=%s pool=%s target=%s provider=%s model=%s elapsed_ms=%s response_chars=%s usage=%s",
            call_id,
            scheduled.pool.name,
            scheduled.target.name,
            provider,
            model,
            int((time.monotonic() - started) * 1000),
            len(text),
            _compact_usage_for_log(usage),
        )
        return LLMResponse(
            text=text,
            response_id=litellm_response.response_id,
            provider="hf_pool",
            model=model,
            usage=usage,
            raw=litellm_response.raw,
        )

    def _litellm_client(self, scheduled: ScheduledTarget, *, provider: str, model: str) -> LiteLLMTextClient:
        return LiteLLMTextClient(
            LiteLLMSettings(
                provider=provider,
                model=model,
                api_key=scheduled.api_key,
                api_base=str(scheduled.target.base_url or "").strip(),
                timeout=max(1, int(scheduled.pool.timeout_seconds)),
                timeout_override=True,
                use_instruction_fallback_models=False,
            )
        )

    def _runtime_state(self) -> HFPoolRuntimeState:
        if self.state_store is not None:
            state = self.state_store.load()
            self.state = state
            return state
        if self.state is None:
            self.state = HFPoolRuntimeState()
        return self.state

    def _persist_state(self, state: HFPoolRuntimeState) -> None:
        self.state = state
        if self.state_store is not None:
            self.state_store.save(state)

    def _raise_if_in_cooldown(self, scheduled: ScheduledTarget, state: HFPoolRuntimeState) -> None:
        cooldown_until = hf_pool_state_lookup(state.cooldowns, scheduled.pool.name, scheduled.target.name, "")
        if not cooldown_until:
            return
        try:
            parsed = datetime.fromisoformat(cooldown_until)
        except ValueError:
            hf_pool_state_pop(state.cooldowns, scheduled.pool.name, scheduled.target.name)
            self._persist_state(state)
            return
        if parsed > datetime.now(timezone.utc):
            raise HFPoolRateLimited(f"hf_pool target {scheduled.target.name} is in cooldown until {cooldown_until}")
        hf_pool_state_pop(state.cooldowns, scheduled.pool.name, scheduled.target.name)
        self._persist_state(state)

    def _record_failure(self, scheduled: ScheduledTarget, state: HFPoolRuntimeState, status_code: int) -> None:
        state_key = hf_pool_state_key(scheduled.pool.name, scheduled.target.name)
        state.failures[state_key] = state.failures.get(state_key, 0) + 1
        cooldown_seconds = 0
        if status_code == 429:
            cooldown_seconds = scheduled.pool.cooldown_seconds_on_429
        elif status_code >= 500:
            cooldown_seconds = scheduled.pool.cooldown_seconds_on_5xx
        elif status_code == 0:
            cooldown_seconds = scheduled.pool.cooldown_seconds_on_timeout
        if cooldown_seconds > 0:
            state.cooldowns[state_key] = (datetime.now(timezone.utc) + timedelta(seconds=cooldown_seconds)).isoformat()

    def _append_usage(self, scheduled: ScheduledTarget, status: str, started: float, usage: dict[str, Any], state: HFPoolRuntimeState) -> None:
        latency_ms = max(0, int(round((time.monotonic() - started) * 1000)))
        _record_average_latency(state, scheduled.pool.name, scheduled.target.name, latency_ms)
        event = HFPoolUsageEvent(
            pool=scheduled.pool.name,
            target=scheduled.target.name,
            model=scheduled.target.request_model,
            status=status,
            latency_ms=latency_ms,
            usage=dict(usage),
        )
        if self.usage_events is not None:
            self.usage_events.append(event)
        if self.state_store is not None:
            self.state_store.append_usage(event)
        self._persist_state(state)


OpenAICompatibleHFPoolExecutor = LiteLLMHFPoolExecutor


def _target_litellm_provider(scheduled: ScheduledTarget) -> str:
    kind = str(scheduled.target.kind or "").strip().casefold().replace("-", "_")
    if kind in {"openai_compatible", "openai_chat", "litellm"}:
        return "litellm"
    if kind == "groq":
        return "groq"
    return "huggingface"


def _safe_endpoint_for_log(endpoint: str) -> str:
    text = str(endpoint or "").strip()
    if "@" in text:
        return text.split("@", maxsplit=1)[-1]
    return text[:180]


def _compact_usage_for_log(usage: dict[str, Any]) -> dict[str, Any]:
    keys = ("input_tokens", "prompt_tokens", "output_tokens", "completion_tokens", "total_tokens", "response_cost")
    return {key: usage[key] for key in keys if key in usage}


def _record_average_latency(state: HFPoolRuntimeState, pool_name: str, target_name: str, latency_ms: int) -> None:
    state_key = hf_pool_state_key(pool_name, target_name)
    previous = float(state.avg_latency_ms.get(state_key, 0.0) or 0.0)
    completed = max(0, state.successes.get(state_key, 0) + state.failures.get(state_key, 0) - 1)
    if completed <= 0 or previous <= 0:
        state.avg_latency_ms[state_key] = float(latency_ms)
        return
    state.avg_latency_ms[state_key] = ((previous * completed) + latency_ms) / (completed + 1)


def _is_rate_limited_error(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if str(status or "").strip() == "429":
        return True
    text = f"{type(exc).__name__} {exc}".casefold()
    return any(marker in text for marker in ("429", "rate limit", "ratelimit", "resource_exhausted", "quota exceeded", "too many requests"))


def _redact_executor_error(exc: Exception, scheduled: ScheduledTarget) -> str:
    detail = str(exc)
    if isinstance(exc, LLMAPIError):
        detail = str(exc)
    api_key = str(scheduled.api_key or "").strip()
    if api_key:
        detail = detail.replace(api_key, "<REDACTED>")
    return redact_hf_secrets(detail)
