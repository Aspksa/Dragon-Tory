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


def recency_score(updated_at: str, half_life_days: float = 90.0) -> float:
    try:
        moment = datetime.fromisoformat(updated_at)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        age_days = max(0.0, (datetime.now(UTC) - moment).total_seconds() / 86400)
    except ValueError:
        return 0.5
    return math.exp(-math.log(2) * age_days / half_life_days)


class HybridReranker:
    def score(
        self,
        query: str,
        memory: MemoryItem,
        semantic_score: float,
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

        total = (
            0.50 * semantic
            + 0.20 * lexical
            + 0.12 * memory.importance
            + 0.08 * memory.confidence
            + 0.10 * recency
        )
        return MemoryRecallHit(
            memory=memory,
            score=round(total, 6),
            semantic_score=round(semantic, 6),
            lexical_score=round(lexical, 6),
            importance_score=memory.importance,
            confidence_score=memory.confidence,
            recency_score=round(recency, 6),
        )
