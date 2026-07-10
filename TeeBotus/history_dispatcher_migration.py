from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from TeeBotus.history_dispatcher_bridge import HistoryDispatcherClient, HistoryDispatcherError
from TeeBotus.runtime.accounts import INSTANCE_STATE_ACCOUNT_ID, AccountStore


def migrate_codex_history_to_dispatcher(
    store: AccountStore,
    client: HistoryDispatcherClient,
    *,
    dry_run: bool = False,
    limit: int = 0,
) -> dict[str, Any]:
    """Stream the decrypted AccountStore view directly into the Dispatcher API.

    No plaintext staging file is created. The source store remains untouched;
    idempotency keys make rerunning the migration safe.
    """
    rows = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
    dispatch_rows = store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID)
    dispatch_by_item: dict[str, list[dict[str, Any]]] = {}
    for result in dispatch_rows:
        if not isinstance(result, Mapping):
            continue
        item_key = str(result.get("codex_history_item_id") or "").strip()
        if item_key:
            dispatch_by_item.setdefault(item_key, []).append(dict(result))
    if limit > 0:
        rows = rows[:limit]
    digest = hashlib.sha256()
    imported = 0
    deduplicated = 0
    failures: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        canonical = json.dumps(dict(row), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest.update(hashlib.sha256(canonical).digest())
        item_id = str(row.get("id") or "").strip()
        if dry_run:
            imported += 1
            continue
        project = row.get("project")
        if isinstance(project, Mapping):
            project = str(project.get("repo_root") or project.get("repo_name") or "")
        request = {
            "id": item_id,
            "source": str(row.get("source") or "teebotus-legacy"),
            "kind": str(row.get("kind") or "codex_run_summary"),
            "target_group": str(row.get("target_group") or (row.get("delivery") or {}).get("target_group") or "status_admins"),
            "project": str(project or ""),
            "created_at": str(row.get("created_at") or ""),
            "dedupe_key": item_id or "sha256:" + hashlib.sha256(canonical).hexdigest(),
            "payload": dict(row),
            "recipient_results": dispatch_by_item.get(item_id, []),
        }
        try:
            response = client.request("history.append", request)
            if not response.get("ok"):
                failures.append(str(response.get("error") or "history.append failed")[:240])
            elif response.get("data", {}).get("deduplicated"):
                deduplicated += 1
            else:
                imported += 1
        except HistoryDispatcherError as exc:
            failures.append(str(exc)[:240])
            break
    return {
        "ok": not failures,
        "dry_run": dry_run,
        "total": len(rows),
        "imported": imported,
        "deduplicated": deduplicated,
        "failures": failures,
        "source_digest": digest.hexdigest(),
    }
