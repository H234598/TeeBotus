from __future__ import annotations

from TeeBotus.runtime.accounts import AccountStore
from TeeBotus.runtime.qdrant_memory import QdrantMemoryIndex


def rebuild_qdrant_memory_index(
    *,
    account_store: AccountStore,
    qdrant_index: QdrantMemoryIndex,
    instance_name: str,
    account_id: str,
) -> tuple[str, ...]:
    return qdrant_index.rebuild(account_store=account_store, instance_name=instance_name, account_id=account_id)
