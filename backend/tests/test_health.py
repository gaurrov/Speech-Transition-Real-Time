"""Health endpoint tests."""
from fastapi.testclient import TestClient

from app.main import app


def _client() -> TestClient:
    return TestClient(app)


def test_health_returns_ok() -> None:
    resp = _client().get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["asr_provider"] == "deepgram"
    assert body["translation_provider"] == "hybrid"


def test_health_returns_env() -> None:
    resp = _client().get("/health")
    assert resp.json()["env"] == "development"
