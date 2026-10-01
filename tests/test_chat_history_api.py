from fastapi.testclient import TestClient

from tooru.main import app


def test_chat_history_crud_api() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/v1/chats",
            json={"title": "Тестовый чат"},
        )
        assert created.status_code == 201
        chat_id = created.json()["id"]

        listed = client.get("/v1/chats")
        assert listed.status_code == 200
        assert any(
            item["id"] == chat_id
            for item in listed.json()["items"]
        )

        renamed = client.patch(
            f"/v1/chats/{chat_id}",
            json={"title": "Переименованный чат"},
        )
        assert renamed.status_code == 200
        assert renamed.json()["title"] == "Переименованный чат"

        detail = client.get(f"/v1/chats/{chat_id}")
        assert detail.status_code == 200
        assert detail.json()["messages"] == []

        deleted = client.delete(f"/v1/chats/{chat_id}")
        assert deleted.status_code == 204
