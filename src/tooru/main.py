from contextlib import asynccontextmanager
from datetime import UTC, datetime
from ipaddress import ip_address
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from tooru.ai.openai_compatible import OpenAICompatibleProvider
from tooru.ai.router import AIRouter
from tooru.api.chat import router as chat_router
from tooru.api.chats import router as chats_router
from tooru.api.cloud import router as cloud_router
from tooru.api.cloud_intelligence import router as cloud_intelligence_router
from tooru.api.cloud_smart import router as cloud_smart_router
from tooru.api.diagnostics import router as diagnostics_router
from tooru.api.health import router as health_router
from tooru.api.home import router as home_router
from tooru.api.memory import router as memory_router
from tooru.api.settings import remove_legacy_claude_settings
from tooru.api.settings import router as settings_router
from tooru.api.update import router as update_router
from tooru.chat.pipeline import ChatPipeline
from tooru.chat.store import ChatStore
from tooru.cloud.document_intelligence import DocumentIntelligence
from tooru.cloud.smart import SmartDrive
from tooru.cloud.store import CloudStore
from tooru.cloud.vault import ToryVault
from tooru.core.config import get_settings
from tooru.memory.embedding import build_embedding_provider
from tooru.memory.engine import MemoryEngine
from tooru.memory.guardian import GuardianConfig, MemoryGuardian
from tooru.memory.guardian_automation import MemoryGuardianAutomation
from tooru.memory.intelligence import IntelligenceConfig, MemoryIntelligence
from tooru.memory.intake import MemoryIntakeGateway
from tooru.memory.maintenance import MemoryAutomation
from tooru.memory.store import SQLiteMemoryStore
from tooru.update.service import UpdateService


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    remove_legacy_claude_settings(Path(".env").resolve())

    store = SQLiteMemoryStore(settings.memory_db_path)
    memory = MemoryEngine(
        store=store,
        embedder=build_embedding_provider(settings),
        related_threshold=settings.memory_related_threshold,
    )
    memory.initialize()

    chat_store = ChatStore(settings.chat_db_path)
    chat_store.initialize()

    cloud_vault = ToryVault(settings.cloud_dir / "vault.json")
    cloud_store = CloudStore(
        settings.cloud_dir,
        settings.cloud_db_path,
        vault=cloud_vault,
    )
    cloud_store.initialize()
    cloud_smart = SmartDrive(cloud_store)
    cloud_smart.initialize()
    document_intelligence = DocumentIntelligence(cloud_store)
    document_intelligence.initialize()

    ai_router = AIRouter()
    if settings.deepseek_api_key:
        ai_router.register(
            OpenAICompatibleProvider(
                name="deepseek",
                api_key=settings.deepseek_api_key,
                base_url=settings.deepseek_base_url,
                model=settings.deepseek_model,
                timeout_seconds=settings.deepseek_timeout_seconds,
                max_attempts=settings.deepseek_max_attempts,
                retry_base_seconds=settings.deepseek_retry_base_seconds,
                retry_max_seconds=settings.deepseek_retry_max_seconds,
                circuit_breaker_failures=settings.deepseek_circuit_breaker_failures,
                circuit_breaker_cooldown_seconds=(
                    settings.deepseek_circuit_breaker_cooldown_seconds
                ),
            )
        )

    intelligence = MemoryIntelligence(
        engine=memory,
        router=ai_router,
        config=IntelligenceConfig(
            primary_provider="deepseek",
            reviewer_provider="deepseek",
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

    memory_intake = MemoryIntakeGateway(guardian)

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
    app.state.update_service = UpdateService(
        project_root=Path.cwd(),
        local_version=settings.version,
        repository=settings.update_repository,
        branch=settings.update_branch,
    )
    app.state.memory = memory
    app.state.chat_store = chat_store
    app.state.cloud_store = cloud_store
    app.state.cloud_vault = cloud_vault
    app.state.cloud_smart = cloud_smart
    app.state.document_intelligence = document_intelligence
    app.state.chat_tasks = {}
    app.state.ai_router = ai_router
    app.state.deepseek_config = {
        "configured": bool(settings.deepseek_api_key),
        "base_url": settings.deepseek_base_url,
        "model": settings.deepseek_model,
        "timeout_seconds": settings.deepseek_timeout_seconds,
        "max_attempts": settings.deepseek_max_attempts,
    }
    app.state.memory_intelligence = intelligence
    app.state.memory_guardian = guardian
    app.state.memory_intake = memory_intake
    app.state.memory_guardian_automation = guardian_automation
    app.state.memory_automation = automation
    app.state.chat_pipeline = ChatPipeline(
        memory=memory,
        router=ai_router,
        guardian=guardian,
    )

    if settings.memory_automation_enabled:
        automation.start()
    if settings.memory_guardian_automation_enabled:
        guardian_automation.start()

    try:
        yield
    finally:
        for task in list(app.state.chat_tasks.values()):
            task.cancel()
        await guardian_automation.stop()
        await automation.stop()


def _is_loopback_host(value: str | None) -> bool:
    host = (value or "").strip().split("%", 1)[0]
    if host.casefold() in {"localhost", "testclient"}:
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def local_api_guard(request: Request, call_next):
        if settings.allow_remote_api or _is_loopback_host(
            request.client.host if request.client else None
        ):
            return await call_next(request)
        return JSONResponse(
            status_code=403,
            content={
                "detail": (
                    "Dragon Tory API доступен только локально. "
                    "Удалённый доступ требует отдельного защищённого "
                    "слоя аутентификации и авторизации."
                )
            },
        )
    app.include_router(home_router)
    app.include_router(health_router)
    app.include_router(chat_router)
    app.include_router(chats_router)
    app.include_router(cloud_router)
    app.include_router(cloud_smart_router)
    app.include_router(cloud_intelligence_router)
    app.include_router(diagnostics_router)
    app.include_router(settings_router)
    app.include_router(update_router)
    app.include_router(memory_router)
    return app


app = create_app()


def run() -> None:
    settings = get_settings()
    if not settings.allow_remote_api and not _is_loopback_host(settings.host):
        raise RuntimeError(
            "Небезопасная привязка API заблокирована: используйте "
            "127.0.0.1/localhost, пока не настроен защищённый удалённый доступ."
        )
    uvicorn.run(
        "tooru.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    run()
