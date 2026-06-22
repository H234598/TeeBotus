from __future__ import annotations

import json
import os
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from pydantic_ai import exceptions as _pydantic_ai_exceptions

from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.hf_pool.config import DEFAULT_HF_POOL_CONFIG_PATH, load_hf_pool_config
from TeeBotus.llm.hf_pool.errors import HFPoolUnavailable
from TeeBotus.llm.hf_pool.redaction import redact_hf_secrets
from TeeBotus.llm.hf_pool.scheduler import select_target
from TeeBotus.llm.hf_pool.state import (
    HFPoolRuntimeState,
    SQLiteHFPoolRuntimeStateStore,
    default_hf_pool_state_path,
)
from TeeBotus.llm.profiles import LLMProfile, load_llm_profiles, normalize_llm_purpose
from TeeBotus.llm_client import build_text_llm_client, normalize_llm_provider
from TeeBotus.runtime.log_context import current_log_context, logging_context, next_llm_call_id


LOGGER = logging.getLogger("TeeBotus.ai_structures.pydantic_ai_adapter")


class PydanticAIUnavailableError(RuntimeError):
    pass


@dataclass
class _LiteLLMStructuredModel:
    client: Any
    model_name: str
    provider: str
    api_base: str = ""

    def run(self, prompt: str, schema: type[Any], *, system_prompt: str = "", output_retries: int | None = None) -> Any:
        attempts = max(1, int(output_retries or 0) + 1)
        last_error = ""
        for _attempt in range(attempts):
            instructions = BotInstructions(
                openai_system_prompt=_structured_system_prompt(schema, system_prompt=system_prompt, last_error=last_error)
            )
            response = self.client.create_reply(_structured_user_prompt(prompt, last_error=last_error), instructions, None)
            try:
                return _validate_structured_response(schema, str(getattr(response, "text", "") or response))
            except Exception as exc:  # noqa: BLE001 - repair prompt on schema errors.
                last_error = f"{type(exc).__name__}: {exc}"
        raise ValueError(f"LiteLLM structured response did not match schema after {attempts} attempts: {last_error}")


TEEBOTUS_STRUCTURED_DECISION_MAX_OUTPUT_RETRIES = "TEEBOTUS_STRUCTURED_DECISION_MAX_OUTPUT_RETRIES"
TEEBOTUS_STRUCTURED_DECISION_MAX_OUTPUT_RETRIES_DEFAULT = 2
TEEBOTUS_LLM_OFFLOAD_LOCAL_OLLAMA = "TEEBOTUS_LLM_OFFLOAD_LOCAL_OLLAMA"
TEEBOTUS_LLM_OFFLOAD_LOCAL_OLLAMA_PROFILE = "TEEBOTUS_LLM_OFFLOAD_LOCAL_OLLAMA_PROFILE"
TEEBOTUS_LLM_OFFLOAD_LOCAL_OLLAMA_DEFAULT_PROFILE = "openai_premium"


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
    output_retries: int | None = None,
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
        result_prompt = str(prompt or "")
        schema_name = str(getattr(schema, "__name__", schema))
        call_id = next_llm_call_id("pydantic_ai")
        with logging_context(
            component="pydantic_ai",
            operation="structured_decision",
            llm_call_id=call_id,
            provider=str(metadata.get("pydantic_ai_provider") or metadata.get("llm_provider") or ""),
            model=str(metadata.get("pydantic_ai_model_name") or model_name),
            api_base=str(metadata.get("pydantic_ai_base_url") or metadata.get("hf_pool_base_url") or ""),
            schema=schema_name,
        ):
            started_at = time.perf_counter()
            LOGGER.info(
                "Pydantic-AI structured decision started call_id=%s schema=%s model=%s output_retries=%s prompt_chars=%s",
                call_id,
                schema_name,
                model_name,
                output_retries,
                len(result_prompt),
            )
            if isinstance(model_arg, _LiteLLMStructuredModel):
                output = model_arg.run(result_prompt, schema, system_prompt=system_prompt, output_retries=output_retries)
                LOGGER.info(
                    "LiteLLM structured decision finished call_id=%s schema=%s elapsed_ms=%s output_type=%s",
                    call_id,
                    schema_name,
                    int((time.perf_counter() - started_at) * 1000),
                    type(output).__name__,
                )
                return output
            agent = _build_agent(
                resolved_factory,
                model_arg,
                schema=schema,
                system_prompt=system_prompt,
                output_retries=output_retries,
            )
            try:
                result = _run_agent_sync(agent, result_prompt, output_retries=output_retries)
                output = _extract_output(result)
                LOGGER.info(
                    "Pydantic-AI structured decision finished call_id=%s schema=%s elapsed_ms=%s output_type=%s",
                    call_id,
                    schema_name,
                    int((time.perf_counter() - started_at) * 1000),
                    type(output).__name__,
                )
                return output
            except _pydantic_ai_exceptions.UnexpectedModelBehavior:
                LOGGER.warning(
                    "Pydantic-AI structured decision schema retry failed call_id=%s schema=%s; retrying as raw string.",
                    call_id,
                    schema_name,
                )
                raw_agent = _build_agent(
                    resolved_factory,
                    model_arg,
                    schema=str,
                    system_prompt=system_prompt,
                    output_retries=None,
                )
                result = _run_agent_sync(raw_agent, result_prompt, output_retries=output_retries)
                output = _extract_output(result)
                LOGGER.info(
                    "Pydantic-AI raw fallback finished call_id=%s schema=%s elapsed_ms=%s output_type=%s",
                    call_id,
                    schema_name,
                    int((time.perf_counter() - started_at) * 1000),
                    type(output).__name__,
                )
                return output

    setattr(run, "model_name", model_name)
    setattr(run, "pydantic_ai_output_retries", output_retries)
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
    source = os.environ if env is None else env
    output_retries = _parse_optional_nonnegative_int(
        source.get(TEEBOTUS_STRUCTURED_DECISION_MAX_OUTPUT_RETRIES, ""),
        default=TEEBOTUS_STRUCTURED_DECISION_MAX_OUTPUT_RETRIES_DEFAULT,
    )
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
            output_retries=output_retries,
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
            output_retries=output_retries,
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


