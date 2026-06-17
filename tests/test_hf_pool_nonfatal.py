from __future__ import annotations

import json

import pytest

from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.hf_pool.errors import HFPoolUnavailable
from TeeBotus.llm.hf_pool.executor import HFPoolMockExecutor
from TeeBotus.llm.hf_pool.provider import HFPoolProvider


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


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.status = 200

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def close(self) -> None:
        return None


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
