from __future__ import annotations

import json

import pytest

from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.base import LLMResponse
from TeeBotus.llm.hf_pool.errors import HFPoolUnavailable
from TeeBotus.llm.hf_pool.executor import HFPoolMockExecutor
from TeeBotus.llm.hf_pool.provider import HFPoolProvider
from TeeBotus.llm.hf_pool.state import HFPoolRuntimeState


def test_hf_pool_provider_missing_config_raises_controlled_llm_error(tmp_path):
    provider = HFPoolProvider(config_path=tmp_path / "missing.yaml")

    with pytest.raises(HFPoolUnavailable, match="missing"):
        provider.create_reply("ping", BotInstructions())


def test_hf_pool_provider_malformed_config_raises_controlled_llm_error(tmp_path):
    path = tmp_path / "hf_pool.yaml"
    path.write_text("[]", encoding="utf-8")
    provider = HFPoolProvider(config_path=path)

    with pytest.raises(HFPoolUnavailable, match="root must be a mapping"):
        provider.create_reply("ping", BotInstructions())


def test_hf_pool_provider_missing_target_key_is_unavailable_not_crash(tmp_path):
    path = tmp_path / "hf_pool.yaml"
    path.write_text(
        json.dumps(
            {
                "pools": {
                    "default": {
                        "enabled": True,
                        "targets": [
                            {
                                "name": "needs_key",
                                "api_key_env": "HF_TOKEN_MAIN",
                                "model": "Qwen/Qwen3-4B-Instruct-2507",
                            }
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    provider = HFPoolProvider(config_path=path, env={})

    with pytest.raises(HFPoolUnavailable, match="configured API key"):
        provider.create_reply("ping", BotInstructions())


def test_hf_pool_provider_configured_target_without_executor_is_unavailable_not_mock(tmp_path):
    path = _enabled_config(tmp_path)
    provider = HFPoolProvider(config_path=path, env={"HF_TOKEN_MAIN": "hf-secret"})

    with pytest.raises(HFPoolUnavailable, match="live executor is not enabled"):
        provider.create_reply("ping", BotInstructions())


def test_hf_pool_provider_live_executor_requires_explicit_env(monkeypatch, tmp_path):
    path = _enabled_config(tmp_path)
    calls: list[dict[str, object]] = []

    def fake_urlopen(request, *, timeout):
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
                "id": "hf-live-test",
                "choices": [{"message": {"content": "live ok"}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1},
            }
        )

    monkeypatch.setattr("TeeBotus.llm.hf_pool.executor.urlopen", fake_urlopen)
    provider = HFPoolProvider(
        config_path=path,
        env={
            "HF_TOKEN_MAIN": "hf-secret",
            "TEEBOTUS_HF_POOL_LIVE": "1",
            "TEEBOTUS_HF_POOL_STATE_DB": str(tmp_path / "hf_pool_state.sqlite3"),
        },
    )

    response = provider.create_reply("ping", BotInstructions(openai_system_prompt="System."))

    assert response.text == "live ok"
    assert response.response_id == "hf-live-test"
    assert response.usage == {"prompt_tokens": 2, "completion_tokens": 1}
    assert calls[0]["authorization"] == "Bearer hf-secret"
    assert calls[0]["body"]["messages"][-1] == {"role": "user", "content": "ping"}


def test_hf_pool_provider_uses_mock_executor_for_configured_target(tmp_path):
    path = _enabled_config(tmp_path)
    provider = HFPoolProvider(config_path=path, env={"HF_TOKEN_MAIN": "hf-secret"}, executor=HFPoolMockExecutor("mock ok"))

    response = provider.create_reply("ping", BotInstructions())

    assert response.text == "mock ok"
    assert response.provider == "hf_pool"
    assert response.model == "Qwen/Qwen3-4B-Instruct-2507"


def test_hf_pool_provider_passes_executor_state_to_scheduler(tmp_path):
    path = _two_target_config(tmp_path)
    executor = _RecordingExecutor()

    provider = HFPoolProvider(config_path=path, env={"HF_TOKEN_MAIN": "hf-secret"}, executor=executor)
    response = provider.create_reply("ping", BotInstructions())

    assert response.text == "selected low_target"
    assert executor.selected_target == "low_target"


def test_hf_pool_provider_retries_next_target_before_fallback(tmp_path):
    path = _two_target_config(tmp_path)
    executor = _RetryExecutor()

    provider = HFPoolProvider(config_path=path, env={"HF_TOKEN_MAIN": "hf-secret"}, executor=executor)
    response = provider.create_reply("ping", BotInstructions())

    assert response.text == "selected low_target"
    assert executor.selected_targets == ["high_target", "low_target"]


def test_hf_pool_provider_redacts_unexpected_executor_errors(tmp_path):
    path = _enabled_config(tmp_path)
    provider = HFPoolProvider(config_path=path, env={"HF_TOKEN_MAIN": "hf-secret"}, executor=_BrokenSecretExecutor())

    with pytest.raises(HFPoolUnavailable) as excinfo:
        provider.create_reply("ping", BotInstructions())

    message = str(excinfo.value)
    assert "hf_TESTSECRET123" not in message
    assert "Bearer hf_" not in message
    assert "Bearer <REDACTED>" in message


def test_hf_pool_provider_redacts_executor_unavailable_errors(tmp_path):
    path = _enabled_config(tmp_path)
    provider = HFPoolProvider(config_path=path, env={"HF_TOKEN_MAIN": "hf-secret"}, executor=_BrokenUnavailableSecretExecutor())

    with pytest.raises(HFPoolUnavailable) as excinfo:
        provider.create_reply("ping", BotInstructions())

    message = str(excinfo.value)
    assert "hf_TESTSECRET123" not in message
    assert "Bearer hf_" not in message
    assert "Bearer <REDACTED>" in message


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.status = 200

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def close(self) -> None:
        return None


class _RecordingExecutor:
    def __init__(self) -> None:
        self.state = HFPoolRuntimeState(cooldowns={"high_target": "2999-01-01T00:00:00+00:00"})
        self.selected_target = ""

    def create_reply(self, scheduled, user_text, instructions):  # noqa: ANN001, ARG002
        self.selected_target = scheduled.target.name
        return LLMResponse(text=f"selected {scheduled.target.name}", provider="hf_pool", model=scheduled.target.request_model)


class _RetryExecutor:
    def __init__(self) -> None:
        self.selected_targets: list[str] = []

    def create_reply(self, scheduled, user_text, instructions):  # noqa: ANN001, ARG002
        self.selected_targets.append(scheduled.target.name)
        if scheduled.target.name == "high_target":
            raise HFPoolUnavailable("high target failed")
        return LLMResponse(text=f"selected {scheduled.target.name}", provider="hf_pool", model=scheduled.target.request_model)


class _BrokenSecretExecutor:
    def create_reply(self, scheduled, user_text, instructions):  # noqa: ANN001, ARG002
        raise RuntimeError("upstream failed with Bearer hf_TESTSECRET123")


class _BrokenUnavailableSecretExecutor:
    def create_reply(self, scheduled, user_text, instructions):  # noqa: ANN001, ARG002
        raise HFPoolUnavailable("upstream unavailable with Bearer hf_TESTSECRET123")


def _enabled_config(tmp_path):
    path = tmp_path / "hf_pool.yaml"
    path.write_text(
        json.dumps(
            {
                "pools": {
                    "default": {
                        "enabled": True,
                        "targets": [
                            {
                                "name": "mock_target",
                                "api_key_env": "HF_TOKEN_MAIN",
                                "model": "Qwen/Qwen3-4B-Instruct-2507",
                                "purposes": ["normal_chat"],
                            }
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def _two_target_config(tmp_path):
    path = tmp_path / "hf_pool.yaml"
    path.write_text(
        json.dumps(
            {
                "pools": {
                    "default": {
                        "enabled": True,
                        "targets": [
                            {
                                "name": "high_target",
                                "api_key_env": "HF_TOKEN_MAIN",
                                "model": "high-model",
                                "weight": 10,
                                "purposes": ["normal_chat"],
                            },
                            {
                                "name": "low_target",
                                "api_key_env": "HF_TOKEN_MAIN",
                                "model": "low-model",
                                "weight": 1,
                                "purposes": ["normal_chat"],
                            },
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return path
