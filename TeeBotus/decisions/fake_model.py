from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Mapping


DecisionResponse = Any | Callable[[str, type[Any]], Any]


@dataclass
class FakeDecisionModel:
    responses: Mapping[str, DecisionResponse]
    calls: list[tuple[str, type[Any]]] = field(default_factory=list)

    def __call__(self, prompt: str, schema: type[Any]) -> Any:
        self.calls.append((str(prompt or ""), schema))
        schema_name = getattr(schema, "__name__", str(schema))
        if schema_name not in self.responses:
            raise KeyError(f"No fake decision response configured for {schema_name}")
        response = self.responses[schema_name]
        if callable(response):
            response = response(str(prompt or ""), schema)
        if isinstance(response, schema):
            return response
        if isinstance(response, str):
            try:
                return schema.model_validate_json(response)
            except AttributeError:
                response = json.loads(response)
        if hasattr(schema, "model_validate"):
            return schema.model_validate(response)
        return response

    def runner(self) -> Callable[[str, type[Any]], Any]:
        return self


def build_fake_model_runner(responses: Mapping[str, DecisionResponse]) -> Callable[[str, type[Any]], Any]:
    return FakeDecisionModel(responses).runner()
