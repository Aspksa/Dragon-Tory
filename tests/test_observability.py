from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tooru.ai.base import AIRequest, AIResponse
from tooru.ai.router import AIRouter
from tooru.main import app
from tooru.memory.embedding import HashEmbeddingProvider
from tooru.memory.engine import MemoryEngine
from tooru.memory.guardian import GuardianConfig, MemoryGuardian
from tooru.memory.intake import MemoryIntakeGateway
from tooru.memory.intelligence import IntelligenceConfig, MemoryIntelligence
from tooru.memory.models import MemoryCreate, MemoryKind, MemoryScope
from tooru.memory.store import SQLiteMemoryStore
from tooru.observability.context import observation_context
from tooru.observability.store import ObservabilityStore


class TelemetryProvider:
    name = "deepseek"
    model = "telemetry-test"

    async def generate(self, request: AIRequest) -> AIResponse:
        return AIResponse(
            text="OK",
            provider=self.name,
            model=self.model,
            retry_count=2,
            duration_ms=123.4,
        )


def _memory_gateway(tmp_path: Path, observability: ObservabilityStore):
    memory_store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    engine = MemoryEngine(memory_store, HashEmbeddingProvider(128))
    engine.initialize()
    intelligence = MemoryIntelligence(
        engine,
        AIRouter(observability=observability),
        IntelligenceConfig(
            primary_provider="deepseek",
            reviewer_provider="deepseek",
        ),
    )
    guardian = MemoryGuardian(
        intelligence,
        memory_store,
        GuardianConfig(),
        observability=observability,
    )
    return MemoryIntakeGateway(guardian)


def test_observability_tracks_active_and_completed_spans(
    tmp_path: Path,
) -> None:
    store = ObservabilityStore(tmp_path / "observability.sqlite3")
    store.initialize()

    with observation_context(
        module="contracts",
        source_type="document",
        source_id="TORY-DOC-1",
        document_id="TORY-DOC-1",
        new_trace=True,
    ):
        span_id = store.start_span(
            category="analysis",
            stage="analysis",
            operation="local_document_analysis",
        )
        running = store.summary()
        assert running["current"]["status"] == "running"
        assert running["current"]["document_id"] == "TORY-DOC-1"

        store.finish_span(
            span_id,
            status="success",
            duration_ms=42.5,
            message="done",
        )

    summary = store.summary()
    assert summary["current"] is None
    assert summary["stats"]["analyses"] == 1
    assert summary["chains"][0]["document_id"] == "TORY-DOC-1"


@pytest.mark.asyncio
async def test_ai_router_records_latency_retry_and_module(
    tmp_path: Path,
) -> None:
    store = ObservabilityStore(tmp_path / "observability.sqlite3")
    store.initialize()
    router = AIRouter(observability=store)
    router.register(TelemetryProvider())

    result = await router.generate(
        "deepseek",
        AIRequest(messages=[{"role": "user", "content": "test"}]),
        module="contracts",
        operation="document_deep_summary",
        source_type="document",
        source_id="TORY-DOC-2",
        document_id="TORY-DOC-2",
    )

    assert result.retry_count == 2
    summary = store.summary()
    assert summary["stats"]["ai_requests"] == 1
    assert summary["stats"]["ai_retries"] == 2
    assert summary["stats"]["ai_avg_ms"] == 123.4

    ai_events = [
        item
        for item in summary["recent"]
        if item["category"] == "ai"
    ]
    assert ai_events[0]["module"] == "contracts"
    assert ai_events[0]["document_id"] == "TORY-DOC-2"
    assert ai_events[0]["retry_count"] == 2


def test_document_to_guardian_to_memory_chain(
    tmp_path: Path,
) -> None:
    store = ObservabilityStore(tmp_path / "observability.sqlite3")
    store.initialize()
    gateway = _memory_gateway(tmp_path, store)

    with observation_context(
        module="contracts",
        source_type="document",
        source_id="TORY-DOC-3",
        document_id="TORY-DOC-3",
        new_trace=True,
    ):
        store.event(
            category="source",
            stage="source",
            operation="module_document_selected",
            status="success",
            message="selected",
        )
        result = gateway.ingest(
            MemoryCreate(
                scope=MemoryScope.PROJECT,
                project_id="dragon-tory",
                kind=MemoryKind.SUMMARY,
                key="document-knowledge:TORY-DOC-3",
                content="Проверенное знание из тестового договора.",
                source="tooru-module-study",
                source_ref="TORY-DOC-3:v1:test",
                confidence=1.0,
                importance=0.72,
                tags=["module-knowledge", "contracts", "document"],
            ),
            reason="Observability integration test.",
        )

    assert result.memory is not None
    summary = store.summary()
    chain = next(
        item
        for item in summary["chains"]
        if item["document_id"] == "TORY-DOC-3"
    )
    categories = [step["category"] for step in chain["steps"]]
    assert categories == ["source", "guardian", "memory"]

    memory_step = chain["steps"][-1]
    assert memory_step["memory_id"] == result.memory.id
    assert summary["stats"]["memory_writes"] == 1


def test_observability_api_is_available() -> None:
    with TestClient(app) as client:
        response = client.get("/v1/observability/summary")

    assert response.status_code == 200
    payload = response.json()
    assert "active" in payload
    assert "stats" in payload
    assert "chains" in payload
