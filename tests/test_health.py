"""GET /health 엔드포인트 테스트."""

from fastapi.testclient import TestClient

from macro_logbot import __version__


def test_health_ok(client: TestClient) -> None:
    """GET /health 가 200 OK 를 반환하고 올바른 body schema 를 포함해야 한다."""
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
