from datetime import UTC, datetime
from pathlib import Path

import psutil
from fastapi import APIRouter, Request

router = APIRouter(prefix="/v1/diagnostics", tags=["diagnostics"])


def _path_size(path: Path) -> int:
    total = 0
    for candidate in (
        path,
        Path(str(path) + "-wal"),
        Path(str(path) + "-shm"),
    ):
        try:
            total += candidate.stat().st_size
        except FileNotFoundError:
            pass
    return total


@router.get("/status")
def diagnostics_status(request: Request) -> dict:
    settings = request.app.state.settings
    memory = request.app.state.memory
    store = memory.store

    vm = psutil.virtual_memory()
    process = psutil.Process()
    process_memory = process.memory_info()
    data_dir = settings.data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    disk = psutil.disk_usage(str(data_dir))

    memory_counts = store.diagnostic_counts()
    guardian = request.app.state.memory_guardian.status()
    memory_automation = request.app.state.memory_automation.status()
    guardian_automation = request.app.state.memory_guardian_automation.status()

    started_at = request.app.state.started_at
    uptime_seconds = max(
        0,
        int((datetime.now(UTC) - started_at).total_seconds()),
    )

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "backend": {
            "status": "ok",
            "name": settings.app_name,
            "version": settings.version,
            "uptime_seconds": uptime_seconds,
        },
        "ai": {
            "providers": request.app.state.ai_router.available_providers(),
            "deepseek_configured": request.app.state.deepseek_config["configured"],
            "deepseek_model": request.app.state.deepseek_config["model"],
            "deepseek_base_url": request.app.state.deepseek_config["base_url"],
        },
        "system_memory": {
            "total_bytes": vm.total,
            "used_bytes": vm.used,
            "available_bytes": vm.available,
            "percent": vm.percent,
        },
        "process": {
            "rss_bytes": process_memory.rss,
            "threads": process.num_threads(),
            "pid": process.pid,
        },
        "disk": {
            "path": str(data_dir),
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
            "percent": disk.percent,
        },
        "memory_engine": {
            **memory_counts,
            "database_bytes": _path_size(settings.memory_db_path),
        },
        "guardian": guardian.model_dump(mode="json"),
        "memory_automation": memory_automation.model_dump(mode="json"),
        "guardian_automation": guardian_automation.model_dump(mode="json"),
    }
