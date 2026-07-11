from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from TeeBotus.runtime.accounts import AccountStore, validate_sha512_token
from TeeBotus.runtime.qdrant import QdrantError
from TeeBotus.runtime.qdrant_memory import QdrantMemoryIndex


@dataclass(frozen=True)
class MemorySearchConfig:
    semantic_enabled: bool = False
    semantic_backend: str = ""
    local_limit: int = 8
    semantic_limit: int = 8

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "MemorySearchConfig":
        source = data or {}
        return cls(
            semantic_enabled=_truthy(source.get("semantic_enabled")),
            semantic_backend=str(source.get("semantic_backend") or "").strip().casefold(),
            local_limit=_positive_int(source.get("local_limit"), default=8),
            semantic_limit=_positive_int(source.get("semantic_limit"), default=8),
        )


@dataclass(frozen=True)
class MemoryCandidate:
    memory_id: str
    score: float
    sources: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class MemorySearchResult:
    entries: tuple[dict[str, Any], ...]
    candidates: tuple[MemoryCandidate, ...]
    semantic_used: bool = False
    semantic_error: str = ""


@dataclass(frozen=True)
class KeywordMemorySearch:
    account_store: AccountStore

    def search(
        self,
        account_id: str,
        query_text: str,
        *,
        limit: int = 8,
        exclude_ids: Iterable[str] = (),
    ) -> tuple[MemoryCandidate, ...]:
        account = validate_sha512_token(account_id, field_name="account_id")
        search_limit = _nonnegative_int(limit, default=8)
        if search_limit == 0:
            return ()
        excluded = {str(memory_id or "").strip() for memory_id in exclude_ids if str(memory_id or "").strip()}
        ranked_ids = self.account_store.rank_structured_memory_ids(account, query_text=query_text, limit=search_limit, exclude_ids=excluded)
        total = max(1, len(ranked_ids))
        return tuple(
            MemoryCandidate(memory_id=memory_id, score=1.0 - (index / (total + 1)), sources=("local",))
            for index, memory_id in enumerate(ranked_ids)
        )


@dataclass(frozen=True)
class QdrantMemorySearch:
    qdrant_index: QdrantMemoryIndex
    instance_name: str

    def search(
        self,
        account_id: str,
        query_text: str,
        *,
        limit: int = 8,
        exclude_ids: Iterable[str] = (),
    ) -> tuple[MemoryCandidate, ...]:
        account = validate_sha512_token(account_id, field_name="account_id")
        search_limit = _nonnegative_int(limit, default=8)
        if search_limit == 0:
            return ()
        excluded = {str(memory_id or "").strip() for memory_id in exclude_ids if str(memory_id or "").strip()}
        return tuple(
            MemoryCandidate(memory_id=memory_id, score=result.score, sources=("qdrant",))
            for result in self.qdrant_index.search(
                instance_name=self.instance_name,
                account_id=account,
                query=query_text,
                limit=search_limit,
            )
            if (memory_id := str(result.memory_id or "").strip()) and memory_id not in excluded
        )


@dataclass(frozen=True)
class MemorySearchService:
    account_store: AccountStore
    instance_name: str
    config: MemorySearchConfig = MemorySearchConfig()
    qdrant_index: QdrantMemoryIndex | None = None

    def search(
        self,
        account_id: str,
        query_text: str,
        *,
        limit: int = 8,
        exclude_ids: Iterable[str] = (),
    ) -> MemorySearchResult:
        account = validate_sha512_token(account_id, field_name="account_id")
        max_results = _nonnegative_int(limit, default=8)
        if max_results == 0:
            return MemorySearchResult(entries=(), candidates=())
        excluded = {str(memory_id or "").strip() for memory_id in exclude_ids if str(memory_id or "").strip()}
        local_candidates = KeywordMemorySearch(self.account_store).search(account, query_text, limit=self.config.local_limit, exclude_ids=excluded)
        semantic_candidates: tuple[MemoryCandidate, ...] = ()
        semantic_used = False
        semantic_error = ""
        if self.config.semantic_enabled and self.config.semantic_backend == "qdrant" and self.qdrant_index is not None:
            semantic_used = True
            try:
                semantic_candidates = QdrantMemorySearch(self.qdrant_index, self.instance_name).search(
                    account,
                    query_text,
                    limit=self.config.semantic_limit,
                    exclude_ids=excluded,
                )
            except (QdrantError, ValueError, RuntimeError) as exc:
                semantic_error = str(exc)
                semantic_candidates = ()
        merged = merge_memory_candidates(
            local_candidates,
            semantic_candidates,
            limit=max(max_results, len(local_candidates) + len(semantic_candidates)),
        )
        selected_ids = [candidate.memory_id for candidate in merged]
        entries_by_id = {
            str(entry.get("id") or "").strip(): entry
            for entry in self.account_store.read_memory_entries_by_ids(account, selected_ids)
            if isinstance(entry, dict) and str(entry.get("id") or "").strip()
        }
        verified_candidates = tuple(candidate for candidate in merged if candidate.memory_id in entries_by_id)[:max_results]
        returned_ids = [candidate.memory_id for candidate in verified_candidates]
        entries = tuple(entries_by_id[memory_id] for memory_id in returned_ids)
        if returned_ids:
            self.account_store.mark_structured_memory_accessed(account, returned_ids)
        return MemorySearchResult(entries=entries, candidates=verified_candidates, semantic_used=semantic_used, semantic_error=semantic_error)


def merge_memory_candidates(*candidate_groups: Iterable[MemoryCandidate], limit: int = 8) -> tuple[MemoryCandidate, ...]:
    max_results = _nonnegative_int(limit, default=8)
    if max_results == 0:
        return ()
    merged: dict[str, MemoryCandidate] = {}
    order: dict[str, int] = {}
    counter = 0
    for candidates in candidate_groups:
        for candidate in candidates:
            memory_id = str(candidate.memory_id or "").strip()
            if not memory_id:
                continue
            if memory_id not in order:
                order[memory_id] = counter
                counter += 1
            existing = merged.get(memory_id)
            sources = tuple(dict.fromkeys(candidate.sources or ("unknown",)))
            if existing is None:
                merged[memory_id] = MemoryCandidate(memory_id=memory_id, score=float(candidate.score), sources=sources)
                continue
            combined_sources = tuple(dict.fromkeys([*existing.sources, *sources]))
            combined_score = max(existing.score, float(candidate.score)) + 0.15 * (len(combined_sources) - len(existing.sources))
            merged[memory_id] = MemoryCandidate(memory_id=memory_id, score=combined_score, sources=combined_sources)
    return tuple(sorted(merged.values(), key=lambda candidate: (-candidate.score, order[candidate.memory_id]))[:max_results])


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "true", "yes", "ja", "on", "enabled"}


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, parsed)


def _nonnegative_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0, parsed)
