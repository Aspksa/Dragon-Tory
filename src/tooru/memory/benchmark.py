from __future__ import annotations

from dataclasses import dataclass

from tooru.memory.engine import MemoryEngine
from tooru.memory.models import (
    MemoryBenchmarkReport,
    MemoryRetrievalStrategy,
    MemoryScope,
    MemorySearch,
)


@dataclass(frozen=True, slots=True)
class RetrievalBenchmarkCase:
    query: str
    expected_memory_id: str
    scope: MemoryScope = MemoryScope.PROJECT
    project_id: str | None = "dragon-tory"
    strategy: MemoryRetrievalStrategy = MemoryRetrievalStrategy.AUTO
    as_of: str | None = None


def evaluate_retrieval(
    engine: MemoryEngine,
    cases: list[RetrievalBenchmarkCase],
    *,
    owner_id: str = "local-user",
    corpus_size: int | None = None,
) -> MemoryBenchmarkReport:
    if not cases:
        return MemoryBenchmarkReport(
            corpus_size=corpus_size or 0,
            query_count=0,
            hit_at_1=0.0,
            hit_at_5=0.0,
            mean_reciprocal_rank=0.0,
            strategies={},
        )

    hit1 = 0
    hit5 = 0
    reciprocal_sum = 0.0
    strategies: dict[str, int] = {}

    for case in cases:
        hits = engine.recall(
            MemorySearch(
                owner_id=owner_id,
                scope=case.scope,
                project_id=case.project_id,
                query=case.query,
                strategy=case.strategy,
                as_of=case.as_of,
                limit=10,
            ),
            track_usage=False,
        )
        if hits:
            strategy = hits[0].strategy.value
            strategies[strategy] = strategies.get(strategy, 0) + 1

        rank = next(
            (
                index
                for index, hit in enumerate(hits, start=1)
                if hit.memory.id == case.expected_memory_id
            ),
            None,
        )
        if rank == 1:
            hit1 += 1
        if rank is not None and rank <= 5:
            hit5 += 1
        if rank is not None:
            reciprocal_sum += 1.0 / rank

    total = len(cases)
    return MemoryBenchmarkReport(
        corpus_size=corpus_size or 0,
        query_count=total,
        hit_at_1=round(hit1 / total, 6),
        hit_at_5=round(hit5 / total, 6),
        mean_reciprocal_rank=round(reciprocal_sum / total, 6),
        strategies=strategies,
    )
