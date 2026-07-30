from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from TeeBotus.admin import codex_history
from TeeBotus.history_dispatcher_provider_v2_codex import (
    PROVIDER_V2_CALLBACK_SPOOL_DIRNAME,
    PROVIDER_V2_LEGACY_SPOOL_DIRNAME,
    build_provider_v2_bridge,
    provider_v2_claim_to_legacy_item,
    provider_v2_dispatch_result_to_outcome,
)
from TeeBotus.runtime.accounts import (
    INSTANCE_STATE_ACCOUNT_ID,
    AccountStore,
    StaticSecretProvider,
)


def _claim() -> dict[str, Any]:
    return {
        "target_delivery_id": "target_cutover",
        "route_plan_id": "route_cutover",
        "event_id": "evt_cutover",
        "target_id": "telegram",
        "provider_id": "teebotus",
        "provider_schema_version": 1,
        "binding": {
            "schema_version": 1,
            "provider": "teebotus",
            "bridge_capability": "history-dispatcher-telegram-v2",
        },
        "attempt_no": 4,
        "worker_id": "teebotus-worker",
        "capability_version": "history-dispatcher-telegram-v2",
        "claim_token": "token_" + "a" * 40,
        "claim_expires_at": "2026-07-30T22:00:00Z",
        "payload": {
            "history_kind": "task_completion",
            "timestamp": "2026-07-30T21:00:00Z",
            "project_id": "proj_opaque",
            "project_label": "History Dispatcher",
            "source_ordinal": 7,
            "text": "Die Aufgabe ist abgeschlossen.",
        },
        "successful_recipient_refs": [],
        "open_recipient_refs": ["status_admin_primary"],
    }


def test_provider_v2_mode_is_explicit_and_unknown_values_still_fail_to_legacy() -> None:
    assert (
        codex_history._history_dispatcher_mode(
            {codex_history.HISTORY_DISPATCHER_MODE_ENV: "provider_v2"}
        )
        == "provider_v2"
    )
    assert (
        codex_history._history_dispatcher_mode(
            {codex_history.HISTORY_DISPATCHER_MODE_ENV: "automatic"}
        )
        == "legacy"
    )


def test_claim_payload_is_converted_to_bounded_legacy_attachment_item() -> None:
    item = provider_v2_claim_to_legacy_item(_claim())

    assert item["id"] == "evt_cutover"
    assert item["kind"] == "codex_run_summary"
    assert item["created_at"] == "2026-07-30T21:00:00Z"
    assert item["project"] == {
        "repo_id": "proj_opaque",
        "repo_name": "History Dispatcher",
        "repo_root": "",
    }
    assert item["version"]["semver"] == "provider-v2"
    assert item["summary_number"] == 7
    assert item["summary"]["markdown"] == "Die Aufgabe ist abgeschlossen."
    assert item["summary_prefix"] == "task_completion"


def test_transport_result_exposes_only_opaque_message_reference() -> None:
    result = provider_v2_dispatch_result_to_outcome(
        {
            "account_id": "status_admin_primary",
            "status": "accepted",
            "reason": "accepted",
            "message_ref": "telegram-message-raw-123",
        },
        recipient_ref="status_admin_primary",
    )

    assert result["recipient_ref"] == "status_admin_primary"
    assert result["status"] == "accepted"
    assert result["message_ref_key"].startswith("message_")
    assert "telegram-message-raw-123" not in result["message_ref_key"]
    assert "message_ref" not in result


def test_provider_bridge_uses_separate_owner_only_spool_directories(tmp_path: Path) -> None:
    provider = StaticSecretProvider(b"k" * 32)
    store = AccountStore(
        tmp_path / "accounts",
        "TeeBotus_Logger",
        secret_provider=provider,
    )

    bridge = build_provider_v2_bridge(
        store,
        instance_name="TeeBotus_Logger",
        socket_path=tmp_path / "runtime" / "control.sock",
        secret_provider=provider,
    )

    state_dir = store.account_dir(INSTANCE_STATE_ACCOUNT_ID)
    assert bridge.spool.root == state_dir / PROVIDER_V2_LEGACY_SPOOL_DIRNAME
    assert bridge.provider_spool is not None
    assert (
        bridge.provider_spool.root
        == state_dir / PROVIDER_V2_CALLBACK_SPOOL_DIRNAME
    )
    assert bridge.spool.root != bridge.provider_spool.root


