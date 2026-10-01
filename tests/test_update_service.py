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
    assert service._version_tuple(APP_VERSION) == (0, 0, 3)
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
