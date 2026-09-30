from collections import defaultdict

from tooru.memory.embedding import EmbeddingProvider, cosine_similarity
from tooru.memory.extractor import HeuristicMemoryExtractor
from tooru.memory.models import (
    MemoryConsolidateRequest,
    MemoryConsolidateResponse,
    MemoryCreate,
    MemoryDelete,
    MemoryExtractRequest,
    MemoryExtractResponse,
    MemoryItem,
    MemoryKind,
    MemoryLink,
    MemoryLinkType,
    MemoryRecallHit,
    MemorySearch,
    MemorySyncRequest,
    MemorySyncResponse,
    MemoryUpdate,
)
from tooru.memory.reranker import HybridReranker, lexical_similarity
from tooru.memory.store import SQLiteMemoryStore


class MemoryEngine:
    def __init__(
        self,
        store: SQLiteMemoryStore,
        embedder: EmbeddingProvider,
        related_threshold: float = 0.82,
    ):
        self.store = store
        self.embedder = embedder
        self.reranker = HybridReranker()
        self.extractor = HeuristicMemoryExtractor()
        self.related_threshold = related_threshold

    def initialize(self) -> None:
        self.store.initialize()
        self.backfill_vectors()

    def add(self, memory: MemoryCreate) -> MemoryItem:
        exact = self.store.find_exact(memory)
        if exact is not None:
            return exact

        near_duplicate = self._near_duplicate(memory)
        if near_duplicate is not None:
            return near_duplicate

        previous_same_key = self.store.find_same_key(memory)
        item = self.store.add(memory)
        self._index(item)

        for previous in previous_same_key:
            if self._normalize(previous.content) != self._normalize(item.content):
                self.store.add_link(
                    item.id,
                    previous.id,
                    MemoryLinkType.CONTRADICTS,
                    1.0,
                )
                self.store.add_link(
                    item.id,
                    previous.id,
                    MemoryLinkType.SUPERSEDES,
                    0.9,
                )

        self._link_related(item)
        return item

    def get(
        self, memory_id: str, owner_id: str = "local-user", include_deleted: bool = False
    ) -> MemoryItem:
        return self.store.get(memory_id, owner_id, include_deleted)

    def update(
        self, memory_id: str, owner_id: str, payload: MemoryUpdate
    ) -> MemoryItem:
        item = self.store.update(memory_id, owner_id, payload)
        self._index(item)
        self._link_related(item)
        return item

    def delete(self, memory_id: str, payload: MemoryDelete) -> MemoryItem:
        return self.store.delete(memory_id, payload)

    def search(self, request: MemorySearch) -> list[MemoryItem]:
        return [hit.memory for hit in self.recall(request)]

    def recall(self, request: MemorySearch) -> list[MemoryRecallHit]:
        candidates = self.store.candidates(
            request,
            limit=max(200, request.limit * 20),
        )
        if not candidates:
            return []

        query_vector = self.embedder.embed([request.query])[0]
        vectors = self.store.vectors_for(
            [item.id for item in candidates],
            provider=self.embedder.name,
            model=self.embedder.model,
        )

        missing = [item for item in candidates if item.id not in vectors]
        if missing:
            generated = self.embedder.embed([self._embedding_text(item) for item in missing])
            for item, vector in zip(missing, generated, strict=True):
                self.store.upsert_vector(
                    item.id, vector, self.embedder.name, self.embedder.model
                )
                vectors[item.id] = vector

        hits = [
            self.reranker.score(
                request.query,
                item,
                cosine_similarity(query_vector, vectors.get(item.id, [])),
            )
            for item in candidates
        ]
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[: request.limit]

    def extract(self, request: MemoryExtractRequest) -> MemoryExtractResponse:
        candidates = self.extractor.extract(request)
        saved: list[MemoryItem] = []
        if request.auto_save:
            saved = [self.add(candidate) for candidate in candidates]
        return MemoryExtractResponse(candidates=candidates, saved=saved)

    def consolidate(
        self,
        request: MemoryConsolidateRequest,
    ) -> MemoryConsolidateResponse:
        candidates = self.store.candidates(
            MemorySearch(
                owner_id=request.owner_id,
                scope=request.scope,
                project_id=request.project_id,
                query="memory-consolidation",
                min_importance=request.min_importance,
                limit=min(request.limit, 100),
            ),
            limit=request.limit,
        )
        candidates = [
            item for item in candidates
            if item.kind is not MemoryKind.SUMMARY
        ]

        if len(candidates) < 2:
            return MemoryConsolidateResponse(
                summary="",
                memory=None,
                source_ids=[item.id for item in candidates],
            )

        grouped: dict[MemoryKind, list[MemoryItem]] = defaultdict(list)
        for item in candidates:
            grouped[item.kind].append(item)

        labels = {
            MemoryKind.FACT: "Факты",
            MemoryKind.PREFERENCE: "Предпочтения",
            MemoryKind.DECISION: "Решения",
            MemoryKind.TASK: "Задачи",
            MemoryKind.EVENT: "События",
            MemoryKind.NOTE: "Заметки",
            MemoryKind.INSTRUCTION: "Правила",
            MemoryKind.RELATIONSHIP: "Связи",
        }
        sections: list[str] = []
        for kind, items in grouped.items():
            if kind is MemoryKind.SUMMARY:
                continue
            best = sorted(
                items,
                key=lambda item: (
                    item.importance,
                    item.confidence,
                    item.updated_at,
                ),
                reverse=True,
            )[:8]
            lines = "\n".join(f"- {item.content.strip()}" for item in best)
            sections.append(f"{labels.get(kind, kind.value)}:\n{lines}")

        summary = "\n\n".join(sections)
        memory = self.add(
            MemoryCreate(
                owner_id=request.owner_id,
                scope=request.scope,
                project_id=request.project_id,
                kind=MemoryKind.SUMMARY,
                key="memory.consolidated.summary",
                content=summary,
                source="memory-consolidator",
                confidence=0.90,
                importance=0.90,
                tags=["summary", "auto-consolidated"],
            )
        )
        source_ids = [item.id for item in candidates]
        for source_id in source_ids:
            if source_id != memory.id:
                self.store.add_link(
                    memory.id,
                    source_id,
                    MemoryLinkType.SUMMARIZES,
                    1.0,
                )
        return MemoryConsolidateResponse(
            summary=summary,
            memory=memory,
            source_ids=source_ids,
        )

    def links_for(
        self,
        memory_id: str,
        relation: MemoryLinkType | None = None,
    ) -> list[MemoryLink]:
        return self.store.links_for(memory_id, relation)

    def sync(self, request: MemorySyncRequest) -> MemorySyncResponse:
        return self.store.sync(request)

    def backfill_vectors(self, limit: int = 500) -> int:
        items = self.store.stale_vector_items(
            self.embedder.name,
            self.embedder.model,
            limit,
        )
        if not items:
            return 0
        vectors = self.embedder.embed([self._embedding_text(item) for item in items])
        for item, vector in zip(items, vectors, strict=True):
            self.store.upsert_vector(
                item.id, vector, self.embedder.name, self.embedder.model
            )
        return len(items)

    def _near_duplicate(self, memory: MemoryCreate) -> MemoryItem | None:
        if memory.key is not None:
            return None

        request = MemorySearch(
            owner_id=memory.owner_id,
            scope=memory.scope,
            project_id=memory.project_id,
            query=memory.content,
            kind=memory.kind,
            min_importance=0.0,
            limit=20,
        )
        candidates = self.store.candidates(request, limit=100)
        if not candidates:
            return None

        query_vector = self.embedder.embed([
            " | ".join(
                filter(
                    None,
                    [
                        memory.kind.value,
                        memory.content,
                        " ".join(memory.tags),
                    ],
                )
            )
        ])[0]
        vectors = self.store.vectors_for(
            [candidate.id for candidate in candidates],
            provider=self.embedder.name,
            model=self.embedder.model,
        )

        missing = [candidate for candidate in candidates if candidate.id not in vectors]
        if missing:
            generated = self.embedder.embed(
                [self._embedding_text(candidate) for candidate in missing]
            )
            for candidate, vector in zip(missing, generated, strict=True):
                self.store.upsert_vector(
                    candidate.id,
                    vector,
                    self.embedder.name,
                    self.embedder.model,
                )
                vectors[candidate.id] = vector

        for candidate in candidates:
            semantic = max(
                0.0,
                cosine_similarity(query_vector, vectors.get(candidate.id, [])),
            )
            lexical = lexical_similarity(memory.content, candidate.content)
            if semantic >= 0.97 and lexical >= 0.80:
                return candidate
        return None

    def _index(self, item: MemoryItem) -> None:
        vector = self.embedder.embed([self._embedding_text(item)])[0]
        self.store.upsert_vector(
            item.id, vector, self.embedder.name, self.embedder.model
        )

    def _link_related(self, item: MemoryItem) -> None:
        request = MemorySearch(
            owner_id=item.owner_id,
            scope=item.scope,
            project_id=item.project_id,
            query=item.content,
            min_importance=0.0,
            limit=8,
        )
        query_vector = self.embedder.embed([self._embedding_text(item)])[0]
        candidates = self.store.candidates(request, limit=100)
        vectors = self.store.vectors_for(
            [candidate.id for candidate in candidates],
            provider=self.embedder.name,
            model=self.embedder.model,
        )
        for candidate in candidates:
            if candidate.id == item.id:
                continue
            vector = vectors.get(candidate.id)
            if vector is None:
                continue
            similarity = max(0.0, cosine_similarity(query_vector, vector))
            if similarity >= self.related_threshold:
                self.store.add_link(
                    item.id,
                    candidate.id,
                    MemoryLinkType.RELATED,
                    similarity,
                )

    @staticmethod
    def _embedding_text(item: MemoryItem) -> str:
        return " | ".join(
            filter(
                None,
                [
                    item.key,
                    item.kind.value,
                    item.content,
                    " ".join(item.tags),
                ],
            )
        )

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.lower().split())
