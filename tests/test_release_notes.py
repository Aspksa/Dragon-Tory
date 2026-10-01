from tooru.releases import release_notes_for


def test_release_0027_lists_garage_and_timesheet_changes() -> None:
    release = release_notes_for("00.00.27")

    assert release is not None
    modules = {item["id"]: item for item in release["modules"]}
    assert "garage" in modules
    assert "timesheet" in modules
    assert modules["garage"]["version"] == "01.03.00"
    assert modules["timesheet"]["version"] == "01.05.00"


def test_release_0028_lists_service_memo_changes() -> None:
    release = release_notes_for("0.0.28")

    assert release is not None
    modules = {item["id"]: item for item in release["modules"]}
    assert {"memos", "drive", "memory", "updater"} <= set(modules)
    assert modules["memos"]["version"] == "01.05.00"
