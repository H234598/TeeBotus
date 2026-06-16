from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from TeeBotus.embedding import EmbeddingProvider, FakeEmbeddingProvider, HFEmbeddingProvider
from TeeBotus.runtime.qdrant import (
    DEFAULT_BIBLIOTHEKAR_EMBEDDING_DIMENSIONS,
    DEFAULT_QDRANT_TIMEOUT_SECONDS,
    QDRANT_BIBLIOTHEKAR_COLLECTION,
    QdrantError,
    QdrantOpener,
    resolve_qdrant_url,
)


BGE_M3_EMBEDDING_MODEL = "BAAI/bge-m3"
BGE_M3_EMBEDDING_DIMENSIONS = 1024
QDRANT_BIBLIOTHEKAR_PAYLOAD_SCHEMA = "teebotus_qdrant_bibliothekar_v1"


@dataclass(frozen=True)
class QdrantBibliothekarResult:
    chunk_id: str
    instance_name: str
    score: float
    payload: dict[str, Any]


@dataclass(frozen=True)
class QdrantBibliothekarIndex:
    url: str | None = None
    collection: str = QDRANT_BIBLIOTHEKAR_COLLECTION
    embedding_provider: EmbeddingProvider = field(
        default_factory=lambda: FakeEmbeddingProvider(
            model_name="teebotus-fake-bibliothekar-embedding-v1",
            dimensions=DEFAULT_BIBLIOTHEKAR_EMBEDDING_DIMENSIONS,
        )
    )
    timeout_seconds: float = DEFAULT_QDRANT_TIMEOUT_SECONDS
    opener: QdrantOpener | None = None

    def index_chunks(self, *, instance_name: str, chunks: Iterable[dict[str, Any]]) -> tuple[str, ...]:
        instance = _validate_instance_name(instance_name)
        points: list[dict[str, Any]] = []
        point_ids: list[str] = []
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            chunk_id = _chunk_id(chunk)
            point_id = qdrant_bibliothekar_point_id(instance_name=instance, chunk_id=chunk_id)
            text = str(chunk.get("text") or "")
            vector = self.embedding_provider.embed_text(text)
            _validate_vector(vector, expected_dimensions=int(self.embedding_provider.dimensions))
            points.append(
                {
                    "id": point_id,
                    "vector": vector,
                    "payload": _chunk_payload(
                        instance_name=instance,
                        chunk_id=chunk_id,
                        chunk=chunk,
                        source_text=text,
                        embedding_model=self.embedding_provider.model_name,
                        embedding_dimensions=self.embedding_provider.dimensions,
                    ),
                }
            )
            point_ids.append(point_id)
        if not points:
            return ()
        self._request_json(
            "PUT",
            f"/collections/{quote(_validate_collection(self.collection), safe='')}/points?wait=true",
            {"points": points},
        )
        return tuple(point_ids)

    def search(self, *, instance_name: str, query: str, limit: int = 5) -> tuple[QdrantBibliothekarResult, ...]:
        instance = _validate_instance_name(instance_name)
        vector = self.embedding_provider.embed_text(query)
        _validate_vector(vector, expected_dimensions=int(self.embedding_provider.dimensions))
        response = self._request_json(
            "POST",
            f"/collections/{quote(_validate_collection(self.collection), safe='')}/points/search",
            {
                "vector": vector,
                "limit": max(1, min(50, int(limit))),
                "with_payload": True,
                "filter": {"must": [{"key": "instance_name", "match": {"value": instance}}]},
            },
        )
        raw_results = response.get("result")
        if isinstance(raw_results, dict):
            raw_results = raw_results.get("points", [])
        if not isinstance(raw_results, list):
            return ()
        results: list[QdrantBibliothekarResult] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            if payload.get("instance_name") != instance:
                continue
            chunk_id = str(payload.get("chunk_id") or "").strip()
            if not chunk_id:
                continue
            try:
                score = float(item.get("score", 0.0))
            except (TypeError, ValueError):
                score = 0.0
            results.append(QdrantBibliothekarResult(chunk_id=chunk_id, instance_name=instance, score=score, payload=dict(payload)))
        return tuple(results)

    def delete_instance(self, *, instance_name: str) -> None:
        instance = _validate_instance_name(instance_name)
        self._request_json(
            "POST",
            f"/collections/{quote(_validate_collection(self.collection), safe='')}/points/delete?wait=true",
            {"filter": {"must": [{"key": "instance_name", "match": {"value": instance}}]}},
        )

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
        except Exception as exc:  # noqa: BLE001 - optional Qdrant index reports controlled errors.
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


