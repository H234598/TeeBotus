from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from TeeBotus.embedding.config import EmbeddingConfig, build_account_memory_embedding_provider, build_embedding_provider
from TeeBotus.admin.codex_history import codex_history_bibliothekar_chunks
from TeeBotus.instructions import BotInstructions, load_instructions
from TeeBotus.runtime.accounts import AccountStore, InstanceSecretProvider, runtime_secret_provider, validate_sha512_token
from TeeBotus.runtime.bibliothekar import BibliothekarStore
from TeeBotus.runtime.qdrant import (
    DEFAULT_BIBLIOTHEKAR_EMBEDDING_DIMENSIONS,
    QDRANT_BIBLIOTHEKAR_COLLECTION,
    QDRANT_CODEX_HISTORY_COLLECTION,
    QDRANT_USER_MEMORY_COLLECTION,
    QdrantCollectionResult,
    QdrantCollectionSpec,
    default_qdrant_collection_specs,
    ensure_default_collections,
    qdrant_codex_history_collection_spec,
    qdrant_user_memory_side_collection_spec,
)
from TeeBotus.runtime.qdrant_bibliothekar import QdrantBibliothekarIndex
from TeeBotus.runtime.qdrant_memory import QdrantMemoryIndex


@dataclass(frozen=True)
class QdrantMemoryRebuildResult:
    instance_name: str
    account_id: str
    status: str
    point_count: int = 0
    point_ids: tuple[str, ...] = ()
    qdrant_url: str = ""
    collection_name: str = QDRANT_USER_MEMORY_COLLECTION
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
    actual_vector_size: int | None = None


@dataclass(frozen=True)
class QdrantBibliothekarRebuildResult:
    instance_name: str
    status: str
    chunk_count: int = 0
    point_count: int = 0
    point_ids: tuple[str, ...] = ()
    qdrant_url: str = ""
    collection_name: str = QDRANT_BIBLIOTHEKAR_COLLECTION
    embedding_provider: str = ""
    embedding_model: str = ""
    embedding_dimensions: int = 0
    error: str = ""


