"""WebSocket /ws/translate protocol tests."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import TranscriptSegment
from app.websocket import translate_stream


@pytest.fixture(autouse=True)
def _use_fake_asr(fake_asr_factory):
    """Isolate transport tests from the network: every session gets a fake ASR."""
    return fake_asr_factory


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


def test_vad_event_is_recorded_on_session() -> None:
    with TestClient(app).websocket_connect("/ws/translate") as ws:
        _configure(ws, "vad-1")
        session = translate_stream.session_manager.get("vad-1")
        assert session is not None
        ws.send_json(
            {
                "type": "vad_event",
                "session_id": "vad-1",
                "event": "silence_detected",
                "timestamp_ms": 12345,
                "duration_ms": 600,
                "probability": 0.02,
            }
        )
        # stop_session acts as a barrier: session_stopped is only sent after
        # the vad_event message has been processed in order.
        ws.send_json({"type": "stop_session", "session_id": "vad-1"})
        assert ws.receive_json()["type"] == "session_stopped"
        assert session.last_vad_event is not None
        assert session.last_vad_event.event == "silence_detected"
        assert session.last_vad_event.duration_ms == 600


def test_vad_event_requires_matching_session() -> None:
    with TestClient(app).websocket_connect("/ws/translate") as ws:
        _configure(ws, "vad-2")
        ws.send_json(
            {
                "type": "vad_event",
                "session_id": "other-session",
                "event": "speech_started",
                "timestamp_ms": 1,
            }
        )
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["code"] == "no_active_session"


def test_invalid_vad_event_is_rejected() -> None:
    with TestClient(app).websocket_connect("/ws/translate") as ws:
        _configure(ws, "vad-3")
        ws.send_json({"type": "vad_event", "session_id": "vad-3", "event": "teleported"})
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["code"] == "invalid_message"


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


def test_partial_and_final_transcripts_are_forwarded(
    fake_asr_factory,
) -> None:
    session_id = "asr-1"
    with TestClient(app).websocket_connect("/ws/translate") as ws:
        _configure(ws, session_id)
        provider = fake_asr_factory[-1]

        provider.script(
            [
                TranscriptSegment(
                    segment_id="seg-0", text="We need to discuss", is_final=False
                ),
                TranscriptSegment(
                    segment_id="seg-0",
                    text="We need to discuss the project.",
                    is_final=True,
                    start_ms=120,
                    end_ms=2100,
                    confidence=0.95,
                    asr_latency_ms=180.0,
                ),
            ]
        )

        first = ws.receive_json()
        assert first["type"] == "partial_transcript"
        assert first["text"] == "We need to discuss"
        assert first["is_final"] is False
        assert first["segment_id"] == "seg-0"

        final = ws.receive_json()
        assert final["type"] == "final_transcript"
        assert final["text"] == "We need to discuss the project."
        assert final["is_final"] is True
        assert final["start_ms"] == 120
        assert final["end_ms"] == 2100
        assert final["confidence"] == 0.95

        latency = ws.receive_json()
        assert latency["type"] == "latency"
        assert latency["segment_id"] == "seg-0"
        assert latency["asr_ms"] == 180.0

        ws.send_json({"type": "stop_session", "session_id": session_id})
        assert ws.receive_json()["type"] == "session_stopped"


def test_audio_is_forwarded_to_asr_provider(fake_asr_factory) -> None:
    with TestClient(app).websocket_connect("/ws/translate") as ws:
        _configure(ws, "asr-audio")
        provider = fake_asr_factory[-1]
        ws.send_bytes(b"\x00" * 3200)
        assert ws.receive_json()["type"] == "audio_received"
        assert provider.chunks == [b"\x00" * 3200]


def test_silence_boundary_sends_endpointing_hint(fake_asr_factory) -> None:
    with TestClient(app).websocket_connect("/ws/translate") as ws:
        _configure(ws, "asr-hint")
        provider = fake_asr_factory[-1]
        ws.send_json(
            {
                "type": "vad_event",
                "session_id": "asr-hint",
                "event": "speech_started",
                "timestamp_ms": 1000,
            }
        )
        ws.send_json(
            {
                "type": "vad_event",
                "session_id": "asr-hint",
                "event": "silence_detected",
                "timestamp_ms": 5000,
                "duration_ms": 900,
            }
        )
        # stop_session acts as a barrier so the silence event is fully processed.
        ws.send_json({"type": "stop_session", "session_id": "asr-hint"})
        assert ws.receive_json()["type"] == "session_stopped"
        assert provider.silence_hints == [900]


def test_short_silence_does_not_send_endpointing_hint(fake_asr_factory) -> None:
    with TestClient(app).websocket_connect("/ws/translate") as ws:
        _configure(ws, "asr-nohint")
        provider = fake_asr_factory[-1]
        ws.send_json(
            {
                "type": "vad_event",
                "session_id": "asr-nohint",
                "event": "speech_started",
                "timestamp_ms": 1000,
            }
        )
        ws.send_json(
            {
                "type": "vad_event",
                "session_id": "asr-nohint",
                "event": "silence_detected",
                "timestamp_ms": 5000,
                "duration_ms": 300,
            }
        )
        ws.send_json({"type": "stop_session", "session_id": "asr-nohint"})
        assert ws.receive_json()["type"] == "session_stopped"
        assert provider.silence_hints == []


def test_connect_args_include_language(fake_asr_factory) -> None:
    with TestClient(app).websocket_connect("/ws/translate") as ws:
        ws.send_json(
            {
                "type": "session_configuration",
                "session_id": "asr-lang",
                "source_language": "hi",
                "target_language": "en",
                "audio_source": "microphone",
                "sample_rate": 16_000,
                "encoding": "linear16",
            }
        )
        assert ws.receive_json()["type"] == "session_started"
        provider = fake_asr_factory[-1]
        assert provider.connect_args == {
            "sample_rate": 16_000,
            "encoding": "linear16",
            "language": "hi",
        }
