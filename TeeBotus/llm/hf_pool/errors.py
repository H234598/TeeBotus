from __future__ import annotations

from TeeBotus.llm.base import LLMAPIError


class HFPoolError(LLMAPIError):
    """Base error for the optional Hugging Face pool provider."""


class HFPoolConfigError(HFPoolError):
    """Raised when hf_pool configuration is present but unusable in strict mode."""


class HFPoolUnavailable(HFPoolError):
    """Raised when hf_pool is requested but no configured target can be used."""


class HFPoolTargetUnavailable(HFPoolUnavailable):
    """Raised when a selected hf_pool target cannot be used."""


class HFPoolRateLimited(HFPoolTargetUnavailable):
    """Raised when a target is in cooldown due to rate limits."""
