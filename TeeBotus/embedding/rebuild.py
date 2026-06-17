from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from TeeBotus.embedding.config import EmbeddingConfig, build_account_memory_embedding_provider
from TeeBotus.instructions import BotInstructions, load_instructions
from TeeBotus.runtime.accounts import AccountStore, InstanceSecretProvider, validate_sha512_token
from TeeBotus.runtime.qdrant import (
    QDRANT_USER_MEMORY_COLLECTION,
    QdrantCollectionResult,
    QdrantCollectionSpec,
    default_qdrant_collection_specs,
    ensure_default_collections,
)
from TeeBotus.runtime.qdrant_memory import QdrantMemoryIndex


@dataclass(frozen=True)
class QdrantMemoryRebuildResult:
    instance_name: str
    account_id: str
    status: str
    point_count: int = 0
    point_ids: tuple[str, ...] = ()
    qdrant_url: str = ""
    embedding_provider: str = ""
    embedding_model: str = ""
    embedding_dimensions: int = 0
    error: str = ""


@dataclass(frozen=True)
class QdrantCollectionEnsureResult:
    instance_names: tuple[str, ...]
    collection_name: str
    status: str
    ok: bool
    qdrant_url: str = ""
    vector_size: int = 0
    embedding_model: str = ""
    error: str = ""


def rebuild_qdrant_memory_index(
    *,
    account_store: AccountStore,
    qdrant_index: QdrantMemoryIndex,
    instance_name: str,
    account_id: str,
    include_legacy_raw_account_id_cleanup: bool = False,
) -> tuple[str, ...]:
    return qdrant_index.rebuild(
        account_store=account_store,
        instance_name=instance_name,
        account_id=account_id,
        include_legacy_raw_account_id_cleanup=include_legacy_raw_account_id_cleanup,
    )


