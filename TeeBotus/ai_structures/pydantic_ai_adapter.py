from __future__ import annotations

from typing import Any, Callable


class PydanticAIUnavailableError(RuntimeError):
    pass


def pydantic_ai_available() -> bool:
    try:
        import pydantic_ai  # noqa: F401
    except Exception:
        return False
    return True


def build_pydantic_ai_model_runner(
    model: str,
    *,
    system_prompt: str = "",
    agent_factory: Callable[..., Any] | None = None,
) -> Callable[[str, type[Any]], Any]:
    """Build a structured-decision runner for the existing ModelRunner hook."""
    model_name = str(model or "").strip()
    if not model_name:
        raise ValueError("Pydantic-AI model name must not be empty")
    resolved_factory = agent_factory or _load_agent_factory()

    def run(prompt: str, schema: type[Any]) -> Any:
        agent = _build_agent(
            resolved_factory,
            model_name,
            schema=schema,
            system_prompt=system_prompt,
        )
        result = agent.run_sync(str(prompt or ""))
        return _extract_output(result)

    return run


def _load_agent_factory() -> Callable[..., Any]:
    try:
        from pydantic_ai import Agent  # type: ignore[import-not-found]
    except Exception as exc:
        raise PydanticAIUnavailableError("pydantic-ai is not installed; install TeeBotus with the [agents] extra") from exc
    return Agent


def _build_agent(agent_factory: Callable[..., Any], model: str, *, schema: type[Any], system_prompt: str) -> Any:
    kwargs: dict[str, Any] = {"output_type": schema}
    if system_prompt:
        kwargs["system_prompt"] = system_prompt
    try:
        return agent_factory(model, **kwargs)
    except TypeError:
        # Older Pydantic-AI releases used result_type. Keeping the fallback here
        # makes the optional adapter tolerant without weakening schema validation.
        kwargs.pop("output_type", None)
        kwargs["result_type"] = schema
        return agent_factory(model, **kwargs)


def _extract_output(result: Any) -> Any:
    if hasattr(result, "output"):
        return result.output
    if hasattr(result, "data"):
        return result.data
    return result


__all__ = [
    "PydanticAIUnavailableError",
    "build_pydantic_ai_model_runner",
    "pydantic_ai_available",
]
