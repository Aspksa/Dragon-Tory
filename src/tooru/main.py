from contextlib import asynccontextmanager
from datetime import UTC, datetime

import uvicorn
from fastapi import FastAPI

from tooru.ai.openai_compatible import OpenAICompatibleProvider
from tooru.ai.router import AIRouter
from tooru.api.chat import router as chat_router
from tooru.api.diagnostics import router as diagnostics_router
from tooru.api.health import router as health_router
from tooru.api.home import router as home_router
from tooru.api.memory import router as memory_router
from tooru.api.settings import router as settings_router
from tooru.core.config import get_settings
from tooru.memory.embedding import build_embedding_provider
from tooru.memory.engine import MemoryEngine
from tooru.memory.guardian import GuardianConfig, MemoryGuardian
from tooru.memory.guardian_automation import MemoryGuardianAutomation
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
    if settings.deepseek_api_key:
        ai_router.register(
            OpenAICompatibleProvider(
                name="deepseek",
                api_key=settings.deepseek_api_key,
                base_url=settings.deepseek_base_url,
                model=settings.deepseek_model,
            )
        )

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

    guardian = MemoryGuardian(
        intelligence=intelligence,
        store=store,
        config=GuardianConfig(
            enabled=settings.memory_guardian_enabled,
            medium_importance=settings.memory_guardian_medium_importance,
            high_importance=settings.memory_guardian_high_importance,
            min_confidence=settings.memory_guardian_min_confidence,
            max_attempts=settings.memory_guardian_max_attempts,
            retry_delay_seconds=settings.memory_guardian_retry_delay_seconds,
        ),
    )

    guardian_automation = MemoryGuardianAutomation(
        guardian,
        interval_seconds=settings.memory_guardian_interval_seconds,
        batch_size=settings.memory_guardian_retry_batch_size,
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

    app.state.settings = settings
    app.state.started_at = datetime.now(UTC)
    app.state.memory = memory
    app.state.ai_router = ai_router
    app.state.deepseek_config = {
        "configured": bool(settings.deepseek_api_key),
        "base_url": settings.deepseek_base_url,
        "model": settings.deepseek_model,
    }
    app.state.memory_intelligence = intelligence
    app.state.memory_guardian = guardian
    app.state.memory_guardian_automation = guardian_automation
    app.state.memory_automation = automation

    if settings.memory_automation_enabled:
        automation.start()
    if settings.memory_guardian_automation_enabled:
        guardian_automation.start()

    try:
        yield
    finally:
        await guardian_automation.stop()
        await automation.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        lifespan=lifespan,
    )
    app.include_router(home_router)
    app.include_router(health_router)
    app.include_router(chat_router)
    app.include_router(diagnostics_router)
    app.include_router(settings_router)
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
