from fastapi.testclient import TestClient

from tooru.main import app
from tooru.version import APP_VERSION


def test_web_ui_contains_main_sections() -> None:
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "Центр диагностики" in response.text
    assert "Настройки" in response.text
    assert "Чат" in response.text
    assert "Мой диск Тори" in response.text
    assert 'id="cloudNewFolder"' in response.text
    assert 'id="cloudTrash"' in response.text
    assert 'id="passportVersions"' in response.text
    assert 'id="passportActivity"' in response.text
    assert 'id="cloudDropZone"' in response.text
    assert 'id="cloudFileInput"' in response.text
    assert 'id="passportModal"' in response.text
    assert ".passport-backdrop[hidden]{display:none!important}" in response.text
    assert 'id="passportVerify"' in response.text
    assert "Мой диск Тори · личный документ" in response.text
    assert "Цифровой паспорт" in response.text
    assert "DeepSeek" in response.text
    assert 'id="newChat"' in response.text
    assert 'id="chatSearch"' in response.text
    assert 'id="renameChat"' in response.text
    assert 'id="deleteChat"' in response.text
    assert 'id="composerAction"' in response.text
    assert 'id="chatMode"' in response.text
    assert 'id="stopChat"' not in response.text
    assert 'id="retryChat"' not in response.text
    assert 'id="sendChat"' not in response.text
    assert "Кратко" in response.text
    assert "Подробно" in response.text
    assert "Анализ" in response.text
    assert 'id="chatProject"' not in response.text
    assert 'id="chatProvider"' not in response.text
    assert "Клод" not in response.text
    assert "Центр обновления" in response.text
    assert 'id="openUpdate"' in response.text
    assert 'id="updates"' in response.text
    assert 'id="installUpdate"' in response.text
    assert "История обновлений" in response.text
    assert "Скачанные файлы" in response.text


def test_diagnostics_status_is_available() -> None:
    with TestClient(app) as client:
        response = client.get("/v1/diagnostics/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["backend"]["status"] == "ok"
    assert "system_memory" in payload
    assert "memory_engine" in payload
    assert "chat_history" in payload
    assert "chats" in payload["chat_history"]
    assert "messages" in payload["chat_history"]


def test_chat_requires_configured_provider() -> None:
    with TestClient(app) as client:
        if client.get("/v1/settings/ai/deepseek").json()["configured"]:
            return
        response = client.post(
            "/v1/chat",
            json={"message": "Привет"},
        )

    assert response.status_code == 503


def test_update_status_endpoint_is_available() -> None:
    with TestClient(app) as client:
        response = client.get("/v1/update/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["local_version"] == APP_VERSION
    assert payload["repository"] == "Aspksa/Dragon-Tory"



def test_update_history_endpoint_is_available() -> None:
    with TestClient(app) as client:
        response = client.get("/v1/update/history")

    assert response.status_code == 200
    payload = response.json()
    assert "items" in payload
    assert "count" in payload



def test_chat_rejects_unknown_response_mode() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat",
            json={
                "message": "Привет",
                "response_mode": "unknown",
            },
        )

    assert response.status_code == 422
