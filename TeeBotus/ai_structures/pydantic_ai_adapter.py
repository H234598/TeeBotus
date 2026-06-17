from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Mapping

from TeeBotus.llm.hf_pool.config import DEFAULT_HF_POOL_CONFIG_PATH, load_hf_pool_config
from TeeBotus.llm.hf_pool.errors import HFPoolUnavailable
from TeeBotus.llm.hf_pool.redaction import redact_hf_secrets
from TeeBotus.llm.hf_pool.scheduler import select_target
from TeeBotus.llm.hf_pool.state import (
    HFPoolRuntimeState,
    SQLiteHFPoolRuntimeStateStore,
    default_hf_pool_state_path,
)
from TeeBotus.llm.profiles import normalize_llm_purpose


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
    hf_pool_config_path: str | Path = DEFAULT_HF_POOL_CONFIG_PATH,
    env: Mapping[str, str] | None = None,
    base_url: str = "",
) -> Callable[[str, type[Any]], Any]:
    """Build a structured-decision runner for the existing ModelRunner hook."""
    model_name = str(model or "").strip()
    if not model_name:
        raise ValueError("Pydantic-AI model name must not be empty")
    model_arg, metadata = _resolve_model_for_pydantic_ai(
        model_name,
        resolve_hf_pool=agent_factory is None,
        hf_pool_config_path=hf_pool_config_path,
        env=env,
        base_url=base_url,
    )
    resolved_factory = agent_factory or _load_agent_factory()

    def run(prompt: str, schema: type[Any]) -> Any:
        agent = _build_agent(
            resolved_factory,
            model_arg,
            schema=schema,
            system_prompt=system_prompt,
        )
        result = agent.run_sync(str(prompt or ""))
        return _extract_output(result)

    setattr(run, "model_name", model_name)
    for key, value in metadata.items():
        setattr(run, key, value)
    return run


def build_router_pydantic_ai_model_runner(
    purpose: str = "structured_decision",
    *,
    allow_remote_fallback: bool = False,
    system_prompt: str = "",
    agent_factory: Callable[..., Any] | None = None,
    route_selector: Callable[..., Any] | None = None,
    hf_pool_config_path: str | Path = DEFAULT_HF_POOL_CONFIG_PATH,
    env: Mapping[str, str] | None = None,
) -> Callable[[str, type[Any]], Any]:
    """Build a Pydantic-AI runner from TeeBotus' purpose router."""
    purpose_name = str(purpose or "structured_decision").strip() or "structured_decision"
    selector = route_selector or _load_route_selector()
    route = selector(purpose_name, allow_remote_fallback=allow_remote_fallback)
    model_name = str(getattr(route, "model", "") or "").strip()
    if not model_name:
        raise ValueError(f"LLM route for {purpose_name!r} did not resolve a model")
    fallback_used = False
    primary_error = ""
    try:
        runner = build_pydantic_ai_model_runner(
            model_name,
            system_prompt=system_prompt,
            agent_factory=agent_factory,
            hf_pool_config_path=hf_pool_config_path,
            env=env,
            base_url=str(getattr(route, "base_url", "") or ""),
        )
    except HFPoolUnavailable as exc:
        fallback_model = str(getattr(route, "fallback_model", "") or "").strip()
        if not fallback_model:
            raise
        primary_error = redact_hf_secrets(str(exc))
        runner = build_pydantic_ai_model_runner(
            fallback_model,
            system_prompt=system_prompt,
            agent_factory=agent_factory,
            hf_pool_config_path=hf_pool_config_path,
            env=env,
            base_url=str(getattr(route, "fallback_base_url", "") or ""),
        )
        fallback_used = True
    setattr(runner, "llm_route", route)
    setattr(runner, "llm_purpose", getattr(route, "purpose", purpose_name))
    setattr(runner, "llm_provider", getattr(route, "provider", ""))
    setattr(runner, "model_name", model_name)
    setattr(runner, "llm_fallback_used", fallback_used)
    setattr(runner, "llm_fallback_profile", getattr(route, "fallback_profile_name", "") if fallback_used else "")
    setattr(runner, "llm_fallback_model", getattr(route, "fallback_model", "") if fallback_used else "")
    setattr(runner, "llm_primary_error", primary_error)
    return runner


def _load_agent_factory() -> Callable[..., Any]:
    try:
        from pydantic_ai import Agent  # type: ignore[import-not-found]
    except Exception as exc:
        raise PydanticAIUnavailableError("pydantic-ai is not installed; install TeeBotus with the [agents] extra") from exc
    return Agent


def _load_route_selector() -> Callable[..., Any]:
    from TeeBotus.llm.profiles import select_llm_route

    return select_llm_route


def _build_agent(agent_factory: Callable[..., Any], model: Any, *, schema: type[Any], system_prompt: str) -> Any:
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


