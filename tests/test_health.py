from fastapi.testclient import TestClient

from tooru.main import app
from tooru.version import APP_VERSION


def test_health() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["version"] == APP_VERSION
