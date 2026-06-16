from __future__ import annotations

from pathlib import Path
from typing import Mapping

from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.base import LLMResponse
from TeeBotus.llm.capabilities import LITELLM_TEXT_CAPABILITIES
from TeeBotus.llm.hf_pool.config import DEFAULT_HF_POOL_CONFIG_PATH, load_hf_pool_config
from TeeBotus.llm.hf_pool.errors import HFPoolUnavailable
from TeeBotus.llm.hf_pool.executor import HFPoolExecutor, HFPoolMockExecutor
from TeeBotus.llm.hf_pool.scheduler import select_target
from TeeBotus.llm.profiles import normalize_llm_purpose


class HFPoolProvider:
    provider_name = "hf_pool"
    capabilities = LITELLM_TEXT_CAPABILITIES

    def __init__(
        self,
        *,
        pool_name: str = "default",
        purpose: str = "normal_chat",
        config_path: str | Path = DEFAULT_HF_POOL_CONFIG_PATH,
        env: Mapping[str, str] | None = None,
        executor: HFPoolExecutor | None = None,
        fallback_client: object | None = None,
    ) -> None:
        self.pool_name = _normalize_pool_name(pool_name)
        self.purpose = normalize_llm_purpose(purpose)
        self.config_path = Path(config_path)
        self.env = env
        self.executor = executor or HFPoolMockExecutor()
        self.fallback_client = fallback_client

    def create_reply(
        self,
        user_text: str,
        instructions: BotInstructions,
        previous_response_id: str | None = None,
    ) -> LLMResponse:
        try:
            config = load_hf_pool_config(self.config_path)
            scheduled = select_target(config, pool_name=self.pool_name, purpose=self.purpose, env=self.env)
            return self.executor.create_reply(scheduled, user_text, instructions)
        except HFPoolUnavailable as exc:
            return self._fallback_or_raise(user_text, instructions, previous_response_id, exc)
        except Exception as exc:  # noqa: BLE001 - provider boundary normalizes executor failures.
            return self._fallback_or_raise(user_text, instructions, previous_response_id, HFPoolUnavailable(f"hf_pool target failed: {type(exc).__name__}: {exc}"))

    def _fallback_or_raise(
        self,
        user_text: str,
        instructions: BotInstructions,
        previous_response_id: str | None,
        exc: HFPoolUnavailable,
    ) -> LLMResponse:
        if self.fallback_client is None:
            raise exc
        create_reply = getattr(self.fallback_client, "create_reply", None)
        if not callable(create_reply):
            raise exc
        response = create_reply(user_text, instructions, previous_response_id)
        if isinstance(response, LLMResponse):
            return response
        return LLMResponse(
            text=str(getattr(response, "text", "") or response),
            response_id=getattr(response, "response_id", None),
            provider=str(getattr(response, "provider", "") or "fallback"),
            model=str(getattr(response, "model", "") or ""),
            usage=dict(getattr(response, "usage", {}) or {}),
        )


def _normalize_pool_name(value: object) -> str:
    text = str(value or "").strip()
    if text.startswith("pool:"):
        text = text.split(":", maxsplit=1)[1]
    return text or "default"
