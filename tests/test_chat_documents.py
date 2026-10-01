from __future__ import annotations

from fastapi.testclient import TestClient

from tooru.ai.base import AIRequest, AIResponse
from tooru.main import app


class CapturingDeepSeek:
    name = "deepseek"
    model = "test-document-model"

    def __init__(self) -> None:
        self.requests: list[AIRequest] = []

    async def generate(self, request: AIRequest) -> AIResponse:
        self.requests.append(request)
        prompt = request.system_prompt or ""
        if "финальное долговременное знание" in prompt:
            text = (
                "Документ сообщает, что сервисный интервал Subaru Forester "
                "составляет 12000 км. Источник сохранён в личном архиве."
            )
        elif "Изучи этот фрагмент документа" in prompt:
            text = "Сервисный интервал Subaru Forester — 12000 км."
        elif "локальный персональный ИИ-помощник" in prompt:
            text = "По загруженному документу интервал составляет 12000 км."
        else:
            text = "[]"
        return AIResponse(
            text=text,
            provider=self.name,
            model=self.model,
            retry_count=0,
            duration_ms=1.0,
        )


def test_chat_upload_studies_indexes_remembers_and_retrieves_document() -> None:
    provider = CapturingDeepSeek()
    with TestClient(app) as client:
        app.state.ai_router.register(provider)
        chat = client.post("/v1/chats", json={})
        assert chat.status_code == 201
        chat_id = chat.json()["id"]

        upload = client.post(
            (
                "/v1/chat/documents?"
                f"chat_id={chat_id}&name=forester-service.txt"
            ),
            content=(
                b"Subaru Forester service interval is 12000 km. "
                b"Next maintenance should use this interval."
            ),
            headers={"Content-Type": "text/plain"},
        )
        assert upload.status_code == 201
        payload = upload.json()
        document_id = payload["document_id"]

        assert payload["ai_studied"] is True
        assert payload["indexed_chunks"] >= 1
        assert payload["memory_status"] in {
            "applied",
            "pending",
            "ignored",
            "blocked",
        }

        passport = client.get(
            f"/v1/cloud/files/{document_id}/passport"
        )
        assert passport.status_code == 200
        assert passport.json()["ai_access"] == "memory"
        assert passport.json()["scope"] == "personal"
        assert passport.json()["ai_index_status"] == "ready"

        history = client.get(f"/v1/chats/{chat_id}")
        assert history.status_code == 200
        contents = [
            item["content"]
            for item in history.json()["messages"]
        ]
        assert any("forester-service.txt" in item for item in contents)
        assert any("Изучил документ" in item for item in contents)

        answer = client.post(
            "/v1/chat",
            json={
                "chat_id": chat_id,
                "message": "Какой service interval у Subaru Forester?",
                "remember": False,
            },
        )
        assert answer.status_code == 200
        assert "12000" in answer.json()["answer"]

        chat_prompts = [
            request.system_prompt or ""
            for request in provider.requests
            if "Релевантные фрагменты личных документов"
            in (request.system_prompt or "")
        ]
        assert chat_prompts
        assert document_id in chat_prompts[-1]
        assert "12000 km" in chat_prompts[-1]

        client.delete(f"/v1/cloud/files/{document_id}")



class LongSummaryDeepSeek(CapturingDeepSeek):
    async def generate(self, request: AIRequest) -> AIResponse:
        self.requests.append(request)
        prompt = request.system_prompt or ""
        if "финальное долговременное знание" in prompt:
            text = (
                "Долговременный факт документа. "
                + ("Подтверждённая информация из документа. " * 120)
            )
        elif "Изучи этот фрагмент документа" in prompt:
            text = "Подтверждённая информация из документа."
        elif "локальный персональный ИИ-помощник" in prompt:
            text = "Документ изучен."
        else:
            text = "[]"
        return AIResponse(
            text=text,
            provider=self.name,
            model=self.model,
            retry_count=0,
            duration_ms=1.0,
        )


class FakeInternet:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def research(self, query: str) -> dict:
        self.queries.append(query)
        return {
            "query": query,
            "provider": "test-web",
            "sources": [
                {
                    "title": "Toyota Land Cruiser 80 reference",
                    "url": "https://example.com/land-cruiser-80",
                    "snippet": "Fuel consumption reference.",
                    "excerpt": (
                        "Toyota Land Cruiser 80 fuel consumption varies "
                        "by engine and operating conditions."
                    ),
                }
            ],
        }


def test_long_document_summary_can_be_saved_and_restudied() -> None:
    provider = LongSummaryDeepSeek()
    with TestClient(app) as client:
        app.state.ai_router.register(provider)
        chat = client.post("/v1/chats", json={})
        chat_id = chat.json()["id"]

        upload = client.post(
            (
                "/v1/chat/documents?"
                f"chat_id={chat_id}&name=long-memory-document.txt"
            ),
            content=b"Long document facts for durable memory.",
            headers={"Content-Type": "text/plain"},
        )
        assert upload.status_code == 201
        payload = upload.json()
        assert payload["error"] is None
        assert len(payload["summary"]) > 2000
        assert payload["memory_status"] in {
            "applied",
            "pending",
            "ignored",
            "blocked",
        }

        restudy = client.post(
            f"/v1/chat/documents/{payload['document_id']}/restudy"
        )
        assert restudy.status_code == 200
        assert restudy.json()["document_id"] == payload["document_id"]
        assert restudy.json()["memory_status"] in {
            "applied",
            "pending",
            "ignored",
            "blocked",
        }

        client.delete(f"/v1/cloud/files/{payload['document_id']}")


def test_chat_explicit_web_request_uses_real_web_context() -> None:
    provider = CapturingDeepSeek()
    internet = FakeInternet()
    with TestClient(app) as client:
        app.state.ai_router.register(provider)
        app.state.chat_pipeline.internet = internet

        response = client.post(
            "/v1/chat",
            json={
                "message": (
                    "Найди в интернете расход топлива Land Cruiser 80"
                ),
                "remember": False,
            },
        )

        assert response.status_code == 200
        assert internet.queries
        assert "https://example.com/land-cruiser-80" in (
            response.json()["answer"]
        )

        prompts = [
            request.system_prompt or ""
            for request in provider.requests
            if "[Web 1]" in (request.system_prompt or "")
        ]
        assert prompts
        assert "Toyota Land Cruiser 80" in prompts[-1]
        assert "нет доступа к сети" not in prompts[-1].casefold()
