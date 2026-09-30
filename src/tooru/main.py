from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from tooru.ai.router import AIRouter
from tooru.api.health import router as health_router
from tooru.api.memory import router as memory_router
from tooru.core.config import get_settings
from tooru.memory.embedding import build_embedding_provider
from tooru.memory.engine import MemoryEngine
from tooru.memory.intelligence import IntelligenceConfig, MemoryIntelligence
from tooru.memory.maintenance import MemoryAutomation
from tooru.memory.store import SQLiteMemoryStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    store = SQLiteMemoryStore(settings.memory_db_path)
    memory = MemoryEngine(
        store=store,
        embedder=build_embedding_provider(settings),
        related_threshold=settings.memory_related_threshold,
    )
    memory.initialize()

    ai_router = AIRouter()
    intelligence = MemoryIntelligence(
        engine=memory,
        router=ai_router,
        config=IntelligenceConfig(
            primary_provider=settings.memory_intelligence_primary_provider,
            reviewer_provider=settings.memory_intelligence_reviewer_provider,
            reviewer_threshold=settings.memory_intelligence_reviewer_threshold,
            context_limit=settings.memory_intelligence_context_limit,
        ),
    )

    automation = MemoryAutomation(
        memory,
        interval_seconds=settings.memory_maintenance_interval_seconds,
        archive_after_days=settings.memory_archive_after_days,
        archive_max_importance=settings.memory_archive_max_importance,
        archive_max_access_count=settings.memory_archive_max_access_count,
        auto_consolidate_threshold=settings.memory_auto_consolidate_threshold,
        consolidate_cooldown_hours=settings.memory_consolidate_cooldown_hours,
    )

    app.state.memory = memory
    app.state.ai_router = ai_router
    app.state.memory_intelligence = intelligence
    app.state.memory_automation = automation

    if settings.memory_automation_enabled:
        automation.start()

    try:
        yield
    finally:
        await automation.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        lifespan=lifespan,
    )
    app.include_router(health_router)
    app.include_router(memory_router)
    return app


app = create_app()


def run() -> None:
    settings = get_settings()
    uvicorn.run(
        "tooru.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    run()
