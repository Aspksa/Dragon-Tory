import json
from pathlib import Path

from tooru.update.service import UpdateService
from tooru.version import APP_VERSION, __version__


def make_service(tmp_path: Path) -> UpdateService:
    return UpdateService(
        project_root=tmp_path,
        local_version=APP_VERSION,
        repository="Aspksa/Dragon-Tory",
        branch="main",
    )


def test_version_normalization(tmp_path: Path) -> None:
    service = make_service(tmp_path)

    assert service._display_version(__version__) == APP_VERSION
    assert service._version_tuple(APP_VERSION) == tuple(
        int(part) for part in __version__.split(".")
    )
    assert service._version_tuple("0.1.12") == (0, 1, 12)


def test_update_state_round_trip(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service._write_state(
        {
            "phase": "success",
            "installed_sha": "a" * 40,
            "update_available": False,
        }
    )

    status = service.status()
    assert status["phase"] == "success"
    assert status["installed_sha"] == "a" * 40
    assert status["local_version"] == APP_VERSION
    assert status["repository"] == "Aspksa/Dragon-Tory"


def test_dead_updater_is_detected(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service._write_state(
        {
            "phase": "starting",
            "message": "starting",
            "updater_pid": 2_000_000_000,
            "update_started_at": "2026-10-01T00:00:00+00:00",
            "heartbeat_at": "2026-10-01T00:00:00+00:00",
            "local_version": APP_VERSION,
            "remote_version": APP_VERSION,
            "remote_sha": "b" * 40,
        }
    )

    status = service.status()

    assert status["phase"] == "failed"
    assert status["running"] is False
    assert "неожиданно завершился" in status["message"]


def test_history_returns_latest_first(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.history_path.parent.mkdir(parents=True, exist_ok=True)
    service.history_path.write_text(
        json.dumps(
            [
                {"description": "старое"},
                {"description": "новое"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    items = service.history(limit=10)

    assert [item["description"] for item in items] == [
        "новое",
        "старое",
    ]


def test_atomic_state_writes_use_unique_temp_files(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    service = make_service(tmp_path)

    def write_state(index: int) -> None:
        service._write_state(
            {
                "phase": "checking",
                "writer": index,
                "local_version": APP_VERSION,
            }
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write_state, range(40)))

    state = json.loads(
        service.state_path.read_text(encoding="utf-8")
    )
    assert 0 <= state["writer"] < 40
    assert not list(
        service.state_path.parent.glob("state.json.*.tmp")
    )


def test_atomic_history_write_leaves_no_shared_temp(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service._write_state(
        {
            "phase": "failed",
            "local_version": APP_VERSION,
            "remote_version": "00.00.99",
            "remote_sha": "d" * 40,
            "update_started_at": "2026-10-01T00:00:00+00:00",
            "error": "test",
        }
    )
    service._append_history_from_state(service._read_state(), success=False)

    assert service.history()
    assert not list(
        service.history_path.parent.glob("history.json.*.tmp")
    )
