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


def test_hf_pool_provider_uses_mock_executor_for_configured_target(tmp_path):
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
    provider = HFPoolProvider(config_path=path, env={"HF_TOKEN_MAIN": "hf-secret"}, executor=HFPoolMockExecutor("mock ok"))

    response = provider.create_reply("ping", BotInstructions())

    assert response.text == "mock ok"
    assert response.provider == "hf_pool"
    assert response.model == "Qwen/Qwen3-4B-Instruct-2507"
