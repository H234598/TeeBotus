from __future__ import annotations

from TeeBotus.ai_structures.schemas import YouTubeOptionsDecision
from TeeBotus.decisions.parsing import coerce_decision_payload


def parse_youtube_options_decision(payload: object) -> YouTubeOptionsDecision:
    return coerce_decision_payload(payload, YouTubeOptionsDecision)


__all__ = ["YouTubeOptionsDecision", "parse_youtube_options_decision"]
