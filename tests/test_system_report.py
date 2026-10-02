from __future__ import annotations

from fastapi.testclient import TestClient

from tooru.main import app
from tooru.version import APP_VERSION


def test_machine_report_is_complete_downloadable_and_sanitized() -> None:
    sentinel = "PRIVATE_CHAT_BODY_MUST_NOT_ENTER_MACHINE_REPORT"

    with TestClient(app) as client:
        chat = client.app.state.chat_store.create("Machine report privacy")
        client.app.state.chat_store.add_message(
            chat["id"],
            role="user",
            content=sentinel,
        )

        response = client.get("/v1/settings/system-report")
        download = client.get("/v1/settings/system-report/download")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema"] == "dragon-tory.machine-report.v1"
    assert payload["project"]["version"] == APP_VERSION
    assert payload["privacy"]["contains_document_bodies"] is False
    assert payload["privacy"]["contains_chat_messages"] is False
    assert payload["privacy"]["contains_hidden_reasoning"] is False
    assert payload["privacy"]["contains_api_keys_or_tokens"] is False
    assert "pipeline_contracts" in payload
    assert "documents" in payload
    assert "memory" in payload
    assert "guardian" in payload
    assert "reasoning" in payload
    assert "cognition" in payload
    assert "observability" in payload
    assert "diagnostic_findings" in payload
    assert "report_summary" in payload

    ai_config = payload["configuration"]["ai"]
    assert "api_key" not in ai_config
    assert "deepseek_api_key" not in ai_config
    assert "github_token" not in payload["configuration"]["updates"]
    assert sentinel not in response.text

    assert download.status_code == 200
    assert "application/json" in download.headers["content-type"]
    disposition = download.headers["content-disposition"]
    assert "attachment" in disposition
    assert "dragon-tory-machine-report-" in disposition
    assert APP_VERSION in disposition


def test_chat_document_fatal_study_error_is_persisted_in_report(
    monkeypatch,
) -> None:
    marker = "REPORT_TEST_STUDY_FAILURE"

    async def broken_study(document_id: str, *, chat_id: str) -> dict:
        del document_id, chat_id
        raise RuntimeError(marker)

    with TestClient(app) as client:
        chat = client.app.state.chat_store.create("Broken document report")
        monkeypatch.setattr(
            client.app.state.chat_document_assistant,
            "study",
            broken_study,
        )

        uploaded = client.post(
            f"/v1/chat/documents?name=broken-report.txt&chat_id={chat['id']}",
            content=b"document body for failure test",
            headers={"content-type": "text/plain"},
        )
        assert uploaded.status_code == 201
        body = uploaded.json()
        assert marker in str(body["error"])
        document_id = body["document_id"]

        report = client.get("/v1/settings/system-report")
        assert report.status_code == 200
        payload = report.json()

    document = next(
        item
        for item in payload["documents"]["items"]
        if item["id"] == document_id
    )
    assert document["study_status"] == "failed"
    assert document["latest_study"]["event"] == "chat_document_study_failed"
    assert marker in str(document["latest_study"]["details"]["error"])
    assert any(
        item["code"] == "DOCUMENT_STUDY_FAILED"
        for item in payload["diagnostic_findings"]
    )


def test_machine_report_survives_broken_subsystem(monkeypatch) -> None:
    def broken_summary(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("OBS_REPORT_FAILURE")

    with TestClient(app) as client:
        monkeypatch.setattr(
            client.app.state.observability,
            "summary",
            broken_summary,
        )
        response = client.get("/v1/settings/system-report")

    assert response.status_code == 200
    payload = response.json()
    assert payload["observability"] == {}
    assert any(
        item["section"] == "observability"
        and item["error_type"] == "RuntimeError"
        for item in payload["collection_errors"]
    )
    assert any(
        item["code"] == "REPORT_SECTION_UNAVAILABLE"
        for item in payload["diagnostic_findings"]
    )