def _resolve_model_for_pydantic_ai(
    model_name: str,
    *,
    resolve_hf_pool: bool,
    hf_pool_config_path: str | Path,
    env: Mapping[str, str] | None,
    base_url: str,
) -> tuple[Any, dict[str, Any]]:
    if not resolve_hf_pool or not _is_hf_pool_selector(model_name):
        if resolve_hf_pool and _is_ollama_selector(model_name):
            return _build_ollama_model(model_name, base_url=base_url)
        return model_name, {"pydantic_ai_model_name": model_name}
    return _build_hf_pool_openai_chat_model(model_name, config_path=hf_pool_config_path, env=env)


def _is_hf_pool_selector(model_name: str) -> bool:
    return str(model_name or "").strip().startswith("pool:")


def _is_ollama_selector(model_name: str) -> bool:
    value = str(model_name or "").strip().casefold()
    return value.startswith(("ollama_chat/", "ollama/"))


def _build_hf_pool_openai_chat_model(
    model_selector: str,
    *,
    config_path: str | Path,
    env: Mapping[str, str] | None,
) -> tuple[Any, dict[str, Any]]:
    try:
        from pydantic_ai.models.openai import OpenAIChatModel  # type: ignore[import-not-found]
        from pydantic_ai.providers.openai import OpenAIProvider  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - depends on optional extra.
        raise PydanticAIUnavailableError("pydantic-ai OpenAI-compatible provider is not installed; install TeeBotus with the [agents] extra") from exc
    selector = _parse_hf_pool_selector(model_selector)
    config = load_hf_pool_config(config_path)
    runtime_state = _hf_pool_runtime_state(env)
    scheduled = select_target(
        config,
        pool_name=selector["pool_name"],
        purpose=selector["purpose"],
        env=env,
        state=runtime_state,
    )
    provider = OpenAIProvider(
        base_url=_openai_compatible_base_url(scheduled.target.base_url),
        api_key=scheduled.api_key,
    )
    model = OpenAIChatModel(scheduled.target.request_model, provider=provider)
    return model, {
        "pydantic_ai_model_name": scheduled.target.request_model,
        "hf_pool_name": scheduled.pool.name,
        "hf_pool_target": scheduled.target.name,
        "hf_pool_request_model": scheduled.target.request_model,
        "hf_pool_base_url": _openai_compatible_base_url(scheduled.target.base_url),
        "hf_pool_state_loaded": runtime_state is not None,
    }


def _parse_hf_pool_selector(model_selector: str) -> dict[str, str]:
    text = str(model_selector or "").strip()
    pool_text, _, purpose_text = text.partition("#")
    pool_name = pool_text.removeprefix("pool:").strip() or "default"
    purpose = normalize_llm_purpose(purpose_text) if purpose_text.strip() else "normal_chat"
    return {"pool_name": pool_name, "purpose": purpose}


def _openai_compatible_base_url(base_url: str) -> str:
    text = str(base_url or "https://router.huggingface.co/v1").strip().rstrip("/")
    suffix = "/chat/completions"
    if text.endswith(suffix):
        text = text[: -len(suffix)]
    return text or "https://router.huggingface.co/v1"


def _hf_pool_runtime_state(env: Mapping[str, str] | None) -> HFPoolRuntimeState | None:
    source = os.environ if env is None else env
    state_db = str(source.get("TEEBOTUS_HF_POOL_STATE_DB", "") or "").strip()
    state_path = Path(state_db).expanduser() if state_db else default_hf_pool_state_path()
    if not state_path.exists():
        return None
    try:
        state = SQLiteHFPoolRuntimeStateStore(state_path).load()
    except Exception:  # noqa: BLE001 - corrupt state must not block structured fallback routing.
        return None
    return state if isinstance(state, HFPoolRuntimeState) else None


def _build_ollama_model(model_selector: str, *, base_url: str) -> tuple[Any, dict[str, Any]]:
    try:
        from pydantic_ai.models.ollama import OllamaModel  # type: ignore[import-not-found]
        from pydantic_ai.providers.ollama import OllamaProvider  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - depends on optional extra.
        raise PydanticAIUnavailableError("pydantic-ai Ollama provider is not installed; install TeeBotus with the [agents] extra") from exc
    model_name = _strip_ollama_selector(model_selector)
    resolved_base_url = _ollama_openai_base_url(base_url)
    provider = OllamaProvider(base_url=resolved_base_url)
    return OllamaModel(model_name, provider=provider), {
        "pydantic_ai_model_name": model_name,
        "pydantic_ai_provider": "ollama",
        "pydantic_ai_base_url": resolved_base_url,
    }


def _strip_ollama_selector(model_selector: str) -> str:
    text = str(model_selector or "").strip()
    for prefix in ("ollama_chat/", "ollama/"):
        if text.casefold().startswith(prefix):
            return text[len(prefix) :].strip()
    return text


def _ollama_openai_base_url(base_url: str) -> str:
    text = str(base_url or "http://127.0.0.1:11434").strip().rstrip("/")
    if text.endswith("/v1"):
        return text
    return f"{text}/v1"


__all__ = [
    "PydanticAIUnavailableError",
    "build_pydantic_ai_model_runner",
    "build_router_pydantic_ai_model_runner",
    "pydantic_ai_available",
]
