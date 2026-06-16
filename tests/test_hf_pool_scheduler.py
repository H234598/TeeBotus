from __future__ import annotations

import pytest

from TeeBotus.llm.hf_pool.config import HFPool, HFPoolConfig
from TeeBotus.llm.hf_pool.errors import HFPoolUnavailable
from TeeBotus.llm.hf_pool.scheduler import select_target
from TeeBotus.llm.hf_pool.targets import HFPoolTarget


def test_hf_pool_scheduler_selects_enabled_target_by_purpose_and_weight(tmp_path) -> None:
    config = HFPoolConfig(
        path=tmp_path / "hf_pool.yaml",
        pools={
            "default": HFPool(
                name="default",
                enabled=True,
                targets=(
                    HFPoolTarget(
                        name="chat_low",
                        kind="hf_router_chat",
                        base_url="https://router.huggingface.co/v1",
                        api_key_env="HF_TOKEN_MAIN",
                        model="chat-low",
                        weight=1,
                        purposes=("normal_chat",),
                    ),
                    HFPoolTarget(
                        name="structured_high",
                        kind="hf_router_chat",
                        base_url="https://router.huggingface.co/v1",
                        api_key_env="HF_TOKEN_MAIN",
                        model="structured-high",
                        weight=5,
                        purposes=("structured_decision",),
                    ),
                ),
            )
        },
    )

    scheduled = select_target(config, purpose="structured-decision", env={"HF_TOKEN_MAIN": "hf_fake_token"})

    assert scheduled.target.name == "structured_high"
    assert scheduled.target.request_model == "structured-high"
    assert scheduled.api_key == "hf_fake_token"


def test_hf_pool_scheduler_treats_missing_target_keys_as_unavailable(tmp_path) -> None:
    config = HFPoolConfig(
        path=tmp_path / "hf_pool.yaml",
        pools={
            "default": HFPool(
                name="default",
                enabled=True,
                targets=(
                    HFPoolTarget(
                        name="chat",
                        kind="hf_router_chat",
                        base_url="https://router.huggingface.co/v1",
                        api_key_env="HF_TOKEN_MAIN",
                        model="chat",
                        purposes=("normal_chat",),
                    ),
                ),
            )
        },
    )

    with pytest.raises(HFPoolUnavailable, match="configured API key"):
        select_target(config, purpose="normal_chat", env={"HF_TOKEN_MAIN": ""})
