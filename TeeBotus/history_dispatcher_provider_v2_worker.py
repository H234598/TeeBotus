from __future__ import annotations

import hashlib
import inspect
import re
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Protocol

from TeeBotus.history_dispatcher_bridge import HistoryDispatcherBridge


MAX_PROVIDER_BATCH = 100
MAX_PROVIDER_RECIPIENTS = 32
_SUCCESS_STATES = frozenset({"accepted", "delivered", "acknowledged"})
_OPEN_STATES = frozenset({"pending", "claimed", "failed_retryable"})
_ALLOWED_OUTCOMES = frozenset(
    {
        "accepted",
        "delivered",
        "acknowledged",
        "failed",
        "skipped",
        "possible_duplicate",
    }
)
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_REASON_RE = re.compile(r"[^a-z0-9_]+")


class ProviderV2WorkerError(RuntimeError):
    pass


class ProviderBridge(Protocol):
    async def flush_provider_v2_spool(self) -> dict[str, int]: ...

    async def heartbeat_provider_v2(self, **kwargs: Any) -> dict[str, Any]: ...

    async def claim_provider_v2(
        self,
        worker_id: str,
        **kwargs: Any,
    ) -> list[dict[str, Any]]: ...

    async def register_provider_v2_recipients(
        self,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    async def renew_provider_v2_claim(
        self,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    async def record_provider_v2_recipients(
        self,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    async def complete_provider_v2_claim(
        self,
        **kwargs: Any,
    ) -> dict[str, Any]: ...


RequestIdFactory = Callable[[str, str, int], str]
SendCallback = Callable[
    [Mapping[str, Any], str],
    Mapping[str, Any] | Awaitable[Mapping[str, Any]],
]


def _safe_ref(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ProviderV2WorkerError(f"{field} must be a string")
    normalized = value.strip()
    if not _SAFE_REF_RE.fullmatch(normalized):
        raise ProviderV2WorkerError(f"{field} is invalid")
    return normalized


def _default_request_id(
    phase: str,
    target_delivery_id: str,
    attempt_no: int,
) -> str:
    if phase == "claim":
        return f"pv2-claim-{uuid.uuid4().hex}"
    digest = hashlib.sha256(
        f"{phase}\x00{target_delivery_id}\x00{attempt_no}".encode("utf-8")
    ).hexdigest()[:40]
    return f"pv2-{phase[:32]}-{digest}"


def _request_id(
    factory: RequestIdFactory,
    phase: str,
    target_delivery_id: str,
    attempt_no: int,
) -> str:
    return _safe_ref(
        factory(phase, target_delivery_id, attempt_no),
        field="request_id",
    )


def _empty_result(*, reason: str, ok: bool, blocked: bool) -> dict[str, Any]:
    return {
        "ok": ok,
        "blocked": blocked,
        "reason": reason,
        "claims": 0,
        "sent": 0,
        "spooled": 0,
        "items": [],
        "status_counts": {},
    }


def _normalize_recipient_refs(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)):
        raise ProviderV2WorkerError("recipient_refs must be a sequence")
    refs: list[str] = []
    seen: set[str] = set()
    for value in values:
        ref = _safe_ref(value, field="recipient_ref")
        if ref in seen:
            continue
        seen.add(ref)
        refs.append(ref)
        if len(refs) > MAX_PROVIDER_RECIPIENTS:
            raise ProviderV2WorkerError("too many provider recipients")
    return tuple(refs)


def _normalize_reason(value: object, *, default: str) -> str:
    normalized = str(value or "").strip().casefold()
    normalized = _REASON_RE.sub("_", normalized).strip("_")
    return (normalized or default)[:96]


def _normalize_send_outcome(
    value: Mapping[str, Any],
    *,
    recipient_ref: str,
) -> dict[str, Any]:
    outcome = dict(value)
    returned_ref = _safe_ref(
        outcome.get("recipient_ref", recipient_ref),
        field="recipient_ref",
    )
    if returned_ref != recipient_ref:
        raise ProviderV2WorkerError("transport result recipient mismatch")
    status = str(outcome.get("status") or "").strip().casefold()
    if status not in _ALLOWED_OUTCOMES:
        raise ProviderV2WorkerError("transport result status is invalid")
    normalized: dict[str, Any] = {
        "recipient_ref": recipient_ref,
        "status": status,
    }
    if outcome.get("possible_duplicate"):
        normalized["possible_duplicate"] = True
    message_ref_key = outcome.get("message_ref_key")
    if message_ref_key:
        normalized["message_ref_key"] = _safe_ref(
            message_ref_key,
            field="message_ref_key",
        )
    reason_code = outcome.get("reason_code")
    if reason_code:
        normalized["reason_code"] = _normalize_reason(
            reason_code,
            default="transport_result",
        )
    return normalized


async def _heartbeat(
    bridge: ProviderBridge,
    *,
    worker_id: str,
    state: str,
    details: Mapping[str, Any],
    request_id_factory: RequestIdFactory,
    phase: str,
) -> None:
    await bridge.heartbeat_provider_v2(
        worker_id=worker_id,
        state=state,
        details=dict(details),
        request_id=_request_id(request_id_factory, phase, "batch", 0),
    )


async def dispatch_provider_v2_batch(
    bridge: ProviderBridge | HistoryDispatcherBridge,
    *,
    worker_id: str,
    recipient_refs: Sequence[str],
    send: SendCallback,
    limit: int = 20,
    lease_seconds: int = 120,
    request_id_factory: RequestIdFactory | None = None,
) -> dict[str, Any]:
    """Dispatch one fail-closed provider-v2 batch.

    The function never sends while a previous encrypted callback remains
    unresolved. Recipient callbacks are persisted before target completion, and
    a spooled callback blocks completion so a later retry cannot silently erase
    an uncertain external accept window.
    """

    normalized_worker = _safe_ref(worker_id, field="worker_id")
    normalized_recipients = _normalize_recipient_refs(recipient_refs)
    factory = request_id_factory or _default_request_id
    safe_limit = max(1, min(int(limit), MAX_PROVIDER_BATCH))
    safe_lease = max(10, min(int(lease_seconds), 1800))

    flushed = await bridge.flush_provider_v2_spool()
    if int(flushed.get("failed", 0) or 0) > 0:
        await _heartbeat(
            bridge,
            worker_id=normalized_worker,
            state="blocked",
            details={"reason": "provider_callback_spool_blocked"},
            request_id_factory=factory,
            phase="heartbeat-blocked",
        )
        return _empty_result(
            reason="provider_callback_spool_blocked",
            ok=False,
            blocked=True,
        )

    if not normalized_recipients:
        await _heartbeat(
            bridge,
            worker_id=normalized_worker,
            state="idle",
            details={"reason": "no_routable_recipients"},
            request_id_factory=factory,
            phase="heartbeat-idle",
        )
        return _empty_result(
            reason="no_routable_recipients",
            ok=True,
            blocked=False,
        )

    await _heartbeat(
        bridge,
        worker_id=normalized_worker,
        state="polling",
        details={"recipient_count": len(normalized_recipients)},
        request_id_factory=factory,
        phase="heartbeat-polling",
    )
    claims = await bridge.claim_provider_v2(
        normalized_worker,
        limit=safe_limit,
        lease_seconds=safe_lease,
        request_id=_request_id(factory, "claim", "poll", 0),
    )

    items: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    sent = 0
    spooled = 0
    completed_claims = 0

    for claim in claims:
        target_delivery_id = _safe_ref(
            claim.get("target_delivery_id"),
            field="target_delivery_id",
        )
        attempt_no = max(1, int(claim.get("attempt_no") or 1))
        claim_token = str(claim.get("claim_token") or "")

        registered = await bridge.register_provider_v2_recipients(
            target_delivery_id=target_delivery_id,
            worker_id=normalized_worker,
            claim_token=claim_token,
            recipient_refs=normalized_recipients,
            request_id=_request_id(
                factory,
                "register",
                target_delivery_id,
                attempt_no,
            ),
        )
        if registered.get("spooled"):
            spooled += 1
            await _heartbeat(
                bridge,
                worker_id=normalized_worker,
                state="blocked",
                details={"reason": "recipient_registration_spooled"},
                request_id_factory=factory,
                phase="heartbeat-registration-spooled",
            )
            return {
                "ok": False,
                "blocked": True,
                "reason": "recipient_registration_spooled",
                "claims": len(claims),
                "sent": sent,
                "spooled": spooled,
                "items": items,
                "status_counts": dict(sorted(status_counts.items())),
            }

        raw_snapshots = registered.get("recipients")
        if not isinstance(raw_snapshots, list):
            raise ProviderV2WorkerError(
                "recipient registration returned invalid recipients"
            )
        states: dict[str, str] = {}
        for snapshot in raw_snapshots:
            if not isinstance(snapshot, Mapping):
                raise ProviderV2WorkerError(
                    "recipient registration row is invalid"
                )
            ref = _safe_ref(
                snapshot.get("recipient_ref"),
                field="recipient_ref",
            )
            states[ref] = str(snapshot.get("state") or "").strip().casefold()

        successful = {
            _safe_ref(value, field="successful_recipient_ref")
            for value in claim.get("successful_recipient_refs", [])
        }
        successful.update(
            ref for ref, state in states.items() if state in _SUCCESS_STATES
        )
        open_recipients = tuple(
            ref
            for ref in normalized_recipients
            if ref not in successful and states.get(ref, "pending") in _OPEN_STATES
        )

        outcomes: list[dict[str, Any]] = []
        for recipient_ref in open_recipients:
            await bridge.renew_provider_v2_claim(
                target_delivery_id=target_delivery_id,
                worker_id=normalized_worker,
                claim_token=claim_token,
                lease_seconds=safe_lease,
                request_id=_request_id(
                    factory,
                    f"renew-{recipient_ref}",
                    target_delivery_id,
                    attempt_no,
                ),
            )
            try:
                send_result = send(claim, recipient_ref)
                if inspect.isawaitable(send_result):
                    send_result = await send_result
                if not isinstance(send_result, Mapping):
                    raise ProviderV2WorkerError(
                        "transport result must be an object"
                    )
                outcome = _normalize_send_outcome(
                    send_result,
                    recipient_ref=recipient_ref,
                )
            except Exception as exc:  # transport adapters expose heterogeneous errors.
                outcome = {
                    "recipient_ref": recipient_ref,
                    "status": "failed",
                    "reason_code": _normalize_reason(
                        f"send_error_{type(exc).__name__}",
                        default="send_error",
                    ),
                }
            outcomes.append(outcome)
            items.append(
                {
                    "target_delivery_id": target_delivery_id,
                    **outcome,
                }
            )
            status_counts[str(outcome["status"])] += 1
            sent += 1

        if outcomes:
            recorded = await bridge.record_provider_v2_recipients(
                target_delivery_id=target_delivery_id,
                worker_id=normalized_worker,
                claim_token=claim_token,
                outcomes=tuple(outcomes),
                request_id=_request_id(
                    factory,
                    "record",
                    target_delivery_id,
                    attempt_no,
                ),
            )
            if recorded.get("spooled"):
                spooled += 1
                await _heartbeat(
                    bridge,
                    worker_id=normalized_worker,
                    state="blocked",
                    details={"reason": "recipient_callback_spooled"},
                    request_id_factory=factory,
                    phase="heartbeat-record-spooled",
                )
                return {
                    "ok": False,
                    "blocked": True,
                    "reason": "recipient_callback_spooled",
                    "claims": len(claims),
                    "sent": sent,
                    "spooled": spooled,
                    "items": items,
                    "status_counts": dict(sorted(status_counts.items())),
                }

        completed = await bridge.complete_provider_v2_claim(
            target_delivery_id=target_delivery_id,
            worker_id=normalized_worker,
            claim_token=claim_token,
            request_id=_request_id(
                factory,
                "complete",
                target_delivery_id,
                attempt_no,
            ),
        )
        if completed.get("spooled"):
            spooled += 1
            await _heartbeat(
                bridge,
                worker_id=normalized_worker,
                state="blocked",
                details={"reason": "completion_callback_spooled"},
                request_id_factory=factory,
                phase="heartbeat-completion-spooled",
            )
            return {
                "ok": False,
                "blocked": True,
                "reason": "completion_callback_spooled",
                "claims": len(claims),
                "sent": sent,
                "spooled": spooled,
                "items": items,
                "status_counts": dict(sorted(status_counts.items())),
            }
        completed_claims += 1

    await _heartbeat(
        bridge,
        worker_id=normalized_worker,
        state="idle",
        details={
            "claims": len(claims),
            "completed": completed_claims,
            "sent": sent,
        },
        request_id_factory=factory,
        phase="heartbeat-idle-complete",
    )
    failed = status_counts.get("failed", 0)
    return {
        "ok": failed == 0,
        "blocked": False,
        "reason": "",
        "claims": len(claims),
        "sent": sent,
        "spooled": spooled,
        "items": items,
        "status_counts": dict(sorted(status_counts.items())),
    }
