from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HFPoolModelInfo:
    model: str
    context_length: int | None = None
    supports_tools: bool = False
    supports_structured_output: bool = False
