from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TargetCapabilities:
    supports_tools: bool = False
    supports_structured_output: bool = False
    context_length: int | None = None


@dataclass(frozen=True)
class HFPoolTarget:
    name: str
    kind: str
    base_url: str
    api_key_env: str
    model: str
    routed_model: str = ""
    weight: int = 1
    purposes: tuple[str, ...] = ()
    enabled: bool = True
    required: dict[str, Any] = field(default_factory=dict)
    capabilities: TargetCapabilities = field(default_factory=TargetCapabilities)

    @property
    def request_model(self) -> str:
        return self.routed_model or self.model

    def supports_purpose(self, purpose: str) -> bool:
        normalized = _normalize_purpose(purpose)
        return not self.purposes or normalized in {_normalize_purpose(item) for item in self.purposes}


def _normalize_purpose(value: object) -> str:
    return str(value or "").strip().casefold().replace("-", "_").replace(" ", "_") or "normal_chat"
