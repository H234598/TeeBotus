from __future__ import annotations

from pathlib import Path


BRIDGE = Path("TeeBotus/history_dispatcher_bridge.py")
WORKER = Path("TeeBotus/history_dispatcher_provider_v2_worker.py")


def replace_once(source: str, old: str, new: str, *, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


def patch_bridge() -> None:
    source = BRIDGE.read_text(encoding="utf-8")
    source = replace_once(
        source,
        '    "provider.v2.claim",\n    "provider.v2.renew",\n',
        '    "provider.v2.claim",\n    "provider.v2.reclaim",\n    "provider.v2.renew",\n',
        label="provider operations",
    )
    source = replace_once(
        source,
        """def _claim_token(value: object) -> str:
    if not isinstance(value, str) or not _SAFE_CLAIM_TOKEN_RE.fullmatch(value):
        raise HistoryDispatcherProtocolError("claim_token is invalid")
    return value


def _canonical_json_bytes(value: object, *, max_bytes: int) -> bytes:
""",
        """def _claim_token(value: object) -> str:
    if not isinstance(value, str) or not _SAFE_CLAIM_TOKEN_RE.fullmatch(value):
        raise HistoryDispatcherProtocolError("claim_token is invalid")
    return value


def _positive_attempt_no(value: object, *, field: str) -> int:
    if isinstance(value, bool):
        raise HistoryDispatcherProtocolError(f"{field} must be an integer")
    try:
        attempt_no = int(value)
    except (TypeError, ValueError) as exc:
        raise HistoryDispatcherProtocolError(
            f"{field} must be an integer"
        ) from exc
    if attempt_no < 1 or attempt_no > 2**31 - 1:
        raise HistoryDispatcherProtocolError(f"{field} is out of range")
    return attempt_no


def _provider_reclaim_required(exc: HistoryDispatcherError) -> bool:
    message = str(exc).strip().casefold()
    return any(
        marker in message
        for marker in (
            "claim has expired",
            "not actively claimed",
            "claim maximum lifetime has elapsed",
        )
    )


def _provider_reclaim_request_id(event_id: str, attempt_no: int) -> str:
    digest = hashlib.sha256(
        f"reclaim\\x00{event_id}\\x00{attempt_no}".encode("utf-8")
    ).hexdigest()[:40]
    return _request_id(f"pv2-reclaim-{digest}")


def _provider_rebound_request_id(
    event_id: str,
    operation: str,
    attempt_no: int,
) -> str:
    digest = hashlib.sha256(
        f"rebound\\x00{event_id}\\x00{operation}\\x00{attempt_no}".encode("utf-8")
    ).hexdigest()[:40]
    return _request_id(f"pv2-rebound-{digest}")


def _canonical_json_bytes(value: object, *, max_bytes: int) -> bytes:
""",
        label="reclaim helpers",
    )
    source = replace_once(
        source,
        """        normalized = {
            "event_id": event_id,
            "operation": operation,
            "request_id": request_id,
            "body": normalized_body,
        }
        _canonical_json_bytes(
""",
        """        normalized = {
            "event_id": event_id,
            "operation": operation,
            "request_id": request_id,
            "body": normalized_body,
        }
        raw_reclaim = event_data.get("reclaim")
        if raw_reclaim is not None:
            if not isinstance(raw_reclaim, Mapping):
                raise ValueError("provider callback reclaim must be an object")
            reclaim = dict(raw_reclaim)
            expected_fields = {
                "target_delivery_id",
                "provider_id",
                "worker_id",
                "capability_version",
                "previous_attempt_no",
            }
            if set(reclaim) != expected_fields:
                raise ValueError("provider callback reclaim fields are invalid")
            target_delivery_id = _opaque_ref(
                reclaim.get("target_delivery_id"),
                field="target_delivery_id",
            )
            worker_id = _opaque_ref(reclaim.get("worker_id"), field="worker_id")
            provider_id = _opaque_ref(
                reclaim.get("provider_id"),
                field="provider_id",
            )
            capability = _opaque_ref(
                reclaim.get("capability_version"),
                field="capability_version",
            )
            if provider_id != "teebotus" or capability != TEEBOTUS_CAPABILITY_V2:
                raise ValueError("provider callback reclaim binding is invalid")
            if _opaque_ref(
                normalized_body.get("target_delivery_id"),
                field="target_delivery_id",
            ) != target_delivery_id:
                raise ValueError("provider callback reclaim target mismatch")
            if _opaque_ref(
                normalized_body.get("worker_id"),
                field="worker_id",
            ) != worker_id:
                raise ValueError("provider callback reclaim worker mismatch")
            normalized["reclaim"] = {
                "target_delivery_id": target_delivery_id,
                "provider_id": provider_id,
                "worker_id": worker_id,
                "capability_version": capability,
                "previous_attempt_no": _positive_attempt_no(
                    reclaim.get("previous_attempt_no"),
                    field="previous_attempt_no",
                ),
            }
        _canonical_json_bytes(
""",
        label="reclaim envelope validation",
    )
    source = replace_once(
        source,
        """        return target

    def events(
""",
        """        return target

    def rewrite(self, path: Path, event: Mapping[str, Any]) -> Path:
        target = Path(path)
        if (
            target.parent != self.root
            or target.suffix != ".bin"
            or target.is_symlink()
            or not target.is_file()
        ):
            raise ValueError("provider callback rewrite path is unsafe")
        event_data = self._validate_envelope(event)
        if str(event_data["event_id"]) != target.stem:
            raise ValueError("provider callback rewrite event id mismatch")
        temporary = self.root / (
            f".{target.stem}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        )
        encrypted = self._encrypt(event_data)
        try:
            with temporary.open("wb") as handle:
                handle.write(encrypted)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
            _fsync_directory(self.root)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        return target

    def events(
""",
        label="spool rewrite",
    )
    source = replace_once(
        source,
        """        return claims

    async def renew_provider_v2_claim(
""",
        """        return claims

    async def reclaim_provider_v2_callback(
        self,
        *,
        target_delivery_id: str,
        worker_id: str,
        previous_attempt_no: int,
        lease_seconds: int = 120,
        request_id: str | None = None,
    ) -> dict[str, Any] | None:
        normalized_target = _opaque_ref(
            target_delivery_id,
            field="target_delivery_id",
        )
        normalized_worker = _opaque_ref(worker_id, field="worker_id")
        previous_attempt = _positive_attempt_no(
            previous_attempt_no,
            field="previous_attempt_no",
        )
        response = await self.client.request_async(
            "provider.v2.reclaim",
            {
                "target_delivery_id": normalized_target,
                "provider_id": "teebotus",
                "worker_id": normalized_worker,
                "capability_version": TEEBOTUS_CAPABILITY_V2,
                "previous_attempt_no": previous_attempt,
                "lease_seconds": max(10, min(int(lease_seconds), 1800)),
            },
            request_id=_request_id(request_id),
        )
        data = _provider_response_data(
            response,
            operation="provider.v2.reclaim",
        )
        if data.get("schema_version") != PROVIDER_API_SCHEMA_VERSION:
            raise HistoryDispatcherProtocolError(
                "History-Dispatcher provider reclaim schema mismatch"
            )
        raw_claims = data.get("claims")
        if not isinstance(raw_claims, list) or len(raw_claims) > 1:
            raise HistoryDispatcherProtocolError(
                "History-Dispatcher provider reclaim returned invalid claims"
            )
        if not raw_claims:
            return None
        raw_claim = raw_claims[0]
        if not isinstance(raw_claim, Mapping):
            raise HistoryDispatcherProtocolError(
                "History-Dispatcher provider reclaim claim is invalid"
            )
        claim = dict(raw_claim)
        if (
            claim.get("target_delivery_id") != normalized_target
            or claim.get("target_id") != "telegram"
            or claim.get("provider_id") != "teebotus"
            or claim.get("capability_version") != TEEBOTUS_CAPABILITY_V2
            or claim.get("worker_id") != normalized_worker
            or claim.get("reconciliation_only") is not True
        ):
            raise HistoryDispatcherProtocolError(
                "History-Dispatcher provider reclaim identity mismatch"
            )
        binding = claim.get("binding")
        if (
            not isinstance(binding, Mapping)
            or binding.get("provider") != "teebotus"
            or binding.get("bridge_capability") != TEEBOTUS_CAPABILITY_V2
        ):
            raise HistoryDispatcherProtocolError(
                "History-Dispatcher provider reclaim binding mismatch"
            )
        attempt_no = _positive_attempt_no(
            claim.get("attempt_no"),
            field="attempt_no",
        )
        if attempt_no != previous_attempt + 1:
            raise HistoryDispatcherProtocolError(
                "History-Dispatcher provider reclaim attempt mismatch"
            )
        claim["attempt_no"] = attempt_no
        claim["claim_token"] = _claim_token(claim.get("claim_token"))
        if not isinstance(claim.get("payload"), Mapping):
            raise HistoryDispatcherProtocolError(
                "History-Dispatcher provider reclaim payload is invalid"
            )
        claim["payload"] = dict(claim["payload"])
        claim["successful_recipient_refs"] = _recipient_refs(
            claim.get("successful_recipient_refs"),
            field="successful_recipient_refs",
        )
        claim["open_recipient_refs"] = _recipient_refs(
            claim.get("open_recipient_refs"),
            field="open_recipient_refs",
        )
        return claim

    async def renew_provider_v2_claim(
""",
        label="bridge reclaim method",
    )
    source = replace_once(
        source,
        """    async def _provider_callback(
        self,
        operation: str,
        body: Mapping[str, Any],
        *,
        request_id: str | None,
    ) -> dict[str, Any]:
""",
        """    async def _provider_callback(
        self,
        operation: str,
        body: Mapping[str, Any],
        *,
        request_id: str | None,
        previous_attempt_no: int | None = None,
    ) -> dict[str, Any]:
""",
        label="provider callback signature",
    )
    source = replace_once(
        source,
        """            path = self.provider_spool.enqueue(
                {
                    "operation": operation,
                    "request_id": normalized_request_id,
                    "body": normalized_body,
                }
            )
""",
        """            envelope: dict[str, Any] = {
                "operation": operation,
                "request_id": normalized_request_id,
                "body": normalized_body,
            }
            if previous_attempt_no is not None:
                envelope["reclaim"] = {
                    "target_delivery_id": _opaque_ref(
                        normalized_body.get("target_delivery_id"),
                        field="target_delivery_id",
                    ),
                    "provider_id": "teebotus",
                    "worker_id": _opaque_ref(
                        normalized_body.get("worker_id"),
                        field="worker_id",
                    ),
                    "capability_version": TEEBOTUS_CAPABILITY_V2,
                    "previous_attempt_no": _positive_attempt_no(
                        previous_attempt_no,
                        field="previous_attempt_no",
                    ),
                }
            path = self.provider_spool.enqueue(envelope)
""",
        label="provider callback reclaim metadata",
    )
    for method, anchor in (
        ("register_provider_v2_recipients", "recipient_refs: Sequence[str],"),
        ("record_provider_v2_recipients", "outcomes: Sequence[Mapping[str, Any]],"),
        ("complete_provider_v2_claim", "claim_token: str,"),
    ):
        start = source.index(f"    async def {method}(")
        end = source.index("    async def ", start + 10)
        block = source[start:end]
        if "previous_attempt_no:" not in block:
            block = replace_once(
                block,
                f"        {anchor}\n        request_id: str | None = None,",
                f"        {anchor}\n        previous_attempt_no: int | None = None,\n        request_id: str | None = None,",
                label=f"{method} attempt parameter",
            )
        block = replace_once(
            block,
            "            request_id=request_id,\n        )",
            "            request_id=request_id,\n            previous_attempt_no=previous_attempt_no,\n        )",
            label=f"{method} callback attempt",
        )
        source = source[:start] + block + source[end:]
    source = replace_once(
        source,
        """    async def flush_provider_v2_spool(self) -> dict[str, int]:
        if self.provider_spool is None:
            return {"delivered": 0, "failed": 0}
        with self.provider_spool.flush_lock():
            delivered = failed = 0
            for path, envelope in self.provider_spool.events():
                try:
                    response = await self.client.request_async(
                        str(envelope["operation"]),
                        dict(envelope["body"]),
                        request_id=str(envelope["request_id"]),
                    )
                    _provider_response_data(
                        response,
                        operation=str(envelope["operation"]),
                    )
                except HistoryDispatcherError:
                    failed += 1
                    break
                self.provider_spool.discard(path)
                delivered += 1
            return {"delivered": delivered, "failed": failed}
""",
        """    async def flush_provider_v2_spool(self) -> dict[str, int]:
        if self.provider_spool is None:
            return {"delivered": 0, "failed": 0}
        with self.provider_spool.flush_lock():
            delivered = failed = 0
            for path, envelope in self.provider_spool.events():
                operation = str(envelope["operation"])
                try:
                    response = await self.client.request_async(
                        operation,
                        dict(envelope["body"]),
                        request_id=str(envelope["request_id"]),
                    )
                    _provider_response_data(response, operation=operation)
                except HistoryDispatcherError as exc:
                    reclaim = envelope.get("reclaim")
                    if not _provider_reclaim_required(exc) or not isinstance(
                        reclaim,
                        Mapping,
                    ):
                        failed += 1
                        break
                    try:
                        previous_attempt = _positive_attempt_no(
                            reclaim.get("previous_attempt_no"),
                            field="previous_attempt_no",
                        )
                        reclaimed = await self.reclaim_provider_v2_callback(
                            target_delivery_id=str(
                                reclaim.get("target_delivery_id") or ""
                            ),
                            worker_id=str(reclaim.get("worker_id") or ""),
                            previous_attempt_no=previous_attempt,
                            lease_seconds=120,
                            request_id=_provider_reclaim_request_id(
                                str(envelope["event_id"]),
                                previous_attempt,
                            ),
                        )
                    except HistoryDispatcherError:
                        failed += 1
                        break
                    if reclaimed is None:
                        failed += 1
                        break
                    rebound = dict(envelope)
                    rebound_body = dict(envelope["body"])
                    rebound_body["claim_token"] = str(reclaimed["claim_token"])
                    rebound["body"] = rebound_body
                    rebound["request_id"] = _provider_rebound_request_id(
                        str(envelope["event_id"]),
                        operation,
                        int(reclaimed["attempt_no"]),
                    )
                    rebound_reclaim = dict(reclaim)
                    rebound_reclaim["previous_attempt_no"] = int(
                        reclaimed["attempt_no"]
                    )
                    rebound["reclaim"] = rebound_reclaim
                    self.provider_spool.rewrite(path, rebound)
                    try:
                        response = await self.client.request_async(
                            operation,
                            rebound_body,
                            request_id=str(rebound["request_id"]),
                        )
                        _provider_response_data(response, operation=operation)
                    except HistoryDispatcherError:
                        failed += 1
                        break
                self.provider_spool.discard(path)
                delivered += 1
            return {"delivered": delivered, "failed": failed}
""",
        label="provider spool reclaim flush",
    )
    BRIDGE.write_text(source, encoding="utf-8")


def patch_worker() -> None:
    source = WORKER.read_text(encoding="utf-8")
    for marker in (
        "recipient_refs=normalized_recipients,",
        "outcomes=tuple(outcomes),",
        "claim_token=claim_token,\n            request_id=_request_id(\n                factory,\n                \"complete\",",
    ):
        if marker.startswith("claim_token"):
            source = replace_once(
                source,
                marker,
                "claim_token=claim_token,\n            previous_attempt_no=attempt_no,\n            request_id=_request_id(\n                factory,\n                \"complete\",",
                label="worker complete attempt metadata",
            )
        else:
            source = replace_once(
                source,
                marker,
                marker + "\n            previous_attempt_no=attempt_no,",
                label=f"worker {marker.split('=')[0]} attempt metadata",
            )
    WORKER.write_text(source, encoding="utf-8")


def main() -> None:
    patch_bridge()
    patch_worker()


if __name__ == "__main__":
    main()