def rebuild_qdrant_memory_indexes(
    *,
    instances_dir: str | Path = "instances",
    instance_names: Iterable[str] = (),
    account_ids: Iterable[str] = (),
    qdrant_url: str | None = None,
    embedding_config: EmbeddingConfig | None = None,
    embedding_overrides: Mapping[str, Any] | None = None,
    dry_run: bool = False,
    include_legacy_raw_account_id_cleanup: bool = False,
    secret_provider: InstanceSecretProvider | None = None,
    qdrant_index_factory: Callable[..., QdrantMemoryIndex] = QdrantMemoryIndex,
) -> tuple[QdrantMemoryRebuildResult, ...]:
    root = Path(instances_dir)
    selected_instances = _resolve_instance_names(root, instance_names)
    requested_accounts = tuple(
        validate_sha512_token(str(account_id or "").strip().lower(), field_name="account_id")
        for account_id in account_ids
        if str(account_id or "").strip()
    )
    results: list[QdrantMemoryRebuildResult] = []
    for instance_name in selected_instances:
        instructions = _load_instance_memory_instructions(root, instance_name)
        effective_qdrant_url = qdrant_url or instructions.memory_search_qdrant_url
        effective_embedding_config = _resolve_memory_embedding_config(
            instructions,
            embedding_config=embedding_config,
            overrides=embedding_overrides,
        )
        store_kwargs: dict[str, Any] = {"create_dirs": False}
        if secret_provider is not None:
            store_kwargs["secret_provider"] = secret_provider
        store = AccountStore(root / instance_name / "data" / "accounts", instance_name, **store_kwargs)
        try:
            target_accounts = requested_accounts or store.list_account_ids()
        except Exception as exc:  # noqa: BLE001 - operator command should report every instance.
            results.append(
                _rebuild_result(
                    instance_name,
                    "",
                    "error",
                    qdrant_url=effective_qdrant_url,
                    embedding_config=effective_embedding_config,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            continue
        if not target_accounts:
            results.append(
                _rebuild_result(
                    instance_name,
                    "",
                    "skipped",
                    qdrant_url=effective_qdrant_url,
                    embedding_config=effective_embedding_config,
                    error="no accounts",
                )
            )
            continue
        for account_id in target_accounts:
            try:
                entries = store.read_memory_entries(account_id)
                if dry_run:
                    results.append(
                        _rebuild_result(
                            instance_name,
                            account_id,
                            "dry_run",
                            point_count=len(entries),
                            qdrant_url=effective_qdrant_url,
                            embedding_config=effective_embedding_config,
                        )
                    )
                    continue
                index = qdrant_index_factory(
                    url=effective_qdrant_url,
                    embedding_provider=build_account_memory_embedding_provider(effective_embedding_config),
                )
                point_ids = rebuild_qdrant_memory_index(
                    account_store=store,
                    qdrant_index=index,
                    instance_name=instance_name,
                    account_id=account_id,
                    include_legacy_raw_account_id_cleanup=include_legacy_raw_account_id_cleanup,
                )
                results.append(
                    _rebuild_result(
                        instance_name,
                        account_id,
                        "rebuilt",
                        point_count=len(point_ids),
                        point_ids=tuple(point_ids),
                        qdrant_url=effective_qdrant_url,
                        embedding_config=effective_embedding_config,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - keep rebuilding other accounts.
                results.append(
                    _rebuild_result(
                        instance_name,
                        account_id,
                        "error",
                        qdrant_url=effective_qdrant_url,
                        embedding_config=effective_embedding_config,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
    return tuple(results)


def ensure_qdrant_collections_for_instances(
    *,
    instances_dir: str | Path = "instances",
    instance_names: Iterable[str] = (),
    qdrant_url: str | None = None,
    embedding_config: EmbeddingConfig | None = None,
    embedding_overrides: Mapping[str, Any] | None = None,
    qdrant_ensure_factory: Callable[..., tuple[QdrantCollectionResult, ...]] = ensure_default_collections,
) -> tuple[QdrantCollectionEnsureResult, ...]:
    root = Path(instances_dir)
    selected_instances = _resolve_instruction_instance_names(root, instance_names)
    instructions_by_instance = {
        instance_name: _load_instance_memory_instructions(root, instance_name)
        for instance_name in selected_instances
    }
    effective_qdrant_url, qdrant_error = _resolve_collection_qdrant_url(
        instructions_by_instance,
        override=qdrant_url,
    )
    memory_embedding_config, embedding_error = _resolve_collection_memory_embedding_config(
        instructions_by_instance,
        embedding_config=embedding_config,
        overrides=embedding_overrides,
    )
    if qdrant_error or embedding_error:
        return (
            QdrantCollectionEnsureResult(
                instance_names=selected_instances,
                collection_name=QDRANT_USER_MEMORY_COLLECTION,
                status="config_conflict",
                ok=False,
                qdrant_url=effective_qdrant_url,
                vector_size=memory_embedding_config.dimensions,
                embedding_model=memory_embedding_config.model_name,
                error=qdrant_error or embedding_error,
            ),
        )
    specs = default_qdrant_collection_specs(
        user_memory_vector_size=memory_embedding_config.dimensions,
        user_memory_embedding_model=memory_embedding_config.model_name,
    )
    spec_by_name = {spec.name: spec for spec in specs}
    try:
        results = qdrant_ensure_factory(url=effective_qdrant_url, specs=specs)
    except Exception as exc:  # noqa: BLE001 - operator command should report controlled failures.
        return (
            QdrantCollectionEnsureResult(
                instance_names=selected_instances,
                collection_name=QDRANT_USER_MEMORY_COLLECTION,
                status="error",
                ok=False,
                qdrant_url=effective_qdrant_url,
                vector_size=memory_embedding_config.dimensions,
                embedding_model=memory_embedding_config.model_name,
                error=f"{type(exc).__name__}: {exc}",
            ),
        )
    return tuple(
        _collection_ensure_result(
            selected_instances,
            result,
            qdrant_url=effective_qdrant_url,
            spec=spec_by_name.get(result.name),
        )
        for result in results
    )


def _rebuild_result(
    instance_name: str,
    account_id: str,
    status: str,
    *,
    qdrant_url: str,
    embedding_config: EmbeddingConfig,
    point_count: int = 0,
    point_ids: tuple[str, ...] = (),
    error: str = "",
) -> QdrantMemoryRebuildResult:
    return QdrantMemoryRebuildResult(
        instance_name=instance_name,
        account_id=account_id,
        status=status,
        point_count=point_count,
        point_ids=point_ids,
        qdrant_url=str(qdrant_url or ""),
        embedding_provider=str(embedding_config.provider or ""),
        embedding_model=str(embedding_config.model_name or ""),
        embedding_dimensions=int(embedding_config.dimensions),
        error=error,
    )


def _load_instance_memory_instructions(instances_dir: Path, instance_name: str) -> BotInstructions:
    return load_instructions(instances_dir / instance_name / "Bot_Verhalten.md")


def _resolve_collection_qdrant_url(instructions_by_instance: Mapping[str, BotInstructions], *, override: str | None = None) -> tuple[str, str]:
    if override:
        return override, ""
    if not instructions_by_instance:
        return BotInstructions().memory_search_qdrant_url, ""
    urls = {
        instance_name: str(instructions.memory_search_qdrant_url or "").strip() or BotInstructions().memory_search_qdrant_url
        for instance_name, instructions in instructions_by_instance.items()
    }
    unique_urls = set(urls.values())
    if len(unique_urls) == 1:
        return next(iter(unique_urls)), ""
    conflicts = ", ".join(f"{instance}:{url}" for instance, url in sorted(urls.items()))
    return BotInstructions().memory_search_qdrant_url, f"conflicting qdrant urls: {conflicts}"


def _resolve_collection_memory_embedding_config(
    instructions_by_instance: Mapping[str, BotInstructions],
    *,
    embedding_config: EmbeddingConfig | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> tuple[EmbeddingConfig, str]:
    if not instructions_by_instance:
        config = _resolve_memory_embedding_config(BotInstructions(), embedding_config=embedding_config, overrides=overrides)
        error = _account_memory_embedding_config_error(config)
        return config, f"invalid user-memory embedding config: {error}" if error else ""
    configs = {
        instance_name: _resolve_memory_embedding_config(
            instructions,
            embedding_config=embedding_config,
            overrides=overrides,
        )
        for instance_name, instructions in instructions_by_instance.items()
    }
    config_errors = {
        instance_name: error
        for instance_name, config in configs.items()
        for error in (_account_memory_embedding_config_error(config),)
        if error
    }
    if config_errors:
        errors = ", ".join(f"{instance}:{error}" for instance, error in sorted(config_errors.items()))
        return next(iter(configs.values())), f"invalid user-memory embedding config: {errors}"
    unique_contracts = {(config.model_name, config.dimensions) for config in configs.values()}
    if len(unique_contracts) == 1:
        return next(iter(configs.values())), ""
    conflicts = ", ".join(
        f"{instance}:{config.model_name}/{config.dimensions}"
        for instance, config in sorted(configs.items())
    )
    return _resolve_memory_embedding_config(BotInstructions(), embedding_config=embedding_config, overrides=overrides), (
        f"conflicting user-memory embedding configs: {conflicts}"
    )


def _account_memory_embedding_config_error(config: EmbeddingConfig) -> str:
    try:
        build_account_memory_embedding_provider(config)
    except ValueError as exc:
        return str(exc)
    return ""


def _resolve_memory_embedding_config(
    instructions: BotInstructions,
    *,
    embedding_config: EmbeddingConfig | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> EmbeddingConfig:
    base = embedding_config or _memory_embedding_config_from_instructions(instructions)
    override = dict(overrides or {})
    return EmbeddingConfig(
        provider=str(override.get("provider") or base.provider).strip(),
        model_name=str(override.get("model_name") or base.model_name).strip(),
        dimensions=_positive_int(override.get("dimensions"), default=base.dimensions),
        endpoint=str(override.get("endpoint") if override.get("endpoint") is not None else base.endpoint).strip(),
        api_key_env=str(override.get("api_key_env") if override.get("api_key_env") is not None else base.api_key_env).strip(),
    )


def _memory_embedding_config_from_instructions(instructions: BotInstructions) -> EmbeddingConfig:
    return EmbeddingConfig(
        provider=instructions.memory_search_embedding_provider,
        model_name=instructions.memory_search_embedding_model,
        dimensions=instructions.memory_search_embedding_dimensions,
        endpoint=instructions.memory_search_embedding_endpoint,
        api_key_env=instructions.memory_search_embedding_api_key_env,
    )


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return max(1, int(default))
    return parsed if parsed > 0 else max(1, int(default))


def _resolve_instance_names(instances_dir: Path, requested: Iterable[str]) -> tuple[str, ...]:
    explicit = tuple(dict.fromkeys(str(value or "").strip() for value in requested if str(value or "").strip()))
    if explicit:
        return explicit
    if not instances_dir.exists():
        return ()
    names: list[str] = []
    for path in sorted(instances_dir.iterdir()):
        if not path.is_dir():
            continue
        if (path / "data" / "accounts").exists():
            names.append(path.name)
    return tuple(names)


def _resolve_instruction_instance_names(instances_dir: Path, requested: Iterable[str]) -> tuple[str, ...]:
    explicit = tuple(dict.fromkeys(str(value or "").strip() for value in requested if str(value or "").strip()))
    if explicit:
        return explicit
    if not instances_dir.exists():
        return ()
    names: list[str] = []
    for path in sorted(instances_dir.iterdir()):
        if path.is_dir() and (path / "Bot_Verhalten.md").exists():
            names.append(path.name)
    return tuple(names)


def _collection_ensure_result(
    instance_names: tuple[str, ...],
    result: QdrantCollectionResult,
    *,
    qdrant_url: str,
    spec: QdrantCollectionSpec | None,
) -> QdrantCollectionEnsureResult:
    return QdrantCollectionEnsureResult(
        instance_names=instance_names,
        collection_name=result.name,
        status=result.status,
        ok=result.ok,
        qdrant_url=qdrant_url or result.target,
        vector_size=spec.vector_size if spec is not None else 0,
        embedding_model=spec.embedding_model if spec is not None else "",
        error=result.error,
    )


__all__ = [
    "QdrantCollectionEnsureResult",
    "QdrantMemoryRebuildResult",
    "ensure_qdrant_collections_for_instances",
    "rebuild_qdrant_memory_index",
    "rebuild_qdrant_memory_indexes",
]
