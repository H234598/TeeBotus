from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.base import LLMResponse
from TeeBotus.llm.hf_pool.errors import HFPoolRateLimited, HFPoolTargetUnavailable
from TeeBotus.llm.hf_pool.metrics import HFPoolUsageEvent
from TeeBotus.llm.hf_pool.redaction import redact_hf_secrets
from TeeBotus.llm.hf_pool.scheduler import ScheduledTarget
from TeeBotus.llm.hf_pool.state import HFPoolRuntimeState


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
class OpenAICompatibleHFPoolExecutor:
    opener: HFPoolOpener | None = None
    state: HFPoolRuntimeState | None = None
    usage_events: list[HFPoolUsageEvent] | None = None

    def create_reply(self, scheduled: ScheduledTarget, user_text: str, instructions: BotInstructions) -> LLMResponse:
        state = self.state or HFPoolRuntimeState()
        self._raise_if_in_cooldown(scheduled, state)
        started = time.monotonic()
        request = self._request(scheduled, user_text, instructions)
        try:
            response = (self.opener or urlopen)(request, timeout=max(1, int(scheduled.pool.timeout_seconds)))
            status_code = int(getattr(response, "status", getattr(response, "code", 200)) or 200)
            raw = response.read() if hasattr(response, "read") else b"{}"
            close = getattr(response, "close", None)
            if callable(close):
                close()
        except HTTPError as exc:
            self._record_failure(scheduled, state, exc.code)
            error_text = _http_error_text(exc)
            self._append_usage(scheduled, "rate_limited" if exc.code == 429 else "http_error", started, {"http_status": exc.code})
            if exc.code == 429:
                raise HFPoolRateLimited(redact_hf_secrets(error_text)) from exc
            raise HFPoolTargetUnavailable(redact_hf_secrets(error_text)) from exc
        except (URLError, TimeoutError, OSError) as exc:
            self._record_failure(scheduled, state, 0)
            self._append_usage(scheduled, "transport_error", started, {})
            raise HFPoolTargetUnavailable(redact_hf_secrets(str(exc))) from exc
        if not 200 <= status_code < 300:
            self._record_failure(scheduled, state, status_code)
            self._append_usage(scheduled, "http_error", started, {"http_status": status_code})
            raise HFPoolTargetUnavailable(f"hf_pool HTTP {status_code}")
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._record_failure(scheduled, state, status_code)
            self._append_usage(scheduled, "invalid_json", started, {"http_status": status_code})
            raise HFPoolTargetUnavailable("hf_pool target returned invalid JSON") from exc
        text = _extract_chat_text(payload)
        if not text:
            self._record_failure(scheduled, state, status_code)
            self._append_usage(scheduled, "empty_response", started, {"http_status": status_code})
            raise HFPoolTargetUnavailable("hf_pool target returned no message content")
        state.successes[scheduled.target.name] = state.successes.get(scheduled.target.name, 0) + 1
        state.failures.pop(scheduled.target.name, None)
        state.cooldowns.pop(scheduled.target.name, None)
        usage = dict(payload.get("usage") or {}) if isinstance(payload.get("usage"), dict) else {}
        self._append_usage(scheduled, "ok", started, usage)
        return LLMResponse(
            text=text,
            response_id=str(payload.get("id") or "") or None,
            provider="hf_pool",
            model=scheduled.target.request_model,
            usage=usage,
            raw=payload if isinstance(payload, dict) else None,
        )

    def _request(self, scheduled: ScheduledTarget, user_text: str, instructions: BotInstructions) -> Request:
        body: dict[str, Any] = {
            "model": scheduled.target.request_model,
            "messages": [
                {"role": "system", "content": instructions.openai_instructions_text()},
                {"role": "user", "content": str(user_text or "")},
            ],
        }
        if instructions.openai_max_output_tokens:
            body["max_tokens"] = int(instructions.openai_max_output_tokens)
        endpoint = _chat_completions_endpoint(scheduled.target.base_url)
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if scheduled.api_key:
            headers["Authorization"] = f"Bearer {scheduled.api_key}"
        return Request(endpoint, data=json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), method="POST", headers=headers)

    def _raise_if_in_cooldown(self, scheduled: ScheduledTarget, state: HFPoolRuntimeState) -> None:
        cooldown_until = state.cooldowns.get(scheduled.target.name)
        if not cooldown_until:
            return
        try:
            parsed = datetime.fromisoformat(cooldown_until)
        except ValueError:
            state.cooldowns.pop(scheduled.target.name, None)
            return
        if parsed > datetime.now(timezone.utc):
            raise HFPoolRateLimited(f"hf_pool target {scheduled.target.name} is in cooldown until {cooldown_until}")
        state.cooldowns.pop(scheduled.target.name, None)

    def _record_failure(self, scheduled: ScheduledTarget, state: HFPoolRuntimeState, status_code: int) -> None:
        state.failures[scheduled.target.name] = state.failures.get(scheduled.target.name, 0) + 1
        cooldown_seconds = 0
        if status_code == 429:
            cooldown_seconds = scheduled.pool.cooldown_seconds_on_429
        elif status_code >= 500:
            cooldown_seconds = scheduled.pool.cooldown_seconds_on_5xx
        elif status_code == 0:
            cooldown_seconds = scheduled.pool.cooldown_seconds_on_timeout
        if cooldown_seconds > 0:
            state.cooldowns[scheduled.target.name] = (datetime.now(timezone.utc) + timedelta(seconds=cooldown_seconds)).isoformat()

    def _append_usage(self, scheduled: ScheduledTarget, status: str, started: float, usage: dict[str, Any]) -> None:
        if self.usage_events is None:
            return
        self.usage_events.append(
            HFPoolUsageEvent(
                pool=scheduled.pool.name,
                target=scheduled.target.name,
                model=scheduled.target.request_model,
                status=status,
                latency_ms=max(0, int(round((time.monotonic() - started) * 1000))),
                usage=dict(usage),
            )
        )


def _chat_completions_endpoint(base_url: str) -> str:
    base = str(base_url or "https://router.huggingface.co/v1").strip().rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _extract_chat_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(str(item.get("text", "")) for item in content if isinstance(item, dict)).strip()
    text = first.get("text")
    return str(text or "").strip()


def _http_error_text(exc: HTTPError) -> str:
    try:
        raw = exc.read()
    except Exception:  # pragma: no cover - defensive only.
        raw = b""
    detail = ""
    if raw:
        try:
            payload = json.loads(raw.decode("utf-8"))
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict):
                    detail = str(error.get("message") or error)
                else:
                    detail = str(error or payload)
            else:
                detail = str(payload)
        except Exception:
            detail = raw.decode("utf-8", errors="replace")
    return f"hf_pool HTTP {exc.code}: {detail}".strip()
