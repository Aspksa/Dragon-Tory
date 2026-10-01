from fastapi.testclient import TestClient

from tooru.main import app
from tooru.version import APP_VERSION


def test_web_ui_contains_main_sections() -> None:
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "Центр диагностики" in response.text
    assert 'id="checkMemoryHealth"' in response.text
    assert 'id="mHealth"' in response.text
    assert "Настройки" in response.text
    assert 'id="moduleRegistryList"' in response.text
    assert 'id="moduleRegistryCount"' in response.text
    assert "Чат" in response.text
    assert "Мой диск Тори" in response.text
    assert 'id="cloudNewFolder"' in response.text
    assert 'id="cloudTrashSidebar"' in response.text
    assert 'id="passportVersions"' in response.text
    assert 'id="passportActivity"' in response.text
    assert 'id="passportPreview"' in response.text
    assert 'id="passportIndexNow"' in response.text
    assert 'id="passportAsk"' in response.text
    assert 'id="cloudContentSearch"' in response.text
    assert 'id="cloudVault"' in response.text
    assert 'id="vaultModal"' in response.text
    assert 'id="vaultPassphrase"' in response.text
    assert 'id="passportEncryption"' in response.text
    assert 'id="cloudKnowledgeGraph"' in response.text
    assert 'id="cloudTimeMachine"' in response.text
    assert 'id="cloudAlerts"' in response.text
    assert 'id="passportDnaKind"' in response.text
    assert 'id="passportCounterparty"' in response.text
    assert 'id="passportDocumentNumber"' in response.text
    assert 'id="passportAmountValue"' in response.text
    assert 'id="passportTermsSummary"' in response.text
    assert 'id="passportCounterpartyId"' in response.text
    assert 'id="counterpartyModal"' in response.text
    assert 'id="passportDocumentSubtype"' in response.text
    assert 'id="passportWorkdayFields"' in response.text
    assert 'id="documentModuleTimesheet"' in response.text
    assert 'id="documentModuleDraft"' in response.text
    assert "document-center" in response.text
    assert 'id="contractExternalAI"' in response.text
    assert 'id="passportCleanRoom"' in response.text
    assert 'id="passportSeal"' in response.text
    assert 'id="passportWatchers"' in response.text
    assert 'id="smartModal"' in response.text
    assert 'id="cloudSmartSearch"' in response.text
    assert 'id="cloudSmartCollections"' in response.text
    assert 'id="cloudDeadlines"' in response.text
    assert 'id="cloudAnalyzePending"' in response.text
    assert 'id="passportAnalyze"' in response.text
    assert 'id="passportInsights"' in response.text
    assert 'id="passportVersionMeaning"' in response.text
    assert 'id="cloudDropZone"' in response.text
    assert 'id="cloudFileInput"' in response.text
    assert 'id="passportModal"' in response.text
    assert ".passport-backdrop[hidden]{display:none!important}" in response.text
    assert 'id="passportVerify"' in response.text
    assert "Мой диск Тори · личный документ" in response.text
    assert "Центр документа Тори" in response.text
    assert 'id="diskModules"' in response.text
    assert 'class="nav module-nav"' not in response.text
    assert 'id="documentModule"' in response.text
    assert 'id="documentModuleBack"' in response.text
    assert 'id="documentModuleAddRecord"' in response.text
    assert 'id="documentModuleUpload"' in response.text
    assert 'id="documentModuleUploadQueue"' in response.text
    assert 'id="cloudUploadQueue"' in response.text
    assert 'id="passportSaveTop"' in response.text
    assert 'data-passport-target="overview"' in response.text
    assert 'data-passport-target="dna"' in response.text
    assert 'data-passport-target="security"' in response.text
    assert 'data-passport-target="actions"' in response.text
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


def test_document_modules_endpoint_is_available() -> None:
    with TestClient(app) as client:
        response = client.get("/v1/cloud/intelligence/modules")

    assert response.status_code == 200
    modules = {item["id"] for item in response.json()["items"]}
    assert modules == {"contracts", "invoice_offers", "memos", "orders", "directives"}


def test_counterparty_directory_endpoint_is_available() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/v1/cloud/smart/counterparties",
            json={
                "name": "ООО Тест Контрагент",
                "inn": "7700000000",
                "kpp": "770001001",
                "bank_name": "Тест Банк",
            },
        )
        assert created.status_code == 201
        counterparty_id = created.json()["id"]

        listed = client.get("/v1/cloud/smart/counterparties")

    assert listed.status_code == 200
    assert any(
        item["id"] == counterparty_id
        for item in listed.json()["items"]
    )


def test_module_version_registry_endpoint_is_available() -> None:
    with TestClient(app) as client:
        response = client.get("/v1/settings/modules")

    assert response.status_code == 200
    items = response.json()["items"]
    ids = {item["id"] for item in items}
    assert {
        "drive",
        "memos",
        "invoice_offers",
        "contracts",
        "orders",
        "directives",
        "employees",
        "garage",
        "timesheet",
        "memory",
        "updater",
    } <= ids
    assert all(item["version"] for item in items)
    assert all(item["description"] for item in items)
    assert all(item["last_update"] for item in items)


def test_employee_and_garage_endpoints_are_available() -> None:
    with TestClient(app) as client:
        employee = client.post(
            "/v1/cloud/smart/employees",
            json={
                "full_name": "Петров Пётр Петрович",
                "personnel_number": "T-002",
                "position": "Водитель",
            },
        )
        assert employee.status_code == 201
        employee_id = employee.json()["id"]

        vehicle = client.post(
            "/v1/cloud/smart/garage",
            json={
                "garage_number": "21",
                "plate_number": "В321ВВ77",
                "make_model": "ГАЗ",
                "driver_employee_id": employee_id,
            },
        )

    assert vehicle.status_code == 201
    assert vehicle.json()["driver_name"] == "Петров Пётр Петрович"
