from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from tooru.api.health import router as health_router
from tooru.api.memory import router as memory_router
from tooru.core.config import get_settings
from tooru.memory.store import SQLiteMemoryStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    memory = SQLiteMemoryStore(settings.memory_db_path)
    memory.initialize()
    app.state.memory = memory
    yield


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
