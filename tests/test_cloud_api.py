from fastapi.testclient import TestClient

from tooru.main import app


def _upload(client: TestClient, name: str, content: bytes = b"test") -> dict:
    response = client.post(
        f"/v1/cloud/files?name={name}",
        content=content,
        headers={"Content-Type": "text/plain"},
    )
    assert response.status_code == 201
    return response.json()


def test_cloud_upload_passport_search_and_restore_trash() -> None:
    with TestClient(app) as client:
        document = _upload(
            client,
            "passport-test.txt",
            b"Dragon Tory cloud document",
        )
        document_id = document["id"]

        assert document_id.startswith("TORY-DOC-")
        assert document["version"] == 1
        assert document["ai_access"] == "denied"
        assert len(document["sha256"]) == 64

        passport = client.patch(
            f"/v1/cloud/files/{document_id}/passport",
            json={
                "ai_access": "read",
                "confidentiality": "confidential",
                "scope": "project",
                "project_id": "dragon-tory",
            },
        )
        assert passport.status_code == 200
        assert passport.json()["ai_access"] == "read"

        removed = client.delete(f"/v1/cloud/files/{document_id}")
        assert removed.status_code == 200
        trashed = client.get("/v1/cloud/trash")
        assert any(
            item["id"] == document_id
            for item in trashed.json()["items"]
        )

        restored = client.post(
            f"/v1/cloud/files/{document_id}/restore"
        )
        assert restored.status_code == 200
        assert restored.json()["trashed"] is False

        content = client.get(f"/v1/cloud/files/{document_id}/content")
        assert content.content == b"Dragon Tory cloud document"
        client.delete(f"/v1/cloud/files/{document_id}")


def test_cloud_folder_move_favorite_and_metadata() -> None:
    with TestClient(app) as client:
        folder = client.post(
            "/v1/cloud/folders",
            json={"name": "Subaru", "parent_id": None},
        )
        assert folder.status_code == 201
        folder_id = folder.json()["id"]

        document = _upload(client, "diag.txt")
        document_id = document["id"]
        updated = client.patch(
            f"/v1/cloud/files/{document_id}",
            json={
                "name": "Диагностика Subaru.txt",
                "folder_id": folder_id,
                "favorite": True,
                "description": "Диагностика автомобиля",
                "tags": ["Subaru", "диагностика"],
            },
        )
        assert updated.status_code == 200
        assert updated.json()["folder_id"] == folder_id
        assert updated.json()["favorite"] is True
        assert updated.json()["tags"] == ["Subaru", "диагностика"]

        listing = client.get(
            f"/v1/cloud/files?folder_id={folder_id}"
        ).json()
        assert any(item["id"] == document_id for item in listing["items"])

        client.delete(f"/v1/cloud/files/{document_id}")


def test_cloud_versions_and_activity() -> None:
    with TestClient(app) as client:
        document = _upload(client, "versioned.txt", b"version-one")
        document_id = document["id"]

        second = client.post(
            f"/v1/cloud/files/{document_id}/versions?name=versioned.txt",
            content=b"version-two",
            headers={"Content-Type": "text/plain"},
        )
        assert second.status_code == 200
        assert second.json()["version"] == 2

        versions = client.get(
            f"/v1/cloud/files/{document_id}/versions"
        ).json()["items"]
        assert [item["version"] for item in versions[:2]] == [2, 1]

        restored = client.post(
            f"/v1/cloud/files/{document_id}/versions/1/restore"
        )
        assert restored.status_code == 200
        assert restored.json()["version"] == 3
        current = client.get(f"/v1/cloud/files/{document_id}/content")
        assert current.content == b"version-one"

        activity = client.get(
            f"/v1/cloud/files/{document_id}/activity"
        ).json()["items"]
        actions = {item["action"] for item in activity}
        assert "uploaded" in actions
        assert "version_added" in actions
        assert "version_restored" in actions
        client.delete(f"/v1/cloud/files/{document_id}")


def test_confidentiality_and_integrity() -> None:
    with TestClient(app) as client:
        document = _upload(client, "protected.txt", b"protected")
        document_id = document["id"]

        blocked = client.patch(
            f"/v1/cloud/files/{document_id}/passport",
            json={
                "confidentiality": "highly_protected",
                "ai_access": "answer",
            },
        )
        assert blocked.status_code == 422

        confidential = client.patch(
            f"/v1/cloud/files/{document_id}/passport",
            json={
                "confidentiality": "confidential",
                "ai_access": "read",
            },
        )
        assert confidential.status_code == 200
        assert "answer" not in confidential.json()["allowed_ai_access"]

        verified = client.post(
            f"/v1/cloud/files/{document_id}/verify"
        ).json()
        assert verified["ok"] is True
        assert verified["actual_sha256"] == verified["expected_sha256"]
        client.delete(f"/v1/cloud/files/{document_id}")


def test_cloud_sanitizes_uploaded_filename() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/v1/cloud/files?name=../folder/secret.txt",
            content=b"safe",
            headers={"Content-Type": "text/plain"},
        )
        assert response.status_code == 201
        document_id = response.json()["id"]
        assert response.json()["name"] == "secret.txt"
        client.delete(f"/v1/cloud/files/{document_id}")


def test_text_preview_index_and_content_search() -> None:
    with TestClient(app) as client:
        document = _upload(
            client,
            "knowledge.txt",
            b"Subaru Forester service interval is 12000 km.",
        )
        document_id = document["id"]

        preview = client.get(
            f"/v1/cloud/files/{document_id}/preview"
        )
        assert preview.status_code == 200
        assert "Subaru Forester" in preview.json()["chunks"][0]["text"]

        denied = client.post(
            f"/v1/cloud/files/{document_id}/index"
        )
        assert denied.status_code == 403

        allowed = client.patch(
            f"/v1/cloud/files/{document_id}/passport",
            json={
                "ai_access": "read",
                "confidentiality": "personal",
            },
        )
        assert allowed.status_code == 200

        indexed = client.post(
            f"/v1/cloud/files/{document_id}/index"
        )
        assert indexed.status_code == 200
        assert indexed.json()["index_status"] == "ready"

        search = client.get(
            "/v1/cloud/search?query=Forester%20service"
        )
        assert search.status_code == 200
        assert any(
            item["document_id"] == document_id
            for item in search.json()["items"]
        )

        ask_denied = client.post(
            f"/v1/cloud/files/{document_id}/ask",
            json={"question": "Какой интервал?"},
        )
        assert ask_denied.status_code == 403
        client.delete(f"/v1/cloud/files/{document_id}")
