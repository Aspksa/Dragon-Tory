from __future__ import annotations

import platform
import shutil
import sqlite3
import sys
from collections import Counter, defaultdict
from contextlib import suppress
from dataclasses import asdict
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from tooru.modules import module_registry
from tooru.releases import release_notes_for
from tooru.version import APP_VERSION


_REPORT_SCHEMA = "dragon-tory.machine-report.v1"
_REDACTED_KEYS = {
    "api_key",
    "authorization",
    "cookie",
    "content",
    "context",
    "deepseek_api_key",
    "excerpt",
    "feedback_note",
    "github_token",
    "knowledge",
    "line",
    "messages",
    "password",
    "passphrase",
    "prompt",
    "raw",
    "response",
    "secret",
    "snippet",
    "summary_local",
    "system_prompt",
    "text",
    "token",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _path_size(path: Path) -> int:
    total = 0
    for candidate in (
        path,
        Path(str(path) + "-wal"),
        Path(str(path) + "-shm"),
    ):
        try:
            total += candidate.stat().st_size
        except OSError:
            pass
    return total


def _safe_value(value: Any, *, depth: int = 0) -> Any:
    """Bound report values and remove secrets/content while keeping diagnostics."""
    if depth > 8:
        return "<max-depth>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str):
        return value[:4_000]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).casefold()
            if normalized in _REDACTED_KEYS:
                result[str(key)] = "<redacted>"
                continue
            result[str(key)] = _safe_value(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple, set)):
        return [
            _safe_value(item, depth=depth + 1)
            for item in list(value)[:2_000]
        ]
    if hasattr(value, "model_dump"):
        return _safe_value(value.model_dump(mode="json"), depth=depth + 1)
    return str(value)[:4_000]


def _git_head(project_root: Path) -> str | None:
    head = project_root / ".git" / "HEAD"
    try:
        raw = head.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw.startswith("ref: "):
        return raw[:80] or None
    ref = raw.removeprefix("ref: ").strip()
    ref_file = project_root / ".git" / ref
    try:
        return ref_file.read_text(encoding="utf-8").strip()[:80] or None
    except OSError:
        pass
    packed = project_root / ".git" / "packed-refs"
    try:
        for line in packed.read_text(encoding="utf-8").splitlines():
            if line.startswith(("#", "^")):
                continue
            sha, _, candidate = line.partition(" ")
            if candidate.strip() == ref:
                return sha[:80]
    except OSError:
        pass
    return None


def _safe_section(
    errors: list[dict[str, str]],
    name: str,
    factory,
    *,
    fallback: Any,
) -> Any:
    try:
        return _safe_value(factory())
    except Exception as exc:  # noqa: BLE001 - report must survive broken modules
        errors.append(
            {
                "section": name,
                "error_type": type(exc).__name__,
                "message": str(exc)[:1_500],
            }
        )
        return fallback


def _status_rank(status: str) -> int:
    return {
        "failed": 5,
        "degraded": 4,
        "pending": 3,
        "analyzed": 2,
        "studied": 1,
    }.get(status, 0)


