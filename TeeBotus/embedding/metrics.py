from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EmbeddingUsageEvent:
    provider: str
    model: str
    purpose: str
    status: str
    texts: int
    latency_ms: int | None = None