@dataclass(frozen=True)
class QdrantCodexHistoryRebuildResult:
    instance_name: str
    status: str
    chunk_count: int = 0
    point_count: int = 0
    point_ids: tuple[str, ...] = ()
    qdrant_url: str = ""
    collection_name: str = QDRANT_CODEX_HISTORY_COLLECTION
    embedding_provider: str = ""
    embedding_model: str = ""
    embedding_dimensions: int = 0
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
    collection_name: str = QDRANT_USER_MEMORY_COLLECTION,
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
        store_kwargs: dict[str, Any] = {
            "create_dirs": False,
            "secret_provider": secret_provider or runtime_secret_provider(),
        }
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
                    collection_name=collection_name or QDRANT_USER_MEMORY_COLLECTION,
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
                    collection_name=collection_name or QDRANT_USER_MEMORY_COLLECTION,
                    embedding_config=effective_embedding_config,
                    error="no accounts",
                )
            )
            continue
        for account_id in target_accounts:
            try:
                embedding_provider = build_account_memory_embedding_provider(effective_embedding_config)
                entries = store.read_memory_entries(account_id)
                if dry_run:
                    results.append(
                        _rebuild_result(
                            instance_name,
                            account_id,
                            "dry_run",
                            point_count=len(entries),
                            qdrant_url=effective_qdrant_url,
                            collection_name=collection_name or QDRANT_USER_MEMORY_COLLECTION,
                            embedding_config=effective_embedding_config,
                        )
                    )
                    continue
                index = qdrant_index_factory(
                    url=effective_qdrant_url,
                    collection=collection_name or QDRANT_USER_MEMORY_COLLECTION,
                    embedding_provider=embedding_provider,
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
                        collection_name=collection_name or QDRANT_USER_MEMORY_COLLECTION,
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
                        collection_name=collection_name or QDRANT_USER_MEMORY_COLLECTION,
                        embedding_config=effective_embedding_config,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
    return tuple(results)


def rebuild_qdrant_bibliothekar_indexes(
    *,
    instances_dir: str | Path = "instances",
    instance_names: Iterable[str] = (),
    qdrant_url: str | None = None,
    embedding_config: EmbeddingConfig | None = None,
    embedding_overrides: Mapping[str, Any] | None = None,
    dry_run: bool = False,
    qdrant_index_factory: Callable[..., QdrantBibliothekarIndex] = QdrantBibliothekarIndex,
) -> tuple[QdrantBibliothekarRebuildResult, ...]:
    root = Path(instances_dir)
    selected_instances = _resolve_instruction_instance_names(root, instance_names)
    results: list[QdrantBibliothekarRebuildResult] = []
    for instance_name in selected_instances:
        instructions = _load_instance_memory_instructions(root, instance_name)
        effective_qdrant_url = qdrant_url or instructions.bibliothekar_qdrant_url
        effective_embedding_config = _resolve_bibliothekar_embedding_config(
            embedding_config=embedding_config,
            overrides=embedding_overrides,
        )
        try:
            embedding_provider = build_embedding_provider(effective_embedding_config)
            store = BibliothekarStore(instance_name, root)
            chunks = store.read_chunks()
            if dry_run:
                results.append(
                    _bibliothekar_rebuild_result(
                        instance_name,
                        "dry_run",
                        chunk_count=len(chunks),
                        point_count=len(chunks),
                        qdrant_url=effective_qdrant_url,
                        collection_name=instructions.bibliothekar_collection or QDRANT_BIBLIOTHEKAR_COLLECTION,
                        embedding_config=effective_embedding_config,
                    )
                )
                continue
            index = qdrant_index_factory(
                url=effective_qdrant_url,
                collection=instructions.bibliothekar_collection or QDRANT_BIBLIOTHEKAR_COLLECTION,
                embedding_provider=embedding_provider,
            )
            if not chunks:
                index.delete_instance(instance_name=instance_name)
                results.append(
                    _bibliothekar_rebuild_result(
                        instance_name,
                        "cleared",
                        qdrant_url=effective_qdrant_url,
                        collection_name=instructions.bibliothekar_collection or QDRANT_BIBLIOTHEKAR_COLLECTION,
                        embedding_config=effective_embedding_config,
                    )
                )
                continue
            index.delete_instance(instance_name=instance_name)
            point_ids = index.index_chunks(instance_name=instance_name, chunks=chunks)
            results.append(
                _bibliothekar_rebuild_result(
                    instance_name,
                    "rebuilt",
                    chunk_count=len(chunks),
                    point_count=len(point_ids),
                    point_ids=tuple(point_ids),
                    qdrant_url=effective_qdrant_url,
                    collection_name=instructions.bibliothekar_collection or QDRANT_BIBLIOTHEKAR_COLLECTION,
                    embedding_config=effective_embedding_config,
                )
            )
        except Exception as exc:  # noqa: BLE001 - operator command should report every instance.
            results.append(
                _bibliothekar_rebuild_result(
                    instance_name,
                    "error",
                    qdrant_url=effective_qdrant_url,
                    embedding_config=effective_embedding_config,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
    return tuple(results)


def rebuild_qdrant_codex_history_indexes(
    *,
    instances_dir: str | Path = "instances",
    instance_names: Iterable[str] = (),
    qdrant_url: str | None = None,
    collection_name: str = QDRANT_CODEX_HISTORY_COLLECTION,
    repo: str = "",
    limit: int = 0,
    embedding_config: EmbeddingConfig | None = None,
    embedding_overrides: Mapping[str, Any] | None = None,
    dry_run: bool = False,
    secret_provider: InstanceSecretProvider | None = None,
    qdrant_index_factory: Callable[..., QdrantBibliothekarIndex] = QdrantBibliothekarIndex,
) -> tuple[QdrantCodexHistoryRebuildResult, ...]:
    root = Path(instances_dir)
    selected_instances = _resolve_instruction_instance_names(root, instance_names)
    results: list[QdrantCodexHistoryRebuildResult] = []
    for instance_name in selected_instances:
        instructions = _load_instance_memory_instructions(root, instance_name)
        effective_qdrant_url = qdrant_url or instructions.bibliothekar_qdrant_url
        effective_embedding_config = _resolve_bibliothekar_embedding_config(
            embedding_config=embedding_config,
            overrides=embedding_overrides,
        )
        try:
            embedding_provider = build_embedding_provider(effective_embedding_config)
            store = AccountStore(
                root / instance_name / "data" / "accounts",
                instance_name,
                create_dirs=False,
                secret_provider=secret_provider or runtime_secret_provider(),
            )
            chunks = codex_history_bibliothekar_chunks(
                store,
                instance_dir=root / instance_name,
                instance_name=instance_name,
                repo=repo,
                limit=limit,
            )
            if dry_run:
                results.append(
                    _codex_history_rebuild_result(
                        instance_name,
                        "dry_run",
                        chunk_count=len(chunks),
                        point_count=len(chunks),
                        qdrant_url=effective_qdrant_url,
                        collection_name=collection_name or QDRANT_CODEX_HISTORY_COLLECTION,
                        embedding_config=effective_embedding_config,
                    )
                )
                continue
            full_rebuild = _is_full_codex_history_rebuild(repo=repo, limit=limit)
            if not chunks:
                if full_rebuild:
                    index = qdrant_index_factory(
                        url=effective_qdrant_url,
                        collection=collection_name or QDRANT_CODEX_HISTORY_COLLECTION,
                        embedding_provider=embedding_provider,
                    )
                    index.delete_instance(instance_name=instance_name)
                    results.append(
                        _codex_history_rebuild_result(
                            instance_name,
                            "cleared",
                            qdrant_url=effective_qdrant_url,
                            collection_name=collection_name or QDRANT_CODEX_HISTORY_COLLECTION,
                            embedding_config=effective_embedding_config,
                        )
                    )
                    continue
                results.append(
                    _codex_history_rebuild_result(
                        instance_name,
                        "skipped",
                        qdrant_url=effective_qdrant_url,
                        collection_name=collection_name or QDRANT_CODEX_HISTORY_COLLECTION,
                        embedding_config=effective_embedding_config,
                        error="no codex history chunks",
                    )
                )
                continue
            index = qdrant_index_factory(
                url=effective_qdrant_url,
                collection=collection_name or QDRANT_CODEX_HISTORY_COLLECTION,
                embedding_provider=embedding_provider,
            )
            if full_rebuild:
                index.delete_instance(instance_name=instance_name)
            point_ids = index.index_chunks(instance_name=instance_name, chunks=chunks)
            results.append(
                _codex_history_rebuild_result(
                    instance_name,
                    "rebuilt",
                    chunk_count=len(chunks),
                    point_count=len(point_ids),
                    point_ids=tuple(point_ids),
                    qdrant_url=effective_qdrant_url,
                    collection_name=collection_name or QDRANT_CODEX_HISTORY_COLLECTION,
                    embedding_config=effective_embedding_config,
                )
            )
        except Exception as exc:  # noqa: BLE001 - operator command should report every instance.
            results.append(
                _codex_history_rebuild_result(
                    instance_name,
                    "error",
                    qdrant_url=effective_qdrant_url,
                    collection_name=collection_name or QDRANT_CODEX_HISTORY_COLLECTION,
                    embedding_config=effective_embedding_config,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
    return tuple(results)


def _is_full_codex_history_rebuild(*, repo: str, limit: int) -> bool:
    return not str(repo or "").strip() and int(limit or 0) <= 0


def ensure_qdrant_collections_for_instances(
    *,
    instances_dir: str | Path = "instances",
    instance_names: Iterable[str] = (),
    qdrant_url: str | None = None,
    embedding_config: EmbeddingConfig | None = None,
    embedding_overrides: Mapping[str, Any] | None = None,
    include_memory_side_dimensions: Iterable[int] = (),
    include_codex_history: bool = False,
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
    specs = list(
        default_qdrant_collection_specs(
            user_memory_vector_size=memory_embedding_config.dimensions,
            user_memory_embedding_model=memory_embedding_config.model_name,
        )
    )
    for dimensions in _unique_positive_ints(include_memory_side_dimensions):
        specs.append(qdrant_user_memory_side_collection_spec(dimensions))
    if include_codex_history:
        specs.append(qdrant_codex_history_collection_spec())
    spec_by_name = {spec.name: spec for spec in specs}
    try:
        results = qdrant_ensure_factory(url=effective_qdrant_url, specs=tuple(specs))
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
    collection_name: str = QDRANT_USER_MEMORY_COLLECTION,
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
        collection_name=str(collection_name or QDRANT_USER_MEMORY_COLLECTION),
        embedding_provider=str(embedding_config.provider or ""),
        embedding_model=str(embedding_config.model_name or ""),
        embedding_dimensions=int(embedding_config.dimensions),
        error=error,
    )


def _bibliothekar_rebuild_result(
    instance_name: str,
    status: str,
    *,
    qdrant_url: str,
    embedding_config: EmbeddingConfig,
    collection_name: str = QDRANT_BIBLIOTHEKAR_COLLECTION,
    chunk_count: int = 0,
    point_count: int = 0,
    point_ids: tuple[str, ...] = (),
    error: str = "",
) -> QdrantBibliothekarRebuildResult:
    return QdrantBibliothekarRebuildResult(
        instance_name=instance_name,
        status=status,
        chunk_count=chunk_count,
        point_count=point_count,
        point_ids=point_ids,
        qdrant_url=str(qdrant_url or ""),
        collection_name=str(collection_name or QDRANT_BIBLIOTHEKAR_COLLECTION),
        embedding_provider=str(embedding_config.provider or ""),
        embedding_model=str(embedding_config.model_name or ""),
        embedding_dimensions=int(embedding_config.dimensions),
        error=error,
    )


def _codex_history_rebuild_result(
    instance_name: str,
    status: str,
    *,
    qdrant_url: str,
    embedding_config: EmbeddingConfig,
    collection_name: str = QDRANT_CODEX_HISTORY_COLLECTION,
    chunk_count: int = 0,
    point_count: int = 0,
    point_ids: tuple[str, ...] = (),
    error: str = "",
) -> QdrantCodexHistoryRebuildResult:
    return QdrantCodexHistoryRebuildResult(
        instance_name=instance_name,
        status=status,
        chunk_count=chunk_count,
        point_count=point_count,
        point_ids=point_ids,
        qdrant_url=str(qdrant_url or ""),
        collection_name=str(collection_name or QDRANT_CODEX_HISTORY_COLLECTION),
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


def _resolve_bibliothekar_embedding_config(
    *,
    embedding_config: EmbeddingConfig | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> EmbeddingConfig:
    base = embedding_config or EmbeddingConfig(
        provider="fake",
        model_name="teebotus-fake-bibliothekar-embedding-v1",
        dimensions=DEFAULT_BIBLIOTHEKAR_EMBEDDING_DIMENSIONS,
    )
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


def _unique_positive_ints(values: Iterable[int]) -> tuple[int, ...]:
    seen: set[int] = set()
    dimensions: list[int] = []
    for value in values:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed < 1 or parsed in seen:
            continue
        seen.add(parsed)
        dimensions.append(parsed)
    return tuple(dimensions)


def _resolve_instance_names(instances_dir: Path, requested: Iterable[str]) -> tuple[str, ...]:
    explicit = _normalize_requested_instance_names(requested)
    if explicit:
        return explicit
    if not instances_dir.exists():
        return ()
    names: list[str] = []
    for path in sorted(instances_dir.iterdir()):
        if not path.is_dir():
            continue
        if _looks_like_account_store_instance(path):
            names.append(path.name)
    return tuple(names)


def _looks_like_account_store_instance(instance_dir: Path) -> bool:
    accounts_dir = instance_dir / "data" / "accounts"
    if not accounts_dir.is_dir():
        return False
    if (instance_dir / "Bot_Verhalten.md").is_file():
        return True
    account_store_markers = (
        "Account_Index.json",
        "Account_Identities.json",
        "Account_Keyring.json",
        "Account_Memory.json",
        "Account_Memory.sqlite",
        "Account_Memory.sqlite3",
        "Account_Memory.backup.sqlite3",
    )
    return any((accounts_dir / marker).exists() for marker in account_store_markers)


def _resolve_instruction_instance_names(instances_dir: Path, requested: Iterable[str]) -> tuple[str, ...]:
    explicit = _normalize_requested_instance_names(requested)
    if explicit:
        return explicit
    if not instances_dir.exists():
        return ()
    names: list[str] = []
    for path in sorted(instances_dir.iterdir()):
        if path.is_dir() and (path / "Bot_Verhalten.md").exists():
            names.append(path.name)
    return tuple(names)


def validate_embedding_instance_name(value: object) -> str:
    name = str(value or "").strip()
    if not name:
        return ""
    if name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError("Instance name must be a single path segment.")
    return name


def _normalize_requested_instance_names(requested: Iterable[str]) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    for value in requested:
        name = validate_embedding_instance_name(value)
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
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
        actual_vector_size=result.actual_vector_size,
    )


__all__ = [
    "QdrantBibliothekarRebuildResult",
    "QdrantCodexHistoryRebuildResult",
    "QdrantCollectionEnsureResult",
    "QdrantMemoryRebuildResult",
    "ensure_qdrant_collections_for_instances",
    "rebuild_qdrant_bibliothekar_indexes",
    "rebuild_qdrant_codex_history_indexes",
    "rebuild_qdrant_memory_index",
    "rebuild_qdrant_memory_indexes",
    "validate_embedding_instance_name",
]
