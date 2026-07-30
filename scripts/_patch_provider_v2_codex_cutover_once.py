from __future__ import annotations

from pathlib import Path


CODEX = Path("TeeBotus/admin/codex_history.py")
WORKER = Path("TeeBotus/history_dispatcher_provider_v2_worker.py")


def replace_once(source: str, old: str, new: str, *, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


def patch_codex() -> None:
    source = CODEX.read_text(encoding="utf-8")
    source = replace_once(
        source,
        """from TeeBotus.history_dispatcher_bridge import (
    HistoryDispatcherClient,
    HistoryDispatcherError,
)
""",
        """from TeeBotus.history_dispatcher_bridge import (
    HistoryDispatcherClient,
    HistoryDispatcherError,
)
from TeeBotus.history_dispatcher_provider_v2_codex import (
    build_provider_v2_bridge,
    provider_v2_claim_to_legacy_item,
    provider_v2_dispatch_result_to_outcome,
)
from TeeBotus.history_dispatcher_provider_v2_worker import (
    ProviderV2WorkerError,
    dispatch_provider_v2_batch,
)
""",
        label="provider-v2 imports",
    )
    source = replace_once(
        source,
        """    if _history_dispatcher_mode(env) == "bridge":
        return await _dispatch_codex_history_outbox_via_dispatcher(
            store,
            instance_name=instance_name,
            account_ids=account_ids,
            senders=senders,
            env=env,
            instances_dir=instances_dir,
            secret_provider=secret_provider,
            now=now,
            dry_run=dry_run,
            limit=limit,
        )
""",
        """    dispatcher_mode = _history_dispatcher_mode(env)
    if dispatcher_mode == "provider_v2":
        return await _dispatch_codex_history_outbox_via_provider_v2(
            store,
            instance_name=instance_name,
            account_ids=account_ids,
            senders=senders,
            env=env,
            instances_dir=instances_dir,
            secret_provider=secret_provider,
            now=now,
            dry_run=dry_run,
            limit=limit,
        )
    if dispatcher_mode == "bridge":
        return await _dispatch_codex_history_outbox_via_dispatcher(
            store,
            instance_name=instance_name,
            account_ids=account_ids,
            senders=senders,
            env=env,
            instances_dir=instances_dir,
            secret_provider=secret_provider,
            now=now,
            dry_run=dry_run,
            limit=limit,
        )
""",
        label="provider-v2 dispatch branch",
    )
    source = replace_once(
        source,
        '    if mode not in {"legacy", "shadow", "bridge"}:\n',
        '    if mode not in {"legacy", "shadow", "bridge", "provider_v2"}:\n',
        label="provider-v2 mode allowlist",
    )
    provider_function = r'''
async def _dispatch_codex_history_outbox_via_provider_v2(
    store: AccountStore,
    *,
    instance_name: str,
    account_ids: Sequence[str] = (),
    senders: Mapping[str, ProactiveSender] | None = None,
    env: Mapping[str, str] | None = None,
    instances_dir: str | Path | None = None,
    secret_provider: InstanceSecretProvider | None = None,
    now: datetime | None = None,
    dry_run: bool = False,
    limit: int = CODEX_HISTORY_DEFAULT_DISPATCH_LIMIT,
) -> dict[str, Any]:
    dispatch_now = now or datetime.now(timezone.utc)
    timestamp = _iso_timestamp(dispatch_now)
    if not _codex_history_dispatch_instance_allowed(instance_name, env=env):
        return {
            "ok": True,
            "dry_run": dry_run,
            "instance": instance_name,
            "generated_at": timestamp,
            "items": [],
            "status_counts": {},
            "mode": "provider_v2",
        }
    candidate_account_ids = _codex_history_dispatch_account_ids(
        store,
        instance_name=instance_name,
        account_ids=account_ids,
        env=env,
        instances_dir=instances_dir,
        secret_provider=secret_provider,
    )
    routable_account_ids = _codex_history_dispatch_routable_account_ids(
        store,
        candidate_account_ids,
        instance_name=instance_name,
        instances_dir=instances_dir,
        secret_provider=secret_provider,
    )
    if dry_run:
        rows = [
            {
                "codex_history_item_id": "",
                "account_id": account_id,
                "status": "would_poll",
                "reason": "provider_v2",
                "channel": "",
                "summary_prefix": "",
            }
            for account_id in routable_account_ids
        ]
        if not rows:
            rows = [
                {
                    "codex_history_item_id": "",
                    "account_id": "",
                    "status": "would_skip",
                    "reason": "no_routable_recipients",
                    "channel": "",
                    "summary_prefix": "",
                }
            ]
        return {
            "ok": True,
            "dry_run": True,
            "instance": instance_name,
            "generated_at": timestamp,
            "items": rows,
            "status_counts": _status_counts(rows),
            "mode": "provider_v2",
        }

    normalized_senders = senders or {}
    worker_id = (
        f"teebotus:{_safe_instance_name(instance_name)}:{os.getpid()}"
    )[:128]
    try:
        bridge = build_provider_v2_bridge(
            store,
            instance_name=instance_name,
            socket_path=_history_dispatcher_socket_path(env),
            secret_provider=secret_provider,
        )

        async def send_claim(
            claim: Mapping[str, Any],
            recipient_ref: str,
        ) -> dict[str, Any]:
            item = provider_v2_claim_to_legacy_item(claim)
            local_result = await _dispatch_codex_history_item_to_account(
                store,
                item,
                recipient_ref,
                instance_name=instance_name,
                senders=normalized_senders,
                instances_dir=instances_dir,
                secret_provider=secret_provider,
                now=timestamp,
                persist_result=isinstance(store, AccountStore),
            )
            return provider_v2_dispatch_result_to_outcome(
                local_result,
                recipient_ref=recipient_ref,
            )

        batch = await dispatch_provider_v2_batch(
            bridge,
            worker_id=worker_id,
            recipient_refs=routable_account_ids,
            send=send_claim,
            limit=max(1, int(limit) if int(limit) > 0 else 20),
            lease_seconds=120,
        )
        result_rows = [
            {
                "codex_history_item_id": str(row.get("event_id") or ""),
                "account_id": str(row.get("recipient_ref") or ""),
                "status": str(row.get("status") or "failed"),
                "reason": str(row.get("reason_code") or ""),
                "channel": "",
                "summary_prefix": "provider_v2",
            }
            for row in batch.get("items", [])
            if isinstance(row, Mapping)
        ]
        return {
            "ok": bool(batch.get("ok")),
            "dry_run": False,
            "instance": instance_name,
            "generated_at": timestamp,
            "items": result_rows,
            "status_counts": dict(batch.get("status_counts", {})),
            "mode": "provider_v2",
            "blocked": bool(batch.get("blocked")),
            "reason": str(batch.get("reason") or ""),
            "claims": int(batch.get("claims") or 0),
            "sent": int(batch.get("sent") or 0),
            "spooled": int(batch.get("spooled") or 0),
        }
    except (
        HistoryDispatcherError,
        ProviderV2WorkerError,
        AccountStoreError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        LOGGER.warning(
            "History-Dispatcher provider-v2 dispatch unavailable: %s",
            str(exc)[:240],
        )
        row = {
            "codex_history_item_id": "",
            "account_id": "",
            "status": "failed",
            "reason": "provider_v2_unavailable",
            "channel": "",
            "summary_prefix": "provider_v2",
            "error": str(exc)[:240],
        }
        return {
            "ok": False,
            "dry_run": False,
            "instance": instance_name,
            "generated_at": timestamp,
            "items": [row],
            "status_counts": {"failed": 1},
            "mode": "provider_v2",
            "blocked": True,
            "reason": "provider_v2_unavailable",
            "claims": 0,
            "sent": 0,
            "spooled": 0,
        }


'''
    source = replace_once(
        source,
        "async def _dispatch_codex_history_outbox_via_dispatcher(\n",
        provider_function
        + "async def _dispatch_codex_history_outbox_via_dispatcher(\n",
        label="provider-v2 dispatch function",
    )
    CODEX.write_text(source, encoding="utf-8")


def patch_worker() -> None:
    source = WORKER.read_text(encoding="utf-8")
    source = replace_once(
        source,
        """        target_delivery_id = _safe_ref(
            claim.get("target_delivery_id"),
            field="target_delivery_id",
        )
        attempt_no = max(1, int(claim.get("attempt_no") or 1))
""",
        """        target_delivery_id = _safe_ref(
            claim.get("target_delivery_id"),
            field="target_delivery_id",
        )
        event_id = _safe_ref(claim.get("event_id"), field="event_id")
        attempt_no = max(1, int(claim.get("attempt_no") or 1))
""",
        label="worker event id validation",
    )
    source = replace_once(
        source,
        """            items.append(
                {
                    "target_delivery_id": target_delivery_id,
                    **outcome,
                }
            )
""",
        """            items.append(
                {
                    "event_id": event_id,
                    "target_delivery_id": target_delivery_id,
                    **outcome,
                }
            )
""",
        label="worker event id output",
    )
    WORKER.write_text(source, encoding="utf-8")


def main() -> None:
    patch_codex()
    patch_worker()


if __name__ == "__main__":
    main()