def test_provider_v2_dry_run_never_claims_or_reads_claim_token(monkeypatch) -> None:
    class Store:
        pass

    monkeypatch.setattr(
        codex_history,
        "_codex_history_dispatch_instance_allowed",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        codex_history,
        "_codex_history_dispatch_account_ids",
        lambda *_args, **_kwargs: ("status_admin_primary",),
    )
    monkeypatch.setattr(
        codex_history,
        "_codex_history_dispatch_routable_account_ids",
        lambda *_args, **_kwargs: ("status_admin_primary",),
    )

    async def forbidden_worker(*_args, **_kwargs):
        raise AssertionError("dry-run must not claim")

    monkeypatch.setattr(
        codex_history,
        "dispatch_provider_v2_batch",
        forbidden_worker,
    )

    result = asyncio.run(
        codex_history.dispatch_codex_history_outbox(
            Store(),  # type: ignore[arg-type]
            instance_name="TeeBotus_Logger",
            env={codex_history.HISTORY_DISPATCHER_MODE_ENV: "provider_v2"},
            dry_run=True,
        )
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["mode"] == "provider_v2"
    assert result["items"] == [
        {
            "codex_history_item_id": "",
            "account_id": "status_admin_primary",
            "status": "would_poll",
            "reason": "provider_v2",
            "channel": "",
            "summary_prefix": "",
        }
    ]


def test_provider_v2_dispatch_uses_worker_without_legacy_fallback(monkeypatch) -> None:
    class Store:
        secret_provider = StaticSecretProvider(b"k" * 32)

    fake_bridge = object()
    monkeypatch.setattr(
        codex_history,
        "_codex_history_dispatch_instance_allowed",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        codex_history,
        "_codex_history_dispatch_account_ids",
        lambda *_args, **_kwargs: ("status_admin_primary",),
    )
    monkeypatch.setattr(
        codex_history,
        "_codex_history_dispatch_routable_account_ids",
        lambda *_args, **_kwargs: ("status_admin_primary",),
    )
    monkeypatch.setattr(
        codex_history,
        "build_provider_v2_bridge",
        lambda *_args, **_kwargs: fake_bridge,
    )

    async def fake_send_to_account(
        _store,
        item,
        account_id,
        **_kwargs,
    ):
        assert item["id"] == "evt_cutover"
        assert account_id == "status_admin_primary"
        return {
            "account_id": account_id,
            "status": "accepted",
            "reason": "accepted",
            "message_ref": "raw-telegram-message-123",
        }

    monkeypatch.setattr(
        codex_history,
        "_dispatch_codex_history_item_to_account",
        fake_send_to_account,
    )

    async def fake_worker(
        bridge,
        *,
        worker_id,
        recipient_refs,
        send,
        **_kwargs,
    ):
        assert bridge is fake_bridge
        assert worker_id.startswith("teebotus:")
        assert recipient_refs == ("status_admin_primary",)
        outcome = await send(_claim(), "status_admin_primary")
        assert "message_ref" not in outcome
        return {
            "ok": True,
            "blocked": False,
            "reason": "",
            "claims": 1,
            "sent": 1,
            "spooled": 0,
            "items": [
                {
                    "event_id": "evt_cutover",
                    "target_delivery_id": "target_cutover",
                    **outcome,
                }
            ],
            "status_counts": {"accepted": 1},
        }

    monkeypatch.setattr(
        codex_history,
        "dispatch_provider_v2_batch",
        fake_worker,
    )

    legacy_called = False

    async def forbidden_legacy(*_args, **_kwargs):
        nonlocal legacy_called
        legacy_called = True
        raise AssertionError("provider_v2 must not fall back")

    monkeypatch.setattr(
        codex_history,
        "_dispatch_codex_history_outbox_via_dispatcher",
        forbidden_legacy,
    )

    result = asyncio.run(
        codex_history.dispatch_codex_history_outbox(
            Store(),  # type: ignore[arg-type]
            instance_name="TeeBotus_Logger",
            env={codex_history.HISTORY_DISPATCHER_MODE_ENV: "provider_v2"},
            senders={},
        )
    )

    assert legacy_called is False
    assert result["ok"] is True
    assert result["mode"] == "provider_v2"
    assert result["items"] == [
        {
            "codex_history_item_id": "evt_cutover",
            "account_id": "status_admin_primary",
            "status": "accepted",
            "reason": "",
            "channel": "",
            "summary_prefix": "provider_v2",
        }
    ]


def test_provider_v2_failure_returns_failed_result_without_fallback(monkeypatch) -> None:
    class Store:
        secret_provider = StaticSecretProvider(b"k" * 32)

    monkeypatch.setattr(
        codex_history,
        "_codex_history_dispatch_instance_allowed",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        codex_history,
        "_codex_history_dispatch_account_ids",
        lambda *_args, **_kwargs: ("status_admin_primary",),
    )
    monkeypatch.setattr(
        codex_history,
        "_codex_history_dispatch_routable_account_ids",
        lambda *_args, **_kwargs: ("status_admin_primary",),
    )
    monkeypatch.setattr(
        codex_history,
        "build_provider_v2_bridge",
        lambda *_args, **_kwargs: object(),
    )

    async def failed_worker(*_args, **_kwargs):
        raise RuntimeError("provider worker failed")

    monkeypatch.setattr(
        codex_history,
        "dispatch_provider_v2_batch",
        failed_worker,
    )

    result = asyncio.run(
        codex_history.dispatch_codex_history_outbox(
            Store(),  # type: ignore[arg-type]
            instance_name="TeeBotus_Logger",
            env={codex_history.HISTORY_DISPATCHER_MODE_ENV: "provider_v2"},
        )
    )

    assert result["ok"] is False
    assert result["mode"] == "provider_v2"
    assert result["items"][0]["reason"] == "provider_v2_unavailable"
    assert "provider worker failed" in result["items"][0]["error"]