def _build_agent(
    agent_factory: Callable[..., Any], model: Any, *, schema: type[Any], system_prompt: str, output_retries: int | None = None
) -> Any:
    base_kwargs: dict[str, Any] = {}
    if system_prompt:
        base_kwargs["system_prompt"] = system_prompt

    retry_variants: list[dict[str, Any]] = [{}]
    if output_retries is not None:
        retry_variants = [
            {"retries": {"output": output_retries}},
            {"output_retries": output_retries},
        ]

    schema_variants = (
        {"output_type": schema},
        {"result_type": schema},
    )
    last_error: Exception | None = None
    for schema_kwargs in schema_variants:
        for retry_kwargs in retry_variants:
            kwargs = dict(base_kwargs)
            kwargs.update(schema_kwargs)
            kwargs.update(retry_kwargs)
            try:
                return agent_factory(model, **kwargs)
            except TypeError as exc:
                last_error = exc
                continue
    if last_error is not None:
        raise last_error
    raise TypeError("unable to build pydantic-ai Agent with available compatibility arguments")


def _run_agent_sync(agent: Any, prompt: str, *, output_retries: int | None = None) -> Any:
    if output_retries is None:
        return agent.run_sync(prompt)
    try:
        return agent.run_sync(prompt, retries=output_retries)
    except TypeError as exc:
        if "unexpected keyword argument 'retries'" not in str(exc):
            raise
    return agent.run_sync(prompt)


def _parse_optional_nonnegative_int(value: object, default: int | None = None) -> int | None:
    text = str(value or "").strip()
    if not text:
        return default
    try:
        parsed = int(text)
    except ValueError:
        return default
    return max(0, parsed)


def _extract_output(result: Any) -> Any:
    if hasattr(result, "output"):
        return result.output
    if hasattr(result, "data"):
        return result.data
    return result


def _structured_system_prompt(schema: type[Any], *, system_prompt: str, last_error: str) -> str:
    schema_name = str(getattr(schema, "__name__", schema))
    parts = [str(system_prompt or "").strip()]
    parts.append(
        "Return only valid JSON. The JSON must validate against the requested output schema "
        f"{schema_name}. Do not include markdown fences, prose, or comments."
    )
    schema_json = _schema_json(schema)
    if schema_json:
        parts.append(f"JSON schema: {schema_json}")
    if last_error:
        parts.append(f"Previous output was invalid: {last_error}")
    return "\n\n".join(part for part in parts if part)


def _structured_user_prompt(prompt: str, *, last_error: str) -> str:
    text = str(prompt or "")
    if not last_error:
        return text
    return f"{text}\n\nReturn corrected JSON only."


def _schema_json(schema: type[Any]) -> str:
    try:
        if hasattr(schema, "model_json_schema"):
            payload = schema.model_json_schema()  # type: ignore[attr-defined]
        elif hasattr(schema, "schema"):
            payload = schema.schema()  # type: ignore[attr-defined]
        else:
            return ""
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)
    except Exception:
        return ""


