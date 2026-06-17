from __future__ import annotations

import json
from typing import Any, TypeVar

DecisionT = TypeVar("DecisionT")


def coerce_decision_payload(payload: object, schema: type[DecisionT]) -> DecisionT:
    """Validate model/test payloads through a concrete Pydantic decision schema."""
    if isinstance(payload, schema):
        return payload
    if isinstance(payload, str):
        payload = json.loads(payload)
    if hasattr(schema, "model_validate"):
        return schema.model_validate(payload)
    raise TypeError(f"Unsupported decision schema: {schema!r}")


__all__ = ["coerce_decision_payload"]