def _document_report(state, *, limit: int) -> dict[str, Any]:
    documents = list(state.cloud_store.all_active_documents(limit=limit))
    observability_by_document: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with suppress(Exception):
        for event in state.observability.recent(limit=500):
            event_document_id = str(event.get("document_id") or "")
            if event_document_id:
                observability_by_document[event_document_id].append(event)

    documents.sort(
        key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
        reverse=True,
    )
    items: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()

    for document in documents:
        document_id = str(document["id"])
        analysis: dict[str, Any] | None = None
        try:
            analysis = state.document_intelligence.get(document_id)
        except (KeyError, ValueError):
            analysis = None

        try:
            contract = state.cloud_smart.get_contract(document_id)
        except (KeyError, ValueError):
            contract = None
        try:
            provenance = state.cloud_smart.provenance(document_id, limit=12)
        except (KeyError, ValueError):
            provenance = []
        try:
            activity = state.cloud_store.activity(document_id, limit=8)
        except (KeyError, ValueError):
            activity = []

        study_events = [
            item
            for item in provenance
            if str(item.get("event") or "").startswith("chat_document_study")
        ]
        latest_study = study_events[0] if study_events else None
        latest_event = str((latest_study or {}).get("event") or "")
        latest_details = dict((latest_study or {}).get("details") or {})

        if latest_event == "chat_document_study_failed":
            study_status = "failed"
        elif latest_event == "chat_document_studied":
            study_status = (
                "degraded"
                if latest_details.get("ai_error")
                else "studied"
            )
        elif analysis is not None:
            study_status = "analyzed"
        else:
            study_status = "pending"
        counts[study_status] += 1

        checks = dict((analysis or {}).get("checks") or {})
        structure = dict((analysis or {}).get("structure") or {})
        analysis_meta = None
        if analysis is not None:
            analysis_meta = {
                "kind": analysis.get("kind"),
                "confidence": analysis.get("confidence"),
                "extraction_method": analysis.get("extraction_method"),
                "ocr_used": bool(analysis.get("ocr_used")),
                "analyzed_at": analysis.get("analyzed_at"),
                "current_version": bool(analysis.get("current_version")),
                "warning_count": int(checks.get("warning_count") or 0),
                "warnings": list(checks.get("warnings") or [])[:20],
                "evidence_count": len(analysis.get("evidence") or []),
                "deadline_count": len(analysis.get("deadlines") or []),
                "chunk_count": int(structure.get("chunk_count") or 0),
                "pages": len(structure.get("pages") or []),
                "tables": len(structure.get("tables") or []),
            }

        document_events = observability_by_document.get(
            document_id,
            [],
        )
        latest_runtime = document_events[0] if document_events else None

        items.append(
            {
                "id": document_id,
                "name": document.get("name"),
                "version": document.get("version"),
                "source": document.get("source"),
                "scope": document.get("scope"),
                "project_id": document.get("project_id"),
                "content_type": document.get("content_type"),
                "size_bytes": document.get("size_bytes"),
                "sha256_prefix": str(document.get("sha256") or "")[:16],
                "confidentiality": document.get("confidentiality"),
                "ai_access": document.get("ai_access"),
                "ai_index_status": document.get("ai_index_status"),
                "indexed_version": document.get("indexed_version"),
                "encrypted": bool(document.get("encrypted")),
                "created_at": document.get("created_at"),
                "updated_at": document.get("updated_at"),
                "study_status": study_status,
                "latest_study": latest_study,
                "analysis": analysis_meta,
                "ai_contract": contract,
                "recent_provenance": provenance[:12],
                "recent_activity": activity[:8],
                "runtime_last_operation": (
                    latest_runtime.get("operation")
                    if latest_runtime is not None
                    else None
                ),
                "runtime_last_status": (
                    latest_runtime.get("status")
                    if latest_runtime is not None
                    else None
                ),
                "recent_observability": document_events[:20],
            }
        )

    items.sort(
        key=lambda item: (
            _status_rank(str(item.get("study_status") or "")),
            str(item.get("updated_at") or ""),
        ),
        reverse=True,
    )
    return {
        "total_in_report": len(items),
        "limit": limit,
        "truncated": len(items) >= limit,
        "study_status_counts": dict(counts),
        "items": items,
    }


def _reasoning_report(state) -> dict[str, Any]:
    experiences = state.cognition.store.experiences(limit=200)
    mode_counts: Counter[str] = Counter()
    pass_counts: Counter[str] = Counter()
    escalation_count = 0
    for item in experiences:
        mode_counts[item.mode] += 1
        if item.passed is True:
            pass_counts["passed"] += 1
        elif item.passed is False:
            pass_counts["failed"] += 1
        else:
            pass_counts["unverified"] += 1
        escalation_count += int(bool(item.escalated))

    config = asdict(state.chat_pipeline.reasoning.config)
    return {
        "automatic_mode_only": True,
        "config": config,
        "learned_policy": state.cognition.policy().model_dump(mode="json"),
        "experience_window": len(experiences),
        "mode_counts": dict(mode_counts),
        "verification_counts": dict(pass_counts),
        "escalations": escalation_count,
        "recent_experiences": [
            item.model_dump(mode="json")
            for item in experiences[:100]
        ],
    }


