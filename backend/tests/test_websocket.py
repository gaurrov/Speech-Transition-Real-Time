"""WebSocket transport scaffold tests."""
from fastapi.testclient import TestClient

from app.main import app


def test_ws_audio_accepts_connection() -> None:
    with TestClient(app).websocket_connect("/ws/audio") as websocket:
        websocket.send_json({"type": "start", "source_language": "en", "target_language": "es"})
        websocket.send_json({"type": "stop"})
