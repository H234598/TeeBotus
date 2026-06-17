from __future__ import annotations

import json

import pytest

from TeeBotus.llm.hf_pool.errors import HFPoolConfigError
from TeeBotus.llm.hf_pool.config import DEFAULT_HF_POOL_CONFIG_PATH, load_hf_pool_config


def test_hf_pool_config_missing_is_nonfatal(tmp_path):
    config = load_hf_pool_config(tmp_path / "missing-hf-pool.yaml")

    assert config.exists is False
    assert config.pools == {}
    assert "missing" in config.error


def test_hf_pool_config_malformed_is_nonfatal_by_default(tmp_path):
    path = tmp_path / "hf_pool.yaml"
    path.write_text("[]", encoding="utf-8")

    config = load_hf_pool_config(path)

    assert config.exists is True
    assert config.pools == {}
    assert "root must be a mapping" in config.error


def test_hf_pool_config_malformed_can_still_fail_strict(tmp_path):
    path = tmp_path / "hf_pool.yaml"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(HFPoolConfigError, match="root must be a mapping"):
        load_hf_pool_config(path, strict=True)


def test_hf_pool_config_parses_pool_and_targets(tmp_path):
    path = tmp_path / "hf_pool.yaml"
    path.write_text(
        json.dumps(
            {
                "pools": {
                    "default": {
                        "enabled": True,
                        "strategy": "purpose_weighted",
                        "targets": [
                            {
                                "name": "qwen_structured",
                                "kind": "hf_router_chat",
                                "base_url": "https://router.huggingface.co/v1",
                                "api_key_env": "HF_TOKEN_MAIN",
                                "model": "Qwen/Qwen3-4B-Instruct-2507",
                                "weight": 5,
                                "purposes": ["structured_decision"],
                                "required": {"supports_structured_output": True},
                            }
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_hf_pool_config(path)
    pool = config.pool("default")

    assert pool is not None
    assert pool.enabled is True
    assert pool.targets[0].name == "qwen_structured"
    assert pool.targets[0].api_key_env == "HF_TOKEN_MAIN"
    assert pool.targets[0].capabilities.supports_structured_output is True


def test_hf_pool_config_allows_zero_max_retries(tmp_path):
    path = tmp_path / "hf_pool.yaml"
    path.write_text(
        json.dumps(
            {
                "pools": {
                    "default": {
                        "enabled": True,
                        "max_retries": 0,
                        "targets": [
                            {
                                "name": "qwen",
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

    config = load_hf_pool_config(path)
    pool = config.pool("default")

    assert pool is not None
    assert pool.max_retries == 0


def test_repository_hf_pool_config_declares_plan3_model_buckets_disabled_by_default() -> None:
    config = load_hf_pool_config(DEFAULT_HF_POOL_CONFIG_PATH)
    pool = config.pool("default")

    assert pool is not None
    assert pool.enabled is False
    purposes = {purpose for target in pool.targets for purpose in target.purposes}
    assert {
        "normal_chat",
        "structured_decision",
        "psychology_explainer",
        "bibliothekar_answer",
        "summarizer",
    }.issubset(purposes)
    assert all(target.enabled is False for target in pool.targets)
    assert all(target.base_url == "https://router.huggingface.co/v1" for target in pool.targets)