def _cognition_report(state) -> dict[str, Any]:
    graph = state.cognition.store.graph(limit=5_000)
    node_kinds = Counter(
        str(item.get("kind") or "unknown")
        for item in graph.get("nodes") or []
    )
    edge_kinds = Counter(
        str(item.get("kind") or "unknown")
        for item in graph.get("edges") or []
    )
    insights = state.cognition.store.insights(status=None, limit=200)
    return {
        "status": state.cognition.status(
            automation_running=bool(
                state.cognition_automation.status().get("running")
            )
        ).model_dump(mode="json"),
        "automation": state.cognition_automation.status(),
        "policy": state.cognition.policy().model_dump(mode="json"),
        "graph": {
            "nodes": len(graph.get("nodes") or []),
            "edges": len(graph.get("edges") or []),
            "node_kinds": dict(node_kinds),
            "edge_kinds": dict(edge_kinds),
        },
        "insights": [
            item.model_dump(mode="json")
            for item in insights
        ],
    }


def _guardian_report(state) -> dict[str, Any]:
    queue = state.memory_guardian.queue_items(limit=200)
    return {
        "status": state.memory_guardian.status().model_dump(mode="json"),
        "automation": state.memory_guardian_automation.status().model_dump(
            mode="json"
        ),
        "queue": [
            {
                "id": item.id,
                "risk": item.risk.value,
                "status": item.status.value,
                "scope": item.scope.value,
                "project_id": item.project_id,
                "attempts": item.attempts,
                "max_attempts": item.max_attempts,
                "next_attempt_at": item.next_attempt_at,
                "last_error": item.last_error,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
            }
            for item in queue
        ],
    }


def _observability_report(state) -> dict[str, Any]:
    recent = state.observability.recent(limit=500)
    failures = [
        item
        for item in recent
        if str(item.get("status") or "")
        in {"error", "failed", "blocked", "interrupted"}
    ]
    return {
        "retention_days": state.settings.observability_retention_days,
        "summary_24h": state.observability.summary(limit=120, hours=24),
        "recent_failures": failures[:150],
        "recent_events": recent[:250],
    }


def _configuration_report(state) -> dict[str, Any]:
    settings = state.settings
    return {
        "network": {
            "host": settings.host,
            "port": settings.port,
            "allow_remote_api": settings.allow_remote_api,
        },
        "ai": {
            "provider": "deepseek",
            "configured": bool(state.deepseek_config.get("configured")),
            "registered": state.ai_router.has_provider("deepseek"),
            "base_url": state.deepseek_config.get("base_url"),
            "model": state.deepseek_config.get("model"),
            "timeout_seconds": settings.deepseek_timeout_seconds,
            "max_attempts": settings.deepseek_max_attempts,
            "retry_base_seconds": settings.deepseek_retry_base_seconds,
            "retry_max_seconds": settings.deepseek_retry_max_seconds,
            "circuit_breaker_failures": settings.deepseek_circuit_breaker_failures,
            "circuit_breaker_cooldown_seconds": (
                settings.deepseek_circuit_breaker_cooldown_seconds
            ),
            "runtime_stats": state.ai_router.provider_status("deepseek"),
        },
        "memory": {
            "embedding_provider": settings.memory_embedding_provider,
            "embedding_model": settings.memory_embedding_model,
            "embedding_dimensions": settings.memory_embedding_dimensions,
            "related_threshold": settings.memory_related_threshold,
            "maintenance_enabled": settings.memory_automation_enabled,
            "maintenance_interval_seconds": (
                settings.memory_maintenance_interval_seconds
            ),
            "guardian_enabled": settings.memory_guardian_enabled,
            "guardian_automation_enabled": (
                settings.memory_guardian_automation_enabled
            ),
            "guardian_interval_seconds": (
                settings.memory_guardian_interval_seconds
            ),
        },
        "cognition": {
            "automation_enabled": settings.cognition_automation_enabled,
            "interval_seconds": settings.cognition_interval_seconds,
        },
        "documents": {
            "max_upload_bytes": settings.cloud_max_upload_bytes,
        },
        "observability": {
            "retention_days": settings.observability_retention_days,
        },
        "updates": {
            "repository": settings.update_repository,
            "branch": settings.update_branch,
        },
    }


