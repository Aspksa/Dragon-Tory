from pathlib import Path

from tooru.update.service import UpdateService


def make_service(tmp_path: Path) -> UpdateService:
    return UpdateService(
        project_root=tmp_path,
        local_version="00.00.03",
        repository="Aspksa/Dragon-Tory",
        branch="main",
    )


def test_version_normalization(tmp_path: Path) -> None:
    service = make_service(tmp_path)

    assert service._display_version("0.0.3") == "00.00.03"
    assert service._version_tuple("00.00.03") == (0, 0, 3)
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
    assert status["local_version"] == "00.00.03"
    assert status["repository"] == "Aspksa/Dragon-Tory"
