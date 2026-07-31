from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from TeeBotus.history_dispatcher_provider_v2_worker import dispatch_provider_v2_batch


class CapturingBridge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def flush_provider_v2_spool(self) -> dict[str, int]:
        return {"delivered": 0, "failed": 0}

    async def heartbeat_provider_v2(self, **kwargs: Any) -> dict[str, Any]:
        return {"ok": True}

    async def claim_provider_v2(self, worker_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                "target_delivery_id": "target_0001",
                "route_plan_id": "route_0001",
                "event_id": "evt_0001",
                "target_id": "telegram",
                "provider_id": "teebotus",
                "provider_schema_version": 1,
                "binding": {
                    "schema_version": 1,
                    "provider": "teebotus",
                    "bridge_capability": "history-dispatcher-telegram-v2",
                },
                "attempt_no": 7,
                "worker_id": worker_id,
                "capability_version": "history-dispatcher-telegram-v2",
                "claim_token": "token_" + "a" * 40,
                "claim_expires_at": "2026-07-31T00:05:00Z",
                "payload": {"text": "callback metadata"},
                "successful_recipient_refs": [],
                "open_recipient_refs": ["status_admin_primary"],
            }
        ]

    async def register_provider_v2_recipients(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("register", dict(kwargs)))
        return {
            "ok": True,
            "recipients": [
                {"recipient_ref": "status_admin_primary", "state": "pending"}
            ],
        }

    async def renew_provider_v2_claim(self, **kwargs: Any) -> dict[str, Any]:
        return {"ok": True, "claim_expires_at": "2026-07-31T00:06:00Z"}

    async def record_provider_v2_recipients(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("record", dict(kwargs)))
        return {
            "ok": True,
            "recipients": [
                {"recipient_ref": "status_admin_primary", "state": "accepted"}
            ],
        }

    async def complete_provider_v2_claim(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("complete", dict(kwargs)))
        return {"ok": True, "state": "delivered"}


def test_worker_passes_attempt_number_to_every_spoolable_callback() -> None:
    bridge = CapturingBridge()

    async def send(_claim: Mapping[str, Any], recipient_ref: str) -> dict[str, Any]:
        return {"recipient_ref": recipient_ref, "status": "accepted"}

    result = asyncio.run(
        dispatch_provider_v2_batch(
            bridge,  # type: ignore[arg-type]
            worker_id="teebotus-worker",
            recipient_refs=("status_admin_primary",),
            send=send,
            request_id_factory=lambda phase, target, attempt: (
                f"pv2-{phase}-{target}-{attempt}"
            ),
        )
    )

    assert result["ok"] is True
    assert [name for name, _kwargs in bridge.calls] == [
        "register",
        "record",
        "complete",
    ]
    assert all(kwargs["previous_attempt_no"] == 7 for _name, kwargs in bridge.calls)
