from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class EmbeddingConfig:
    provider: str = "fake"
    model_name: str = "teebotus-fake-hash-embedding-v1"
    dimensions: int = 64
    endpoint: str = ""
    api_key_env: str = ""

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "EmbeddingConfig":
        source = data or {}
        return cls(
            provider=str(source.get("provider") or "fake").strip().casefold(),
            model_name=str(source.get("model_name") or source.get("model") or "teebotus-fake-hash-embedding-v1").strip(),
            dimensions=_positive_int(source.get("dimensions"), default=64),
            endpoint=str(source.get("endpoint") or "").strip(),
            api_key_env=str(source.get("api_key_env") or "").strip(),
        )


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, parsed)