def _validate_structured_response(schema: type[Any], text: str) -> Any:
    if schema is str:
        return text
    payload = json.loads(_extract_json_text(text))
    if hasattr(schema, "model_validate"):
        return schema.model_validate(payload)  # type: ignore[attr-defined]
    return schema(**payload)


def _extract_json_text(text: str) -> str:
    stripped = str(text or "").strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    if stripped.startswith(("{", "[")):
        return stripped
    starts = [idx for idx in (stripped.find("{"), stripped.find("[")) if idx >= 0]
    if not starts:
        raise ValueError("no JSON object or array found")
    start = min(starts)
    end = max(stripped.rfind("}"), stripped.rfind("]"))
    if end < start:
        raise ValueError("unterminated JSON payload")
    return stripped[start : end + 1]


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
            if _local_ollama_offload_enabled(env):
                return _build_offloaded_pydantic_ai_model(env=env)
            return _build_litellm_structured_model(
                provider="ollama",
                model=_strip_ollama_selector(model_name),
                api_base=_ollama_litellm_base_url(base_url),
            )
        return model_name, {"pydantic_ai_model_name": model_name}
    return _build_hf_pool_litellm_structured_model(model_name, config_path=hf_pool_config_path, env=env)


def _is_hf_pool_selector(model_name: str) -> bool:
    return str(model_name or "").strip().startswith("pool:")


def _is_ollama_selector(model_name: str) -> bool:
    value = str(model_name or "").strip().casefold()
    return value.startswith(("ollama_chat/", "ollama/"))


def _build_hf_pool_litellm_structured_model(
    model_selector: str,
    *,
    config_path: str | Path,
    env: Mapping[str, str] | None,
) -> tuple[Any, dict[str, Any]]:
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
    model, metadata = _build_litellm_structured_model(
        provider=_hf_target_litellm_provider(scheduled.target.kind),
        model=scheduled.target.request_model,
        api_key=scheduled.api_key,
        api_base=_openai_compatible_base_url(scheduled.target.base_url),
    )
    metadata.update(
        {
        "hf_pool_name": scheduled.pool.name,
        "hf_pool_target": scheduled.target.name,
        "hf_pool_request_model": scheduled.target.request_model,
        "hf_pool_base_url": _openai_compatible_base_url(scheduled.target.base_url),
        "hf_pool_state_loaded": runtime_state is not None,
        }
    )
    return model, metadata


def _build_offloaded_pydantic_ai_model(*, env: Mapping[str, str] | None) -> tuple[Any, dict[str, Any]]:
    source = os.environ if env is None else env
    profile_name = _offload_profile_name(source)
    profiles = load_llm_profiles()
    profile = profiles.get(profile_name)
    if profile is None:
        raise PydanticAIUnavailableError(f"local Ollama offload profile not found: {profile_name}")
    provider = normalize_llm_provider(profile.provider)
    model_name = str(profile.model or "").strip()
    if provider in {
        "openai",
        "litellm",
        "huggingface",
        "hf",
        "groq",
        "gemini",
        "vertex_ai",
        "litellm_gemini_stateless",
        "litellm_gemini_stateful",
        "litellm_gemini_paid_stateless",
        "litellm_gemini_paid_stateful",
    }:
        return _build_litellm_profile_model(profile, env=source)
    if provider == "hf_pool" or model_name.startswith("pool:"):
        return _build_hf_pool_litellm_structured_model(model_name, config_path=DEFAULT_HF_POOL_CONFIG_PATH, env=source)
    raise PydanticAIUnavailableError(f"local Ollama offload profile is not supported for pydantic-ai: {profile_name}")


def _build_litellm_profile_model(profile: LLMProfile, *, env: Mapping[str, str]) -> tuple[Any, dict[str, Any]]:
    api_key = _profile_api_key(profile, env)
    provider = normalize_llm_provider(profile.provider)
    if provider == "openai":
        provider = "litellm"
    model, metadata = _build_litellm_structured_model(
        provider=provider,
        model=profile.model,
        api_key=api_key,
        api_base=_openai_compatible_base_url(profile.base_url) if profile.base_url else "",
    )
    metadata.update({
        "pydantic_ai_offload_profile": profile.name,
    })
    return model, metadata