def _document_engines_report() -> dict[str, Any]:
    packages = (
        "pypdf",
        "PyMuPDF",
        "python-docx",
        "openpyxl",
        "python-pptx",
        "odfpy",
        "striprtf",
        "xlrd",
        "pyxlsb",
        "extract-msg",
        "ebooklib",
        "Pillow",
    )
    versions: dict[str, str | None] = {}
    for package in packages:
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            versions[package] = None

    tesseract = shutil.which("tesseract")
    libreoffice = shutil.which("soffice") or shutil.which("libreoffice")
    return {
        "tesseract": {
            "available": bool(tesseract),
            "executable": Path(tesseract).name if tesseract else None,
            "used_for": ["scanned PDFs", "images requiring OCR"],
        },
        "libreoffice": {
            "available": bool(libreoffice),
            "executable": Path(libreoffice).name if libreoffice else None,
            "used_for": ["legacy .doc", "legacy .ppt", "conversion fallback"],
        },
        "python_packages": versions,
        "format_notes": {
            "native": [
                "DOCX",
                "XLSX",
                "XLS",
                "XLSB",
                "PPTX",
                "ODT/ODF",
                "RTF",
                "HTML",
                "EML",
                "MSG",
                "EPUB",
                "PDF",
                "images",
            ],
            "legacy_conversion": ["DOC", "PPT"],
        },
    }


def _implementation_map() -> dict[str, list[str]]:
    return {
        "chat": [
            "src/tooru/api/chat.py",
            "src/tooru/chat/pipeline.py",
            "src/tooru/chat/documents.py",
            "src/tooru/chat/reasoning.py",
        ],
        "documents": [
            "src/tooru/cloud/store.py",
            "src/tooru/cloud/document_intelligence.py",
            "src/tooru/cloud/document_analysis_v2.py",
            "src/tooru/cloud/smart.py",
        ],
        "memory": [
            "src/tooru/memory/engine.py",
            "src/tooru/memory/store.py",
            "src/tooru/memory/guardian.py",
            "src/tooru/memory/intelligence.py",
            "src/tooru/memory/grey_matter.py",
        ],
        "cognition": [
            "src/tooru/cognition/service.py",
            "src/tooru/cognition/store.py",
            "src/tooru/cognition/automation.py",
        ],
        "observability": [
            "src/tooru/observability/store.py",
            "src/tooru/api/observability.py",
        ],
        "report": [
            "src/tooru/system_report.py",
            "src/tooru/api/settings.py",
        ],
    }


def _runtime_report(state) -> dict[str, Any]:
    settings = state.settings
    project_root = Path.cwd().resolve()
    return {
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable_name": Path(sys.executable).name,
        },
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "sqlite_version": sqlite3.sqlite_version,
        "project_root_name": project_root.name,
        "git_head": _git_head(project_root),
        "databases": {
            "memory": {
                "path": str(settings.memory_db_path),
                "bytes": _path_size(settings.memory_db_path),
            },
            "chat": {
                "path": str(settings.chat_db_path),
                "bytes": _path_size(settings.chat_db_path),
            },
            "cloud": {
                "path": str(settings.cloud_db_path),
                "bytes": _path_size(settings.cloud_db_path),
            },
            "observability": {
                "path": str(settings.observability_db_path),
                "bytes": _path_size(settings.observability_db_path),
            },
            "cognition": {
                "path": str(settings.cognition_db_path),
                "bytes": _path_size(settings.cognition_db_path),
            },
        },
    }


def _pipeline_contracts() -> dict[str, Any]:
    return {
        "chat_document_study": {
            "stages": [
                "upload_to_my_disk",
                "set_personal_memory_ai_contract",
                "local_document_intelligence",
                "extract_text_or_ocr",
                "replace_local_search_chunks",
                "optional_deepseek_block_summaries",
                "hierarchical_merge",
                "memory_intake",
                "memory_guardian",
                "document_provenance",
            ],
            "degraded_behavior": (
                "DeepSeek failure does not discard local extraction/index; "
                "study completes as degraded when local analysis remains usable."
            ),
            "failure_behavior": (
                "Fatal study failures keep the original document and record "
                "chat_document_study_failed with stage/error metadata."
            ),
        },
        "chat_reasoning": {
            "stages": [
                "personal_project_memory_context",
                "document_context",
                "adaptive_reasoning_route",
                "optional_plan",
                "optional_tree",
                "deepseek_answer",
                "result_verifier",
                "optional_single_tree_escalation",
                "memory_guardian",
                "cognition_outcome",
            ],
            "modes": ["chain", "hybrid", "tree"],
            "manual_mode_switch": False,
            "hidden_chain_of_thought_exported": False,
        },
        "memory": {
            "scopes": ["personal", "project"],
            "scope_isolation": True,
            "durable_writes": "Memory Intake -> Memory Guardian -> Memory Engine",
            "grey_matter": [
                "entity_resolution",
                "hierarchy",
                "causality",
                "uncertainty",
                "multi_hop",
                "truth_calibration",
                "contradiction_clusters",
                "adaptive_forgetting",
                "sleep_consolidation",
                "goals_tasks",
                "skills",
            ],
        },
        "cognition": {
            "technical_memory_separate": True,
            "features": [
                "bounded_reasoning_policy_learning",
                "metacognitive_readiness",
                "typed_work_graph",
                "proactive_insights",
                "event_driven_debounced_cycles",
                "correction_learning_via_guardian",
            ],
        },
    }


