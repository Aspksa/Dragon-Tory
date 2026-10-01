import sqlite3
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


def _memory_counts(db_path: Path) -> dict[str, int]:
    counts = {
        "total": 0,
        "active": 0,
        "archived": 0,
        "superseded": 0,
        "personal": 0,
        "project": 0,
        "deleted": 0,
        "links": 0,
        "vectors": 0,
        "history": 0,
    }
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN deleted_at IS NULL
                    AND status = 'active' THEN 1 ELSE 0 END) AS active,
                SUM(CASE WHEN deleted_at IS NULL
                    AND status = 'archived' THEN 1 ELSE 0 END) AS archived,
                SUM(CASE WHEN deleted_at IS NULL
                    AND status = 'superseded' THEN 1 ELSE 0 END) AS superseded,
                SUM(CASE WHEN deleted_at IS NULL
                    AND scope = 'personal' THEN 1 ELSE 0 END) AS personal,
                SUM(CASE WHEN deleted_at IS NULL
                    AND scope = 'project' THEN 1 ELSE 0 END) AS project,
                SUM(CASE WHEN deleted_at IS NOT NULL
                    THEN 1 ELSE 0 END) AS deleted
            FROM memory_items
            """
        ).fetchone()
        for key in (
            "total",
            "active",
            "archived",
            "superseded",
            "personal",
            "project",
            "deleted",
        ):
            counts[key] = int(row[key] or 0)

        counts["links"] = int(
            conn.execute(
                "SELECT COUNT(*) AS count FROM memory_links"
            ).fetchone()["count"]
            or 0
        )
        counts["vectors"] = int(
            conn.execute(
                "SELECT COUNT(*) AS count FROM memory_vectors"
            ).fetchone()["count"]
            or 0
        )
        counts["history"] = int(
            conn.execute(
                "SELECT COUNT(*) AS count FROM memory_history"
            ).fetchone()["count"]
            or 0
        )

    return counts


@router.get("/status")
def diagnostics_status(request: Request) -> dict:
    settings = request.app.state.settings

    vm = psutil.virtual_memory()
    process = psutil.Process()
    process_memory = process.memory_info()
    data_dir = settings.data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    disk = psutil.disk_usage(str(data_dir))

    guardian = request.app.state.memory_guardian.status()
    memory_automation = request.app.state.memory_automation.status()
    guardian_automation = (
        request.app.state.memory_guardian_automation.status()
    )

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
            "provider": "deepseek",
            "configured": request.app.state.deepseek_config["configured"],
            "model": request.app.state.deepseek_config["model"],
            "base_url": request.app.state.deepseek_config["base_url"],
            "stats": request.app.state.ai_router.provider_status("deepseek"),
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
            **_memory_counts(settings.memory_db_path),
            "database_bytes": _path_size(settings.memory_db_path),
        },
        "guardian": guardian.model_dump(mode="json"),
        "memory_automation": memory_automation.model_dump(mode="json"),
        "guardian_automation": guardian_automation.model_dump(
            mode="json"
        ),
    }