def bge_m3_embedding_provider() -> HFEmbeddingProvider:
    return HFEmbeddingProvider(model_name=BGE_M3_EMBEDDING_MODEL, dimensions=BGE_M3_EMBEDDING_DIMENSIONS)


def qdrant_bibliothekar_point_id(*, instance_name: str, chunk_id: str) -> str:
    instance = _validate_instance_name(instance_name)
    chunk = str(chunk_id or "").strip()
    if not chunk:
        raise ValueError("chunk_id must not be empty")
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"teebotus-bibliothekar:{instance}:{chunk}"))


def _chunk_payload(
    *,
    instance_name: str,
    chunk_id: str,
    chunk: dict[str, Any],
    source_text: str,
    embedding_model: str,
    embedding_dimensions: int,
) -> dict[str, Any]:
    return {
        "schema": QDRANT_BIBLIOTHEKAR_PAYLOAD_SCHEMA,
        "instance_name": instance_name,
        "chunk_id": chunk_id,
        "document_id": str(chunk.get("document_id") or ""),
        "source_id": str(chunk.get("source_id") or ""),
        "title": str(chunk.get("title") or ""),
        "author": str(chunk.get("author") or ""),
        "relative_path": str(chunk.get("relative_path") or chunk.get("file_path") or ""),
        "file_path": str(chunk.get("file_path") or chunk.get("relative_path") or ""),
        "file_sha256": str(chunk.get("file_sha256") or ""),
        "file_type": str(chunk.get("file_type") or ""),
        "language": str(chunk.get("language") or ""),
        "locator": str(chunk.get("locator") or ""),
        "page_start": chunk.get("page_start"),
        "page_end": chunk.get("page_end"),
        "chapter": str(chunk.get("chapter") or ""),
        "section": str(chunk.get("section") or ""),
        "license": str(chunk.get("license") or ""),
        "ingested_at": str(chunk.get("ingested_at") or ""),
        "chunk_index": chunk.get("chunk_index"),
        "topics": list(chunk.get("topics", [])) if isinstance(chunk.get("topics"), list) else [],
        "categories": list(chunk.get("categories", [])) if isinstance(chunk.get("categories"), list) else [],
        "text_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        "embedding_model": str(embedding_model or ""),
        "embedding_dimensions": int(embedding_dimensions),
    }


def _chunk_id(chunk: dict[str, Any]) -> str:
    chunk_id = str(chunk.get("chunk_id") or "").strip()
    if not chunk_id:
        raise ValueError("bibliothekar chunk must contain chunk_id")
    return chunk_id


def _validate_instance_name(value: str) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.@-]{1,120}", text):
        raise ValueError("instance_name contains unsupported characters")
    return text


def _validate_collection(value: str) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,255}", text):
        raise ValueError("Qdrant bibliothekar collection contains unsupported characters")
    return text


def _validate_vector(vector: list[float], *, expected_dimensions: int) -> None:
    if not isinstance(vector, list) or len(vector) != expected_dimensions:
        raise ValueError("Embedding vector dimensions do not match provider dimensions.")
    for value in vector:
        if not isinstance(value, (int, float)):
            raise ValueError("Embedding vector must contain numbers only.")


def _qdrant_request_error(exc: BaseException) -> str:
    reason = getattr(exc, "reason", "")
    if reason:
        return str(reason)
    return str(exc) or exc.__class__.__name__
