import math
import re
from datetime import UTC, datetime

from tooru.memory.models import MemoryItem, MemoryRecallHit


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
    def score(
        self,
        query: str,
        memory: MemoryItem,
        semantic_score: float,
        retrieval_score: float = 0.0,
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
        total = (
            0.40 * semantic
            + 0.16 * lexical
            + 0.12 * retrieval
            + 0.10 * memory.importance
            + 0.07 * memory.confidence
            + 0.07 * recency
            + 0.04 * usage
            + 0.04 * pin
        )
        return MemoryRecallHit(
            memory=memory,
            score=round(total, 6),
            semantic_score=round(semantic, 6),
            lexical_score=round(lexical, 6),
            retrieval_score=round(retrieval, 6),
            importance_score=memory.importance,
            confidence_score=memory.confidence,
            recency_score=round(recency, 6),
            usage_score=round(usage, 6),
            pin_score=pin,
        )
