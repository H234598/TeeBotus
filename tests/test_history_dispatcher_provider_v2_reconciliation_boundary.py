from __future__ import annotations

import asyncio
from typing import Any

import pytest

from TeeBotus.history_dispatcher_bridge import TEEBOTUS_CAPABILITY_V2
from TeeBotus.history_dispatcher_provider_v2_codex import (
    provider_v2_claim_to_legacy_item,
)
from TeeBotus.history_dispatcher_provider_v2_worker import (
    ProviderV2WorkerError,
    dispatch_provider_v2_batch,
)
from TeeBotus.history_dispatcher_bridge import HistoryDispatcherProtocolError


def _reconciliation_claim() -> dict[str, Any]:
    return {
        "target_delivery_id": "target_0001",
        "route_plan_id": "route_0001",
        "event_id": "evt_0001",
        "target_id": "telegram",
        "provider_id": "teebotus",
        "provider_schema_version": 1,
        "binding": {
            "schema_version": 1,
            "provider": "teebotus",
            "bridge_capability": TEEBOTUS_CAPABILITY_V2,
        },
        "attempt_no": 2,
        "worker_id": "teebotus-worker",
        "capability_version": TEEBOTUS_CAPABILITY_V2,
        "claim_token": "token_" + "a" * 40,
        "claim_expires_at": "2026-07-31T00:05:00Z",
        "payload": {
            "history_kind": "task_completion",
            "text": "must never be sent",
            "timestamp": "2026-07-31T00:00:00Z",
            "project_id": "proj_boundary",
            "project_label": "Boundary",
            "source_ordinal": 1,
        },
        "successful_recipient_refs": [],
        "open_recipient_refs": ["status_admin_primary"],
        "reconciliation_only": True,
    }


def test_transport_adapter_rejects_reconciliation_only_claim() -> None:
    with pytest.raises(HistoryDispatcherProtocolError, match="reconciliation"):
        provider_v2_claim_to_legacy_item(_reconciliation_claim())


class ReconciliationBridge:
    async def flush_provider_v2_spool(self) -> dict[str, int]:
        return {"delivered": 0, "failed": 0}

    async def heartbeat_provider_v2(self, **_kwargs: Any) -> dict[str, Any]:
        return {"ok": True}

    async def claim_provider_v2(
        self,
        worker_id: str,
        **_kwargs: Any,
    ) -> list[dict[str, Any]]:
        claim = _reconciliation_claim()
        claim["worker_id"] = worker_id
        return [claim]


def test_worker_rejects_reconciliation_only_claim_before_registration_or_send() -> None:
    bridge = ReconciliationBridge()
    sends = 0

    async def send(_claim: dict[str, Any], _recipient_ref: str) -> dict[str, Any]:
        nonlocal sends
        sends += 1
        return {"status": "accepted"}

    with pytest.raises(ProviderV2WorkerError, match="reconciliation"):
        asyncio.run(
            dispatch_provider_v2_batch(
                bridge,  # type: ignore[arg-type]
                worker_id="teebotus-worker",
                recipient_refs=("status_admin_primary",),
                send=send,
            )
        )

    assert sends == 0
