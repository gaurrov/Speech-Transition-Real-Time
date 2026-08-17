"""Health endpoint tests."""
from unittest.mock import AsyncMock, patch

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
    assert body["translation"]["provider"] == "nllb"
    assert isinstance(body["translation"]["available"], bool)


def test_health_returns_env() -> None:
    resp = _client().get("/health")
    assert resp.json()["env"] == "development"


def test_health_reports_nllb_service_reachable() -> None:
    with patch("app.main.probe_nllb_service", new_callable=AsyncMock, return_value=True):
        resp = _client().get("/health")
        nllb = resp.json()["providers"]["nllb"]
        assert nllb["service_reachable"] is True


def test_health_reports_nllb_service_unreachable() -> None:
    with patch("app.main.probe_nllb_service", new_callable=AsyncMock, return_value=False):
        resp = _client().get("/health")
        nllb = resp.json()["providers"]["nllb"]
        assert nllb["service_reachable"] is False


def test_health_translation_available_true() -> None:
    with patch("app.main.is_translation_available", new_callable=AsyncMock, return_value=True):
        resp = _client().get("/health")
        assert resp.json()["translation"]["available"] is True


def test_health_translation_available_false() -> None:
    with patch("app.main.is_translation_available", new_callable=AsyncMock, return_value=False):
        resp = _client().get("/health")
        assert resp.json()["translation"]["available"] is False
