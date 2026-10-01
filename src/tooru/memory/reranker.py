import math
import re
from datetime import UTC, datetime

from tooru.memory.models import (
    MemoryItem,
    MemoryRecallHit,
    MemoryRetrievalStrategy,
)


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[\w-]+", text.lower(), flags=re.UNICODE)
        if len(token) > 1
    }


def lexical_similarity(query: str, text: str) -> float:
    query_tokens = _tokens(query)
    text_tokens = _tokens(text)
    if not query_tokens or not text_tokens:
        return 0.0
    overlap = len(query_tokens & text_tokens)
    return overlap / math.sqrt(len(query_tokens) * len(text_tokens))


def recency_score(updated_at: str, half_life_days: float = 120.0) -> float:
    try:
        moment = datetime.fromisoformat(updated_at)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        age_days = max(0.0, (datetime.now(UTC) - moment).total_seconds() / 86400)
    except ValueError:
        return 0.5
    return math.exp(-math.log(2) * age_days / half_life_days)


def usage_score(memory: MemoryItem) -> float:
    access = min(1.0, math.log1p(memory.access_count) / math.log(21))
    total_feedback = memory.helpful_count + memory.unhelpful_count
    feedback = memory.helpful_count / total_feedback if total_feedback else 0.5
    return 0.65 * access + 0.35 * feedback


class HybridReranker:
    @staticmethod
    def _weights(strategy: MemoryRetrievalStrategy) -> dict[str, float]:
        profiles = {
            MemoryRetrievalStrategy.BALANCED: {
                "semantic": 0.34, "lexical": 0.14, "retrieval": 0.10,
                "graph": 0.08, "truth": 0.14, "importance": 0.07,
                "confidence": 0.04, "recency": 0.04, "usage": 0.025,
                "pin": 0.025,
            },
            MemoryRetrievalStrategy.LEXICAL: {
                "semantic": 0.18, "lexical": 0.28, "retrieval": 0.20,
                "graph": 0.04, "truth": 0.14, "importance": 0.05,
                "confidence": 0.03, "recency": 0.03, "usage": 0.025,
                "pin": 0.025,
            },
            MemoryRetrievalStrategy.SEMANTIC: {
                "semantic": 0.48, "lexical": 0.08, "retrieval": 0.05,
                "graph": 0.06, "truth": 0.14, "importance": 0.06,
                "confidence": 0.03, "recency": 0.04, "usage": 0.03,
                "pin": 0.03,
            },
            MemoryRetrievalStrategy.GRAPH: {
                "semantic": 0.24, "lexical": 0.08, "retrieval": 0.06,
                "graph": 0.28, "truth": 0.14, "importance": 0.06,
                "confidence": 0.03, "recency": 0.03, "usage": 0.04,
                "pin": 0.04,
            },
            MemoryRetrievalStrategy.TEMPORAL: {
                "semantic": 0.24, "lexical": 0.08, "retrieval": 0.06,
                "graph": 0.10, "truth": 0.28, "importance": 0.05,
                "confidence": 0.03, "recency": 0.08, "usage": 0.04,
                "pin": 0.04,
            },
            MemoryRetrievalStrategy.CAUSAL: {
                "semantic": 0.22, "lexical": 0.07, "retrieval": 0.05,
                "graph": 0.32, "truth": 0.14, "importance": 0.05,
                "confidence": 0.03, "recency": 0.03, "usage": 0.045,
                "pin": 0.045,
            },
        }
        return profiles.get(strategy, profiles[MemoryRetrievalStrategy.BALANCED])

    def score(
        self,
        query: str,
        memory: MemoryItem,
        semantic_score: float,
        retrieval_score: float = 0.0,
        graph_score: float = 0.0,
        truth_score: float = 0.5,
        strategy: MemoryRetrievalStrategy = MemoryRetrievalStrategy.BALANCED,
    ) -> MemoryRecallHit:
        lexical = lexical_similarity(
            query,
            " ".join(
                filter(
                    None,
                    [memory.key, memory.content, " ".join(memory.tags)],
                )
            ),
        )
        recency = recency_score(memory.updated_at)
        semantic = max(0.0, semantic_score)
        usage = usage_score(memory)
        pin = 1.0 if memory.pinned else 0.0

        retrieval = max(0.0, min(1.0, retrieval_score))
        graph = max(0.0, min(1.0, graph_score))
        truth = max(0.0, min(1.0, truth_score))
        weights = self._weights(strategy)
        total = (
            weights["semantic"] * semantic
            + weights["lexical"] * lexical
            + weights["retrieval"] * retrieval
            + weights["graph"] * graph
            + weights["truth"] * truth
            + weights["importance"] * memory.importance
            + weights["confidence"] * memory.confidence
            + weights["recency"] * recency
            + weights["usage"] * usage
            + weights["pin"] * pin
        )
        return MemoryRecallHit(
            memory=memory,
            score=round(total, 6),
            strategy=strategy,
            semantic_score=round(semantic, 6),
            lexical_score=round(lexical, 6),
            retrieval_score=round(retrieval, 6),
            graph_score=round(graph, 6),
            truth_score=round(truth, 6),
            uncertainty_score=round(1.0 - truth, 6),
            importance_score=memory.importance,
            confidence_score=memory.confidence,
            recency_score=round(recency, 6),
            usage_score=round(usage, 6),
            pin_score=pin,
        )
