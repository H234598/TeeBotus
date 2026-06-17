from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from TeeBotus.runtime.accounts import AccountStore, InstanceSecretProvider, validate_sha512_token
from TeeBotus.runtime.qdrant_memory import QdrantMemoryIndex


@dataclass(frozen=True)
class QdrantMemoryRebuildResult:
    instance_name: str
    account_id: str
    status: str
    point_count: int = 0
    point_ids: tuple[str, ...] = ()
    error: str = ""


def rebuild_qdrant_memory_index(
    *,
    account_store: AccountStore,
    qdrant_index: QdrantMemoryIndex,
    instance_name: str,
    account_id: str,
) -> tuple[str, ...]:
    return qdrant_index.rebuild(account_store=account_store, instance_name=instance_name, account_id=account_id)


def rebuild_qdrant_memory_indexes(
    *,
    instances_dir: str | Path = "instances",
    instance_names: Iterable[str] = (),
    account_ids: Iterable[str] = (),
    qdrant_url: str | None = None,
    dry_run: bool = False,
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
        store_kwargs: dict[str, Any] = {"create_dirs": False}
        if secret_provider is not None:
            store_kwargs["secret_provider"] = secret_provider
        store = AccountStore(root / instance_name / "data" / "accounts", instance_name, **store_kwargs)
        try:
            target_accounts = requested_accounts or store.list_account_ids()
        except Exception as exc:  # noqa: BLE001 - operator command should report every instance.
            results.append(QdrantMemoryRebuildResult(instance_name, "", "error", error=f"{type(exc).__name__}: {exc}"))
            continue
        if not target_accounts:
            results.append(QdrantMemoryRebuildResult(instance_name, "", "skipped", error="no accounts"))
            continue
        for account_id in target_accounts:
            try:
                entries = store.read_memory_entries(account_id)
                if dry_run:
                    results.append(QdrantMemoryRebuildResult(instance_name, account_id, "dry_run", point_count=len(entries)))
                    continue
                index = qdrant_index_factory(url=qdrant_url)
                point_ids = rebuild_qdrant_memory_index(
                    account_store=store,
                    qdrant_index=index,
                    instance_name=instance_name,
                    account_id=account_id,
                )
                results.append(QdrantMemoryRebuildResult(instance_name, account_id, "rebuilt", point_count=len(point_ids), point_ids=tuple(point_ids)))
            except Exception as exc:  # noqa: BLE001 - keep rebuilding other accounts.
                results.append(QdrantMemoryRebuildResult(instance_name, account_id, "error", error=f"{type(exc).__name__}: {exc}"))
    return tuple(results)


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


__all__ = [
    "QdrantMemoryRebuildResult",
    "rebuild_qdrant_memory_index",
    "rebuild_qdrant_memory_indexes",
]
