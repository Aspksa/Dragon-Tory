from fastapi.testclient import TestClient

from tooru.main import app


def test_cloud_upload_passport_search_and_trash() -> None:
    with TestClient(app) as client:
        upload = client.post(
            "/v1/cloud/files?name=passport-test.txt",
            content=b"Dragon Tory cloud document",
            headers={"Content-Type": "text/plain"},
        )
        assert upload.status_code == 201
        document = upload.json()
        document_id = document["id"]

        assert document_id.startswith("TORY-DOC-")
        assert document["name"] == "passport-test.txt"
        assert document["version"] == 1
        assert document["ai_access"] == "denied"
        assert document["ai_index_status"] == "blocked"
        assert len(document["sha256"]) == 64

        listed = client.get("/v1/cloud/files?query=passport-test")
        assert listed.status_code == 200
        assert any(item["id"] == document_id for item in listed.json()["items"])

        passport = client.patch(
            f"/v1/cloud/files/{document_id}/passport",
            json={
                "ai_access": "answer",
                "confidentiality": "confidential",
                "scope": "project",
                "project_id": "dragon-tory",
            },
        )
        assert passport.status_code == 200
        assert passport.json()["ai_access"] == "answer"
        assert passport.json()["ai_index_status"] == "needs_indexing"
        assert passport.json()["project_id"] == "dragon-tory"

        content = client.get(f"/v1/cloud/files/{document_id}/content")
        assert content.status_code == 200
        assert content.content == b"Dragon Tory cloud document"

        removed = client.delete(f"/v1/cloud/files/{document_id}")
        assert removed.status_code == 200
        assert client.get(
            f"/v1/cloud/files/{document_id}/passport"
        ).status_code == 404


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
