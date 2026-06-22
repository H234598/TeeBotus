from __future__ import annotations

import sys
import types

import pytest

from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.hf_pool import (
    HFPool,
    HFPoolRateLimited,
    HFPoolRuntimeState,
    HFPoolTarget,
    HFPoolUsageEvent,
    LiteLLMHFPoolExecutor,
    ScheduledTarget,
    SQLiteHFPoolRuntimeStateStore,
)


def test_litellm_hf_executor_routes_through_litellm_and_records_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def completion(**kwargs):
        calls.append(kwargs)
        return _Response(
            {
                "id": "chatcmpl_test",
                "choices": [{"message": {"content": "Antwort aus HF"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4},
            }
        )

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))
    state = HFPoolRuntimeState()
    events: list[HFPoolUsageEvent] = []
    executor = LiteLLMHFPoolExecutor(state=state, usage_events=events)
    instructions = BotInstructions(openai_system_prompt="Systemregel", openai_max_output_tokens=123)

    response = executor.create_reply(_scheduled(api_key="hf_TESTSECRET123"), "Hallo", instructions)

    assert response.text == "Antwort aus HF"
    assert response.response_id is None
    assert response.provider == "hf_pool"
    assert response.model == "Qwen/Qwen3-4B-Instruct"
    assert response.usage["prompt_tokens"] == 3
    assert response.usage["completion_tokens"] == 4
    assert response.usage["litellm_provider"] == "litellm"
    assert response.usage["litellm_model"] == "huggingface/Qwen/Qwen3-4B-Instruct"
    assert state.successes == {"default/target_a": 1}
    assert state.failures == {}
    assert state.cooldowns == {}
    assert len(events) == 1
    assert events[0].status == "ok"
    assert events[0].usage["prompt_tokens"] == 3
    assert events[0].usage["completion_tokens"] == 4
    assert calls == [
        {
            "model": "huggingface/Qwen/Qwen3-4B-Instruct",
            "api_base": "https://router.huggingface.co/v1",
            "api_key": "hf_TESTSECRET123",
            "timeout": 7,
            "messages": [
                {"role": "system", "content": instructions.openai_instructions_text()},
                {"role": "user", "content": "Hallo"},
            ],
            "max_tokens": 123,
        }
    ]


def test_litellm_hf_executor_rate_limit_sets_cooldown_and_redacts_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    def completion(**_kwargs):
        raise RuntimeError("429 Too Many Requests: bad Bearer hf_TESTSECRET123")

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))
    state = HFPoolRuntimeState()
    events: list[HFPoolUsageEvent] = []
    executor = LiteLLMHFPoolExecutor(state=state, usage_events=events)

    with pytest.raises(HFPoolRateLimited) as excinfo:
        executor.create_reply(_scheduled(api_key="hf_TESTSECRET123"), "Hallo", BotInstructions())

    assert "hf_TESTSECRET123" not in str(excinfo.value)
    assert "<REDACTED>" in str(excinfo.value)
    assert state.failures == {"default/target_a": 1}
    assert "default/target_a" in state.cooldowns
    assert events[-1].status == "rate_limited"
    assert events[-1].usage["http_status"] == 429
    assert events[-1].usage["error_type"] == "LLMAPIError"


def test_openai_compatible_hf_executor_skips_http_while_target_is_in_cooldown() -> None:
    state = HFPoolRuntimeState(cooldowns={"target_a": "2999-01-01T00:00:00+00:00"})

    executor = LiteLLMHFPoolExecutor(state=state)

    with pytest.raises(HFPoolRateLimited, match="cooldown"):
        executor.create_reply(_scheduled(api_key="hf_TESTSECRET123"), "Hallo", BotInstructions())


def test_litellm_hf_executor_keeps_cooldowns_scoped_to_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    state = HFPoolRuntimeState(cooldowns={"other/target_a": "2999-01-01T00:00:00+00:00"})

    def completion(**_kwargs):
        return _Response({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))
    executor = LiteLLMHFPoolExecutor(state=state)

    response = executor.create_reply(_scheduled(api_key="hf_TESTSECRET123"), "Hallo", BotInstructions())

    assert response.text == "ok"
    assert state.successes == {"default/target_a": 1}
    assert "other/target_a" in state.cooldowns


def test_sqlite_hf_pool_state_store_roundtrips_state_and_usage(tmp_path) -> None:
    store = SQLiteHFPoolRuntimeStateStore(tmp_path / "hf_pool_state.sqlite3")
    state = HFPoolRuntimeState(
        cooldowns={"target_a": "2999-01-01T00:00:00+00:00"},
        failures={"target_a": 2},
        successes={"target_b": 3},
        avg_latency_ms={"target_a": 42.5},
    )

    store.save(state)
    store.append_usage(
        HFPoolUsageEvent(
            pool="default",
            target="target_a",
            model="Model",
            status="rate_limited",
            latency_ms=12,
            usage={
                "http_status": 429,
                "detail": "bad Bearer hf_TESTSECRET123",
                "nested": {"token": "hf_TESTSECRET456"},
            },
        )
    )

    loaded = store.load()
    usage = store.read_usage()

    assert loaded.cooldowns == state.cooldowns
    assert loaded.failures == state.failures
    assert loaded.successes == state.successes
    assert loaded.avg_latency_ms == state.avg_latency_ms
    assert len(usage) == 1
    assert usage[0].target == "target_a"
    assert usage[0].usage == {
        "detail": "bad Bearer <REDACTED>",
        "http_status": 429,
        "nested": {"token": "hf_<REDACTED>"},
    }


def test_litellm_hf_executor_reuses_persistent_cooldown(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    def rate_limited(**_kwargs):
        raise RuntimeError("429 rate limited")

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=rate_limited))
    state_store = SQLiteHFPoolRuntimeStateStore(tmp_path / "hf_pool_state.sqlite3")
    executor = LiteLLMHFPoolExecutor(state_store=state_store)

    with pytest.raises(HFPoolRateLimited):
        executor.create_reply(_scheduled(api_key="hf_TESTSECRET123"), "Hallo", BotInstructions())

    assert "default/target_a" in state_store.load().cooldowns

    def unexpected_completion(**_kwargs):  # pragma: no cover - must not be called
        raise AssertionError("persistent cooldown should stop before LiteLLM")

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=unexpected_completion))
    second_executor = LiteLLMHFPoolExecutor(state_store=state_store)

    with pytest.raises(HFPoolRateLimited, match="cooldown"):
        second_executor.create_reply(_scheduled(api_key="hf_TESTSECRET123"), "Hallo", BotInstructions())


class _Response(dict):
    def __init__(self, payload: dict[str, object]) -> None:
        super().__init__(payload)

    @property
    def _hidden_params(self) -> dict[str, object]:
        return {}


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
