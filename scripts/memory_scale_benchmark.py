from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

from tooru.memory.benchmark import RetrievalBenchmarkCase, evaluate_retrieval
from tooru.memory.embedding import FastEmbedProvider, HashEmbeddingProvider
from tooru.memory.engine import MemoryEngine
from tooru.memory.models import MemoryCreate, MemoryKind, MemoryScope
from tooru.memory.store import SQLiteMemoryStore


def build_engine(db_path: Path, provider: str) -> MemoryEngine:
    if provider == "fastembed":
        embedder = FastEmbedProvider()
    else:
        embedder = HashEmbeddingProvider(128)
    engine = MemoryEngine(SQLiteMemoryStore(db_path), embedder)
    engine.initialize()
    return engine


def seed(engine: MemoryEngine, count: int) -> list[RetrievalBenchmarkCase]:
    cases: list[RetrievalBenchmarkCase] = []
    checkpoints = {
        max(0, count // 10),
        max(0, count // 3),
        max(0, count // 2),
        max(0, count - 2),
    }
    for index in range(count):
        code = f"MEM-{index:06d}"
        item = engine.store.add(
            MemoryCreate(
                scope=MemoryScope.PROJECT,
                project_id="dragon-tory",
                kind=MemoryKind.FACT,
                key=f"benchmark.{code}",
                content=(
                    f"Синтетическая память {code}. "
                    f"Автомобиль тестовой группы {index % 97}. "
                    f"Контрольное значение {index * 7 + 11}."
                ),
                source="benchmark",
                confidence=0.9,
                importance=0.5,
                tags=["benchmark", f"group:{index % 97}"],
            )
        )
        if index in checkpoints:
            cases.append(
                RetrievalBenchmarkCase(
                    query=f"Найди запись {code}",
                    expected_memory_id=item.id,
                )
            )
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dragon Tory adaptive memory scale benchmark."
    )
    parser.add_argument(
        "--corpus",
        type=int,
        default=10_000,
        choices=(1_000, 10_000, 100_000),
    )
    parser.add_argument(
        "--provider",
        choices=("hash", "fastembed"),
        default="hash",
    )
    parser.add_argument("--db", type=Path)
    args = parser.parse_args()

    temporary = None
    if args.db is None:
        temporary = tempfile.TemporaryDirectory(prefix="tooru-memory-bench-")
        db_path = Path(temporary.name) / "memory.sqlite3"
    else:
        db_path = args.db

    started = time.perf_counter()
    engine = build_engine(db_path, args.provider)
    cases = seed(engine, args.corpus)
    seeded_at = time.perf_counter()
    report = evaluate_retrieval(
        engine,
        cases,
        corpus_size=args.corpus,
    )
    completed = time.perf_counter()

    payload = report.model_dump(mode="json")
    payload["provider"] = args.provider
    payload["seed_seconds"] = round(seeded_at - started, 3)
    payload["query_seconds"] = round(completed - seeded_at, 3)
    payload["total_seconds"] = round(completed - started, 3)
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if temporary is not None:
        temporary.cleanup()


if __name__ == "__main__":
    main()
