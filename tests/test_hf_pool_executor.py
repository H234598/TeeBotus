from __future__ import annotations

import json
from urllib.error import HTTPError

import pytest

from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.hf_pool import (
    HFPool,
    HFPoolRateLimited,
    HFPoolRuntimeState,
    HFPoolTarget,
    HFPoolUsageEvent,
    OpenAICompatibleHFPoolExecutor,
    ScheduledTarget,
)


class _Response:
    def __init__(self, payload: dict[str, object], status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def close(self) -> None:
        return None


def test_openai_compatible_hf_executor_sends_chat_completion_and_records_usage() -> None:
    calls: list[dict[str, object]] = []

    def opener(request, *, timeout):
        calls.append(
            {
                "url": request.full_url,
                "timeout": timeout,
                "authorization": request.get_header("Authorization"),
                "body": json.loads(request.data.decode("utf-8")),
            }
        )
        return _Response(
            {
                "id": "chatcmpl_test",
                "choices": [{"message": {"content": "Antwort aus HF"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4},
            }
        )

    state = HFPoolRuntimeState()
    events: list[HFPoolUsageEvent] = []
    executor = OpenAICompatibleHFPoolExecutor(opener=opener, state=state, usage_events=events)
    instructions = BotInstructions(openai_system_prompt="Systemregel", openai_max_output_tokens=123)

    response = executor.create_reply(_scheduled(api_key="hf_TESTSECRET123"), "Hallo", instructions)

    assert response.text == "Antwort aus HF"
    assert response.response_id == "chatcmpl_test"
    assert response.provider == "hf_pool"
    assert response.model == "Qwen/Qwen3-4B-Instruct"
    assert response.usage == {"prompt_tokens": 3, "completion_tokens": 4}
    assert state.successes == {"target_a": 1}
    assert state.failures == {}
    assert state.cooldowns == {}
    assert len(events) == 1
    assert events[0].status == "ok"
    assert events[0].usage == {"prompt_tokens": 3, "completion_tokens": 4}
    assert calls == [
        {
            "url": "https://router.huggingface.co/v1/chat/completions",
            "timeout": 7,
            "authorization": "Bearer hf_TESTSECRET123",
            "body": {
                "model": "Qwen/Qwen3-4B-Instruct",
                "messages": [
                    {"role": "system", "content": instructions.openai_instructions_text()},
                    {"role": "user", "content": "Hallo"},
                ],
                "max_tokens": 123,
            },
        }
    ]


def test_openai_compatible_hf_executor_rate_limit_sets_cooldown_and_redacts_secret() -> None:
    def opener(request, *, timeout):  # noqa: ARG001
        body = json.dumps({"error": {"message": "bad Bearer hf_TESTSECRET123"}}).encode("utf-8")
        raise HTTPError(request.full_url, 429, "Too Many Requests", hdrs=None, fp=_ErrorBody(body))

    state = HFPoolRuntimeState()
    events: list[HFPoolUsageEvent] = []
    executor = OpenAICompatibleHFPoolExecutor(opener=opener, state=state, usage_events=events)

    with pytest.raises(HFPoolRateLimited) as excinfo:
        executor.create_reply(_scheduled(api_key="hf_TESTSECRET123"), "Hallo", BotInstructions())

    assert "hf_TESTSECRET123" not in str(excinfo.value)
    assert "hf_<REDACTED>" in str(excinfo.value)
    assert state.failures == {"target_a": 1}
    assert "target_a" in state.cooldowns
    assert events[-1].status == "rate_limited"
    assert events[-1].usage == {"http_status": 429}


def test_openai_compatible_hf_executor_skips_http_while_target_is_in_cooldown() -> None:
    state = HFPoolRuntimeState(cooldowns={"target_a": "2999-01-01T00:00:00+00:00"})

    def opener(_request, *, timeout):  # pragma: no cover - must not be called
        raise AssertionError("cooldown should stop before HTTP")

    executor = OpenAICompatibleHFPoolExecutor(opener=opener, state=state)

    with pytest.raises(HFPoolRateLimited, match="cooldown"):
        executor.create_reply(_scheduled(api_key="hf_TESTSECRET123"), "Hallo", BotInstructions())


class _ErrorBody:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def read(self) -> bytes:
        return self.data

    def close(self) -> None:
        return None


def _scheduled(*, api_key: str = "") -> ScheduledTarget:
    pool = HFPool(name="default", timeout_seconds=7, cooldown_seconds_on_429=60)
    target = HFPoolTarget(
        name="target_a",
        kind="hf_router_chat",
        base_url="https://router.huggingface.co/v1",
        api_key_env="HF_TOKEN_MAIN",
        model="Qwen/Qwen3-4B-Instruct",
    )
    return ScheduledTarget(pool=pool, target=target, api_key=api_key)