def _build_litellm_structured_model(
    *,
    provider: str,
    model: str,
    api_key: str = "",
    api_base: str = "",
) -> tuple[_LiteLLMStructuredModel, dict[str, Any]]:
    normalized_provider = normalize_llm_provider(provider)
    resolved_model = _litellm_structured_model_name(normalized_provider, model)
    client = build_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        provider=normalized_provider,
        model=resolved_model,
        api_key=api_key,
        api_base=api_base,
        use_instruction_fallback_models=False,
    )
    if client is None:
        raise PydanticAIUnavailableError(f"LiteLLM structured model could not be built: provider={provider} model={model}")
    actual_model = str(getattr(client, "model", "") or resolved_model)
    actual_provider = str(getattr(client, "provider", "") or normalized_provider)
    return _LiteLLMStructuredModel(client=client, model_name=actual_model, provider=actual_provider, api_base=api_base), {
        "pydantic_ai_model_name": actual_model,
        "pydantic_ai_provider": "litellm",
        "pydantic_ai_base_url": api_base,
        "litellm_provider": actual_provider,
        "litellm_model": actual_model,
    }


def _litellm_structured_model_name(provider: str, model: str) -> str:
    value = str(model or "").strip()
    if not value:
        return value
    if provider == "litellm":
        if value.startswith("openai/") or "/" in value:
            return value
        return f"openai/{value}"
    prefixes = {
        "openai": "openai/",
        "huggingface": "huggingface/",
        "hf": "huggingface/",
        "groq": "groq/",
        "gemini": "gemini/",
        "litellm_gemini_stateless": "gemini/",
        "litellm_gemini_stateful": "gemini/",
        "litellm_gemini_paid_stateless": "gemini/",
        "litellm_gemini_paid_stateful": "gemini/",
        "vertex_ai": "vertex_ai/",
        "ollama": "ollama/",
    }
    prefix = prefixes.get(provider, "")
    return value if not prefix or value.startswith(prefix) else f"{prefix}{value}"


def _hf_target_litellm_provider(kind: object) -> str:
    normalized = str(kind or "").strip().casefold().replace("-", "_")
    if normalized in {"openai_compatible", "openai_chat", "litellm"}:
        return "litellm"
    if normalized == "groq":
        return "groq"
    return "huggingface"


def _profile_api_key(profile: LLMProfile, env: Mapping[str, str]) -> str:
    env_name = str(profile.api_key_env or "").strip()
    if env_name:
        direct = str(env.get(env_name, "") or "").strip()
        if direct:
            return direct
        instance_token = _current_instance_env_token()
        if instance_token:
            instance_value = str(env.get(f"{env_name}_{instance_token}", "") or "").strip()
            if instance_value:
                return instance_value
    if str(profile.provider or "").strip().casefold() == "openai":
        instance_token = _current_instance_env_token()
        if instance_token:
            return str(env.get(f"OPENAI_API_KEY_{instance_token}", "") or "").strip()
    return ""


def _local_ollama_offload_enabled(env: Mapping[str, str] | None) -> bool:
    source = os.environ if env is None else env
    return _env_bool(_first_instance_env(source, TEEBOTUS_LLM_OFFLOAD_LOCAL_OLLAMA))


def _offload_profile_name(env: Mapping[str, str]) -> str:
    return _first_instance_env(env, TEEBOTUS_LLM_OFFLOAD_LOCAL_OLLAMA_PROFILE).strip() or TEEBOTUS_LLM_OFFLOAD_LOCAL_OLLAMA_DEFAULT_PROFILE


def _first_instance_env(env: Mapping[str, str], base_key: str) -> str:
    instance_token = _current_instance_env_token()
    if instance_token:
        value = str(env.get(f"{base_key}_{instance_token}", "") or "").strip()
        if value:
            return value
    return str(env.get(base_key, "") or "").strip()


def _env_bool(value: object) -> bool:
    return str(value or "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "ja",
        "on",
        "enabled",
        "an",
    }


def _current_instance_env_token() -> str:
    instance_name = str(current_log_context().get("instance", "") or "").strip()
    token = "".join(char if char.isalnum() else "_" for char in instance_name.upper())
    return "_".join(part for part in token.split("_") if part)


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
    if env is not None and not state_db:
        return None
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


def _ollama_litellm_base_url(base_url: str) -> str:
    text = str(base_url or "http://127.0.0.1:11434").strip().rstrip("/")
    if text.endswith("/v1"):
        text = text[: -len("/v1")]
    return text or "http://127.0.0.1:11434"


__all__ = [
    "PydanticAIUnavailableError",
    "build_pydantic_ai_model_runner",
    "build_router_pydantic_ai_model_runner",
    "pydantic_ai_available",
]
