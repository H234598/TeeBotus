from __future__ import annotations

from TeeBotus.ai_structures.schemas import MemoryCandidate
from TeeBotus.decisions.parsing import coerce_decision_payload


def parse_memory_candidate(payload: object) -> MemoryCandidate:
    return coerce_decision_payload(payload, MemoryCandidate)

__all__ = ["MemoryCandidate", "parse_memory_candidate"]
