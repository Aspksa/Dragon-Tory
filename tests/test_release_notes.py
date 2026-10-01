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

def test_release_0029_lists_memory_v5_changes() -> None:
    release = release_notes_for("00.00.29")

    assert release is not None
    modules = {item["id"]: item for item in release["modules"]}
    assert "memory" in modules
    assert modules["memory"]["version"] == "02.00.00"
    assert any("FTS5" in change for change in modules["memory"]["changes"])

def test_release_0030_lists_cognitive_core_changes() -> None:
    release = release_notes_for("0.0.30")

    assert release is not None
    modules = {item["id"]: item for item in release["modules"]}
    assert {"memos", "drive", "memory", "updater"} <= set(modules)
    assert modules["memory"]["version"] == "02.01.00"
    assert any(
        "valid_from" in change
        for change in modules["memory"]["changes"]
    )

def test_release_0031_lists_truth_engine_changes() -> None:
    release = release_notes_for("0.0.31")

    assert release is not None
    modules = {item["id"]: item for item in release["modules"]}
    assert {"memos", "drive", "memory", "updater"} <= set(modules)
    assert modules["memory"]["version"] == "02.02.00"
    assert any(
        "trust-score" in change
        for change in modules["memory"]["changes"]
    )

def test_release_0032_lists_reasoning_engine_changes() -> None:
    release = release_notes_for("0.0.32")

    assert release is not None
    modules = {item["id"]: item for item in release["modules"]}
    assert {"reasoning", "memory", "memos", "drive", "updater"} <= set(modules)
    assert modules["reasoning"]["version"] == "01.00.00"
    assert any(
        "Result Verifier" in change
        for change in modules["reasoning"]["changes"]
    )

def test_release_0033_lists_document_intelligence_v2() -> None:
    release = release_notes_for("0.0.33")

    assert release is not None
    modules = {item["id"]: item for item in release["modules"]}
    assert {"drive", "contracts", "invoice_offers", "memos", "memory", "updater"} <= set(modules)
    assert modules["drive"]["version"] == "01.09.00"
    assert modules["memory"]["version"] == "02.03.00"
    assert any(
        "chunk-first" in change
        for change in modules["drive"]["changes"]
    )

def test_release_0034_lists_grey_matter_capabilities() -> None:
    release = release_notes_for("0.0.34")

    assert release is not None
    modules = {item["id"]: item for item in release["modules"]}
    assert {"grey_matter", "memory", "reasoning", "dashboard", "updater"} <= set(modules)
    assert modules["grey_matter"]["version"] == "01.00.00"
    assert modules["memory"]["version"] == "03.00.00"
    assert len(modules["grey_matter"]["changes"]) == 12
    assert any(
        "Multi-hop" in change
        for change in modules["grey_matter"]["changes"]
    )

def test_release_0035_lists_adaptive_grey_matter() -> None:
    release = release_notes_for("0.0.35")

    assert release is not None
    modules = {item["id"]: item for item in release["modules"]}
    assert {"grey_matter", "memory", "reasoning", "updater"} <= set(modules)
    assert modules["grey_matter"]["version"] == "02.00.00"
    assert modules["memory"]["version"] == "03.01.00"
    assert any(
        "Adaptive forgetting" in change
        for change in modules["grey_matter"]["changes"]
    )
    assert any(
        "strategy" in change
        for change in modules["memory"]["changes"]
    )