def _diagnostic_findings(report: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    config = report.get("configuration") or {}
    ai = config.get("ai") or {}
    if not ai.get("configured") or not ai.get("registered"):
        findings.append(
            {
                "code": "AI_PROVIDER_NOT_READY",
                "severity": "high",
                "message": "DeepSeek is not fully configured/registered.",
            }
        )
    runtime_stats = ai.get("runtime_stats") or {}
    if runtime_stats.get("last_error"):
        findings.append(
            {
                "code": "AI_LAST_ERROR",
                "severity": "medium",
                "message": str(runtime_stats.get("last_error"))[:1_000],
            }
        )

    memory = report.get("memory") or {}
    health = memory.get("health") or {}
    if health.get("status") not in {None, "ok"}:
        findings.append(
            {
                "code": "MEMORY_HEALTH",
                "severity": (
                    "high" if health.get("status") == "error" else "medium"
                ),
                "message": f"Memory health: {health.get('status')}",
            }
        )

    guardian = report.get("guardian") or {}
    guardian_status = guardian.get("status") or {}
    if int(guardian_status.get("queued_dead") or 0) > 0:
        findings.append(
            {
                "code": "GUARDIAN_DEAD_QUEUE",
                "severity": "high",
                "message": (
                    f"Guardian dead-letter items: "
                    f"{guardian_status.get('queued_dead')}"
                ),
            }
        )

    automation_states = (
        ("memory_automation", memory.get("memory_automation") or {}),
        ("guardian_automation", guardian.get("automation") or {}),
    )
    for name, item in automation_states:
        if int(item.get("failure_count") or 0) > 0 or item.get("last_error"):
            findings.append(
                {
                    "code": name.upper() + "_ERROR",
                    "severity": "medium",
                    "message": str(
                        item.get("last_error") or "failure_count > 0"
                    ),
                }
            )

    cognition = report.get("cognition") or {}
    cognition_auto = cognition.get("automation") or {}
    if int(cognition_auto.get("failure_count") or 0) > 0:
        findings.append(
            {
                "code": "COGNITION_AUTOMATION_ERROR",
                "severity": "medium",
                "message": str(
                    cognition_auto.get("last_error") or "failure_count > 0"
                ),
            }
        )

    engines = report.get("document_engines") or {}
    if not (engines.get("tesseract") or {}).get("available", False):
        findings.append(
            {
                "code": "OCR_ENGINE_UNAVAILABLE",
                "severity": "low",
                "message": (
                    "Tesseract OCR is unavailable; scanned/image documents "
                    "may require installation before local text extraction."
                ),
            }
        )
    if not (engines.get("libreoffice") or {}).get("available", False):
        findings.append(
            {
                "code": "LEGACY_OFFICE_ENGINE_UNAVAILABLE",
                "severity": "low",
                "message": (
                    "LibreOffice is unavailable; legacy DOC/PPT conversion "
                    "may fail."
                ),
            }
        )

    documents = report.get("documents") or {}
    status_counts = documents.get("study_status_counts") or {}
    failed = int(status_counts.get("failed") or 0)
    degraded = int(status_counts.get("degraded") or 0)
    pending = int(status_counts.get("pending") or 0)
    if failed:
        findings.append(
            {
                "code": "DOCUMENT_STUDY_FAILED",
                "severity": "high",
                "message": f"Documents with fatal study failure: {failed}",
            }
        )
    if degraded:
        findings.append(
            {
                "code": "DOCUMENT_STUDY_DEGRADED",
                "severity": "medium",
                "message": f"Documents studied with AI degradation: {degraded}",
            }
        )
    if pending:
        findings.append(
            {
                "code": "DOCUMENT_ANALYSIS_PENDING",
                "severity": "low",
                "message": f"Documents without current analysis: {pending}",
            }
        )

    observability = report.get("observability") or {}
    failures = observability.get("recent_failures") or []
    if failures:
        findings.append(
            {
                "code": "RECENT_RUNTIME_FAILURES",
                "severity": "medium",
                "message": f"Recent technical failures/blocks: {len(failures)}",
            }
        )

    for error in report.get("collection_errors") or []:
        findings.append(
            {
                "code": "REPORT_SECTION_UNAVAILABLE",
                "severity": "medium",
                "message": (
                    f"{error.get('section')}: {error.get('error_type')} "
                    f"{error.get('message')}"
                )[:1_500],
            }
        )
    return findings


def build_machine_report(app, *, document_limit: int = 1_000) -> dict[str, Any]:
    state = app.state
    errors: list[dict[str, str]] = []
    generated_at = utc_now()

    report: dict[str, Any] = {
        "schema": _REPORT_SCHEMA,
        "generated_at": generated_at,
        "project": {
            "name": state.settings.app_name,
            "version": APP_VERSION,
            "repository": state.settings.update_repository,
            "branch": state.settings.update_branch,
            "release": release_notes_for(APP_VERSION),
        },
        "privacy": {
            "safe_for_technical_support": True,
            "contains_document_bodies": False,
            "contains_chat_messages": False,
            "contains_hidden_reasoning": False,
            "contains_api_keys_or_tokens": False,
            "may_contain": [
                "document names and IDs",
                "vehicle identifiers present in technical warnings",
                "counterparty names present in technical warnings",
                "local error messages and relative data paths",
            ],
            "redacted_fields": sorted(_REDACTED_KEYS),
        },
        "pipeline_contracts": _pipeline_contracts(),
        "implementation_map": _implementation_map(),
    }

    report["document_engines"] = _safe_section(
        errors,
        "document_engines",
        _document_engines_report,
        fallback={},
    )
    report["runtime"] = _safe_section(
        errors,
        "runtime",
        lambda: _runtime_report(state),
        fallback={},
    )
    report["configuration"] = _safe_section(
        errors,
        "configuration",
        lambda: _configuration_report(state),
        fallback={},
    )
    report["modules"] = _safe_section(
        errors,
        "modules",
        module_registry,
        fallback=[],
    )
    report["chat"] = _safe_section(
        errors,
        "chat",
        lambda: {
            "history": state.chat_store.counts(),
            "active_requests": len(state.chat_tasks),
        },
        fallback={},
    )
    report["documents"] = _safe_section(
        errors,
        "documents",
        lambda: {
            "storage": state.cloud_store.stats(),
            "smart_collections": state.document_intelligence.smart_collections(),
            **_document_report(state, limit=max(1, min(document_limit, 5_000))),
        },
        fallback={},
    )
    report["memory"] = _safe_section(
        errors,
        "memory",
        lambda: {
            "health": state.memory.store.health_report(deep=True),
            "memory_automation": state.memory_automation.status().model_dump(
                mode="json"
            ),
            "grey_matter": {
                "enabled": state.grey_matter is not None,
                "capabilities": _pipeline_contracts()["memory"]["grey_matter"],
            },
        },
        fallback={},
    )
    report["guardian"] = _safe_section(
        errors,
        "guardian",
        lambda: _guardian_report(state),
        fallback={},
    )
    report["reasoning"] = _safe_section(
        errors,
        "reasoning",
        lambda: _reasoning_report(state),
        fallback={},
    )
    report["cognition"] = _safe_section(
        errors,
        "cognition",
        lambda: _cognition_report(state),
        fallback={},
    )
    report["observability"] = _safe_section(
        errors,
        "observability",
        lambda: _observability_report(state),
        fallback={},
    )
    report["updates"] = _safe_section(
        errors,
        "updates",
        lambda: {
            "status": state.update_service.status(),
            "history": state.update_service.history(limit=15),
        },
        fallback={},
    )

    report["collection_errors"] = errors
    report["diagnostic_findings"] = _diagnostic_findings(report)
    report["report_summary"] = {
        "finding_count": len(report["diagnostic_findings"]),
        "high_findings": sum(
            item.get("severity") == "high"
            for item in report["diagnostic_findings"]
        ),
        "collection_error_count": len(errors),
        "document_status_counts": (
            (report.get("documents") or {}).get("study_status_counts") or {}
        ),
    }
    return _safe_value(report)
