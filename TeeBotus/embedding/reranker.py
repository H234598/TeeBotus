from __future__ import annotations

import re
from dataclasses import dataclass

from TeeBotus.embedding.base import RerankResult


@dataclass(frozen=True)
class KeywordRerankerProvider:
    model_name: str = "teebotus-keyword-reranker-v1"

    def rerank(self, query: str, documents: list[str], *, top_k: int) -> list[RerankResult]:
        query_terms = set(_terms(query))
        results: list[RerankResult] = []
        for index, document in enumerate(documents):
            doc_terms = set(_terms(document))
            overlap = len(query_terms & doc_terms)
            denominator = max(1, len(query_terms | doc_terms))
            score = overlap / denominator
            results.append(RerankResult(index=index, document=document, score=score))
        limit = max(1, int(top_k))
        return sorted(results, key=lambda item: (-item.score, item.index))[:limit]


def _terms(text: str) -> list[str]:
    return [match.group(0).casefold() for match in re.finditer(r"\b\w{2,}\b", str(text or ""), re.UNICODE)]
