"""WebSocket /ws/translate protocol tests."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.websocket import translate_stream


def _configure(ws, session_id: str = "test-session") -> dict:
    ws.send_json(
        {
            "type": "session_configuration",
            "session_id": session_id,
            "source_language": "en",
            "target_language": "es",
            "audio_source": "microphone",
            "sample_rate": 16_000,
            "encoding": "linear16",
        }
    )
    return ws.receive_json()


def test_start_and_configuration_yields_session_started() -> None:
    with TestClient(app).websocket_connect("/ws/translate") as ws:
        ws.send_json({"type": "start_session", "session_id": "cfg-1"})
        started = _configure(ws, "cfg-1")
        assert started["type"] == "session_started"
        assert started["session_id"] == "cfg-1"
        assert started["configuration"]["target_language"] == "es"
        assert started["configuration"]["audio_source"] == "microphone"


def test_audio_ack_reports_received_bytes() -> None:
    with TestClient(app).websocket_connect("/ws/translate") as ws:
        _configure(ws, "audio-1")
        ws.send_bytes(b"\x00" * 3200)

        ack = ws.receive_json()
        assert ack["type"] == "audio_received"
        assert ack["session_id"] == "audio-1"
        assert ack["chunks"] == 1
        assert ack["bytes"] == 3200


def test_audio_ack_accumulates_over_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(translate_stream, "_AUDIO_ACK_INTERVAL_MS", 0)
    with TestClient(app).websocket_connect("/ws/translate") as ws:
        _configure(ws, "audio-2")
        ws.send_bytes(b"\x00" * 3200)
        ws.send_bytes(b"\x00" * 1600)
        ws.send_bytes(b"\x00" * 1600)

        acks = [ws.receive_json() for _ in range(3)]
        assert [ack["type"] for ack in acks] == ["audio_received"] * 3
        assert acks[-1]["chunks"] == 3
        assert acks[-1]["bytes"] == 6400
        assert acks[-1]["audio_seconds"] > 0


def test_stop_session_yields_session_stopped() -> None:
    with TestClient(app).websocket_connect("/ws/translate") as ws:
        _configure(ws, "stop-1")
        ws.send_json({"type": "stop_session", "session_id": "stop-1"})
        stopped = ws.receive_json()
        assert stopped["type"] == "session_stopped"
        assert stopped["reason"] == "client_request"


def test_audio_before_session_is_rejected() -> None:
    with TestClient(app).websocket_connect("/ws/translate") as ws:
        ws.send_bytes(b"\x00\x00")
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["code"] == "no_active_session"


def test_unknown_message_type_is_rejected() -> None:
    with TestClient(app).websocket_connect("/ws/translate") as ws:
        ws.send_json({"type": "teleport"})
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["code"] == "unknown_message"


def test_invalid_configuration_is_rejected() -> None:
    with TestClient(app).websocket_connect("/ws/translate") as ws:
        ws.send_json({"type": "session_configuration", "session_id": "broken"})
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["code"] == "invalid_message"


def test_stopped_session_is_released_for_reuse() -> None:
    session_id = "reuse-1"
    with TestClient(app).websocket_connect("/ws/translate") as ws:
        _configure(ws, session_id)
        ws.send_json({"type": "stop_session", "session_id": session_id})
        stopped = ws.receive_json()
        assert stopped["type"] == "session_stopped"

        ws.send_json({"type": "start_session", "session_id": session_id})
        restarted = _configure(ws, session_id)
        assert restarted["type"] == "session_started"
        assert restarted["session_id"] == session_id


def test_session_manager_is_clean_after_stop() -> None:
    session_id = "cleanup-1"
    with TestClient(app).websocket_connect("/ws/translate") as ws:
        _configure(ws, session_id)
        ws.send_json({"type": "stop_session", "session_id": session_id})
        assert ws.receive_json()["type"] == "session_stopped"
    assert translate_stream.session_manager.get(session_id) is None
