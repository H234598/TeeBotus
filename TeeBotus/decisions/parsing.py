from __future__ import annotations

import json
from typing import Any, TypeVar

DecisionT = TypeVar("DecisionT")


def _extract_json_payload(payload: str) -> Any:
    if not isinstance(payload, str):
        return payload
    text = payload.strip()
    if not text:
        raise json.JSONDecodeError("empty payload", "", 0)
    if text.startswith("{") and text.endswith("}"):
        return json.loads(text)
    if text.startswith("```") and text.endswith("```"):
        inner = text.strip("`").strip()
        if inner.startswith("json\n"):
            inner = inner[5:].strip()
        return json.loads(inner)
    start = text.find("{")
    if start == -1:
        raise json.JSONDecodeError("no json object found", text, 0)
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text[start:], start):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : index + 1])
    raise json.JSONDecodeError("unclosed json object", text, start)


def coerce_decision_payload(payload: object, schema: type[DecisionT]) -> DecisionT:
    """Validate model/test payloads through a concrete Pydantic decision schema."""
    if isinstance(payload, schema):
        return payload
    if isinstance(payload, str):
        payload = _extract_json_payload(payload)
    if hasattr(schema, "model_validate"):
        return schema.model_validate(payload)
    raise TypeError(f"Unsupported decision schema: {schema!r}")


__all__ = ["coerce_decision_payload"]
