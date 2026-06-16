from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from TeeBotus.embedding import EmbeddingProvider, FakeEmbeddingProvider
from TeeBotus.runtime.accounts import AccountStore, validate_sha512_token
from TeeBotus.runtime.qdrant import (
    DEFAULT_QDRANT_TIMEOUT_SECONDS,
    QDRANT_USER_MEMORY_COLLECTION,
    QdrantError,
    QdrantOpener,
    resolve_qdrant_url,
)


QDRANT_MEMORY_PAYLOAD_SCHEMA = "teebotus_qdrant_memory_v1"


@dataclass(frozen=True)
class QdrantMemoryResult:
    memory_id: str
    account_id: str
    instance_name: str
    score: float
    payload: dict[str, Any]


@dataclass(frozen=True)
class QdrantMemoryIndex:
    url: str | None = None
    collection: str = QDRANT_USER_MEMORY_COLLECTION
    embedding_provider: EmbeddingProvider = FakeEmbeddingProvider()
    timeout_seconds: float = DEFAULT_QDRANT_TIMEOUT_SECONDS
    opener: QdrantOpener | None = None

    def index_memory(self, *, instance_name: str, account_id: str, entry: dict[str, Any]) -> str:
        account = validate_sha512_token(account_id, field_name="account_id")
        instance = _validate_instance_name(instance_name)
        memory_id = _memory_id(entry)
        point_id = qdrant_memory_point_id(instance_name=instance, account_id=account, memory_id=memory_id)
        text = _memory_embedding_text(entry)
        vector = self.embedding_provider.embed_text(text)
        _validate_vector(vector, expected_dimensions=int(self.embedding_provider.dimensions))
        payload = _memory_payload(
            instance_name=instance,
            account_id=account,
            memory_id=memory_id,
            entry=entry,
            source_text=text,
            embedding_model=self.embedding_provider.model_name,
            embedding_dimensions=self.embedding_provider.dimensions,
        )
        self._request_json(
            "PUT",
            f"/collections/{quote(_validate_collection(self.collection), safe='')}/points?wait=true",
            {
                "points": [
                    {
                        "id": point_id,
                        "vector": vector,
                        "payload": payload,
                    }
                ]
            },
        )
        return point_id

    def search(self, *, instance_name: str, account_id: str, query: str, limit: int = 5) -> tuple[QdrantMemoryResult, ...]:
        account = validate_sha512_token(account_id, field_name="account_id")
        instance = _validate_instance_name(instance_name)
        vector = self.embedding_provider.embed_text(query)
        _validate_vector(vector, expected_dimensions=int(self.embedding_provider.dimensions))
        limit_value = max(1, min(50, int(limit)))
        response = self._request_json(
            "POST",
            f"/collections/{quote(_validate_collection(self.collection), safe='')}/points/search",
            {
                "vector": vector,
                "limit": limit_value,
                "with_payload": True,
                "filter": _qdrant_scope_filter(instance_name=instance, account_id=account),
            },
        )
        raw_results = response.get("result")
        if isinstance(raw_results, dict):
            raw_results = raw_results.get("points", [])
        if not isinstance(raw_results, list):
            return ()
        results: list[QdrantMemoryResult] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            memory_id = str(payload.get("memory_id") or "").strip()
            if not memory_id:
                continue
            if payload.get("account_id") != account or payload.get("instance_name") != instance:
                continue
            try:
                score = float(item.get("score", 0.0))
            except (TypeError, ValueError):
                score = 0.0
            results.append(QdrantMemoryResult(memory_id=memory_id, account_id=account, instance_name=instance, score=score, payload=dict(payload)))
        return tuple(results)

    def delete_memory(self, *, instance_name: str, account_id: str, memory_id: str) -> None:
        account = validate_sha512_token(account_id, field_name="account_id")
        instance = _validate_instance_name(instance_name)
        point_id = qdrant_memory_point_id(instance_name=instance, account_id=account, memory_id=memory_id)
        self._request_json(
            "POST",
            f"/collections/{quote(_validate_collection(self.collection), safe='')}/points/delete?wait=true",
            {"points": [point_id]},
        )

    def delete_account(self, *, instance_name: str, account_id: str) -> None:
        account = validate_sha512_token(account_id, field_name="account_id")
        instance = _validate_instance_name(instance_name)
        self._request_json(
            "POST",
            f"/collections/{quote(_validate_collection(self.collection), safe='')}/points/delete?wait=true",
            {"filter": _qdrant_scope_filter(instance_name=instance, account_id=account)},
        )

    def rebuild(self, *, account_store: AccountStore, instance_name: str, account_id: str) -> tuple[str, ...]:
        account = validate_sha512_token(account_id, field_name="account_id")
        instance = _validate_instance_name(instance_name)
        self.delete_account(instance_name=instance, account_id=account)
        point_ids: list[str] = []
        for entry in account_store.read_memory_entries(account):
            if not isinstance(entry, dict):
                continue
            point_ids.append(self.index_memory(instance_name=instance, account_id=account, entry=entry))
        return tuple(point_ids)

    def _request_json(self, method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        target = resolve_qdrant_url(self.url)
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        request = Request(
            f"{target}{path}",
            data=body,
            method=method,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        open_url = urlopen if self.opener is None else self.opener
        try:
            response = open_url(request, timeout=self.timeout_seconds)
            status_code = int(getattr(response, "status", getattr(response, "code", 200)) or 200)
            raw = response.read() if hasattr(response, "read") else b"{}"
            close = getattr(response, "close", None)
            if callable(close):
                close()
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise QdrantError(_qdrant_request_error(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - callers get a controlled optional-index error.
            raise QdrantError(_qdrant_request_error(exc)) from exc
        if not 200 <= status_code < 300:
            raise QdrantError(f"Qdrant HTTP {status_code}")
        if not raw:
            return {}
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise QdrantError("Qdrant returned invalid JSON") from exc
        return decoded if isinstance(decoded, dict) else {}


def qdrant_memory_point_id(*, instance_name: str, account_id: str, memory_id: str) -> str:
    instance = _validate_instance_name(instance_name)
    account = validate_sha512_token(account_id, field_name="account_id")
    memory = str(memory_id or "").strip()
    if not memory:
        raise ValueError("memory_id must not be empty")
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"teebotus-memory:{instance}:{account}:{memory}"))


def _memory_payload(
    *,
    instance_name: str,
    account_id: str,
    memory_id: str,
    entry: dict[str, Any],
    source_text: str,
    embedding_model: str,
    embedding_dimensions: int,
) -> dict[str, Any]:
    keywords = entry.get("keywords") if isinstance(entry.get("keywords"), list) else []
    payload = {
        "schema": QDRANT_MEMORY_PAYLOAD_SCHEMA,
        "instance_name": instance_name,
        "account_id": account_id,
        "memory_id": memory_id,
        "kind": str(entry.get("kind") or ""),
        "memory_type": str(entry.get("memory_type") or ""),
        "importance": _float_or_zero(entry.get("importance")),
        "salience": _float_or_zero(entry.get("salience")),
        "created_at": str(entry.get("created_at") or ""),
        "updated_at": str(entry.get("updated_at") or ""),
        "valid_from": str(entry.get("valid_from") or ""),
        "valid_to": str(entry.get("valid_to") or ""),
        "source_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        "keyword_sha256": [_short_hash(str(keyword)) for keyword in keywords if str(keyword or "").strip()],
        "embedding_model": str(embedding_model or ""),
        "embedding_dimensions": int(embedding_dimensions),
    }
    return payload


def _memory_embedding_text(entry: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "summary",
        "semantic_summary",
        "fact",
        "value",
        "observation",
        "analysis",
        "plan",
        "user_text",
        "bot_text",
        "note",
        "content",
    ):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    keywords = entry.get("keywords")
    if isinstance(keywords, list):
        parts.extend(str(keyword).strip() for keyword in keywords if str(keyword or "").strip())
    return "\n".join(parts)


def _qdrant_scope_filter(*, instance_name: str, account_id: str) -> dict[str, Any]:
    return {
        "must": [
            {"key": "instance_name", "match": {"value": instance_name}},
            {"key": "account_id", "match": {"value": account_id}},
        ]
    }


def _memory_id(entry: dict[str, Any]) -> str:
    memory_id = str(entry.get("id") or "").strip()
    if not memory_id:
        raise ValueError("memory entry must contain id")
    return memory_id


def _validate_instance_name(value: str) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.@-]{1,120}", text):
        raise ValueError("instance_name contains unsupported characters")
    return text


def _validate_collection(value: str) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,255}", text):
        raise ValueError("Qdrant memory collection contains unsupported characters")
    return text


def _validate_vector(vector: list[float], *, expected_dimensions: int) -> None:
    if not isinstance(vector, list) or len(vector) != expected_dimensions:
        raise ValueError("Embedding vector dimensions do not match provider dimensions.")
    for value in vector:
        if not isinstance(value, (int, float)):
            raise ValueError("Embedding vector must contain numbers only.")


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _qdrant_request_error(exc: BaseException) -> str:
    reason = getattr(exc, "reason", "")
    if reason:
        return str(reason)
    return str(exc) or exc.__class__.__name__
