from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class HFPoolRuntimeState:
    cooldowns: dict[str, str] = field(default_factory=dict)
    failures: dict[str, int] = field(default_factory=dict)
    successes: dict[str, int] = field(default_factory=dict)
