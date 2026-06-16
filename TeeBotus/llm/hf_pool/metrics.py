from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class HFPoolUsageEvent:
    pool: str
    target: str
    model: str
    status: str
    latency_ms: int | None = None
    usage: dict[str, Any] = field(default_factory=dict)
