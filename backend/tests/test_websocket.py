"""WebSocket /ws/translate protocol tests."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.models.schemas import TranscriptSegment
from app.services.translation.base import TranslationError
from app.websocket import translate_stream


@pytest.fixture(autouse=True)
def _use_fakes(fake_asr_factory, fake_translation_factory):
    """Isolate transport tests from the network: every session gets fake ASR + translation."""
    return fake_asr_factory, fake_translation_factory


def _configure(
    ws,
    session_id: str = "test-session",
    source_language: str = "en",
    target_language: str = "es",
) -> dict:
    ws.send_json(
        {
            "type": "session_configuration",
            "session_id": session_id,
            "source_language": source_language,
            "target_language": target_language,
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

        translation = ws.receive_json()
        assert translation["type"] == "translation"
        assert translation["segment_id"] == "seg-0"
        assert translation["source_text"] == "We need to discuss the project."
        assert translation["translated_text"] == "[We need to discuss the project.]"
        assert translation["source_language"] == "en"
        assert translation["target_language"] == "es"
        assert translation["is_final"] is True
        assert translation["provider"] == "fake"

        translation_latency = ws.receive_json()
        assert translation_latency["type"] == "latency"
        assert translation_latency["segment_id"] == "seg-0"
        assert translation_latency["translation_ms"] >= 0

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


def _drain_until(ws, event_type: str, count: int, max_events: int = 30) -> list[dict]:
    found = []
    for _ in range(max_events):
        event = ws.receive_json()
        if event["type"] == event_type:
            found.append(event)
            if len(found) == count:
                return found
    raise AssertionError(f"saw only {len(found)}/{count} {event_type} events")


def _stop_and_await(ws, session_id: str, max_events: int = 30) -> None:
    ws.send_json({"type": "stop_session", "session_id": session_id})
    for _ in range(max_events):
        event = ws.receive_json()
        if event["type"] == "session_stopped":
            return
    raise AssertionError("session_stopped never arrived")


def test_send_event_never_raises_when_peer_is_gone() -> None:
    """Regression: a failed WS send (client disconnected) must be swallowed.

    The old failure log passed ``event=`` to structlog, which is a reserved
    keyword and raised ``TypeError`` inside the error path itself.
    """
    from app.models import schemas

    class _BoomWebSocket:
        async def send_json(self, payload):
            raise RuntimeError("peer went away")

    session = translate_stream.Session("gone-peer", _BoomWebSocket(), get_settings())
    asyncio.run(
        session.send_event(schemas.SessionStoppedEvent(session_id="gone-peer", reason="x"))
    )


def test_partial_transcript_is_not_translated(
    fake_asr_factory, fake_translation_factory
) -> None:
    session_id = "tr-partial"
    with TestClient(app).websocket_connect("/ws/translate") as ws:
        _configure(ws, session_id)
        provider = fake_asr_factory[-1]
        translator = fake_translation_factory[-1]

        provider.script(
            [
                TranscriptSegment(
                    segment_id="seg-0", text="Working draft", is_final=False
                )
            ]
        )
        first = ws.receive_json()
        assert first["type"] == "partial_transcript"
        assert first["text"] == "Working draft"

        ws.send_json({"type": "stop_session", "session_id": session_id})
        assert ws.receive_json()["type"] == "session_stopped"
        assert translator.calls == []


def test_finalized_utterances_translate_in_order(
    fake_asr_factory, fake_translation_factory
) -> None:
    session_id = "tr-order"
    with TestClient(app).websocket_connect("/ws/translate") as ws:
        _configure(ws, session_id)
        provider = fake_asr_factory[-1]
        translator = fake_translation_factory[-1]

        provider.script(
            [
                TranscriptSegment(
                    segment_id="seg-1", text="First idea.", is_final=True
                ),
                TranscriptSegment(
                    segment_id="seg-2", text="Second idea.", is_final=True
                ),
            ]
        )
        translations = _drain_until(ws, "translation", 2)
        assert [t["segment_id"] for t in translations] == ["seg-1", "seg-2"]
        assert [t["translated_text"] for t in translations] == [
            "[First idea.]",
            "[Second idea.]",
        ]
        assert [c["segment_id"] for c in translator.calls] == ["seg-1", "seg-2"]
        assert translator.calls[0]["is_final"] is True

        _stop_and_await(ws, session_id)
        assert translator.closed is True


def test_translation_uses_session_languages(
    fake_asr_factory, fake_translation_factory
) -> None:
    session_id = "tr-lang"
    with TestClient(app).websocket_connect("/ws/translate") as ws:
        _configure(ws, session_id, source_language="hi", target_language="en")
        provider = fake_asr_factory[-1]
        translator = fake_translation_factory[-1]

        provider.script(
            [TranscriptSegment(segment_id="seg-0", text="नमस्ते", is_final=True)]
        )
        translation = _drain_until(ws, "translation", 1)[0]
        assert translation["source_language"] == "hi"
        assert translation["target_language"] == "en"
        assert translator.calls[0]["source_language"] == "hi"
        assert translator.calls[0]["target_language"] == "en"

        _stop_and_await(ws, session_id)


def test_translation_failure_is_non_fatal(
    fake_asr_factory, fake_translation_factory
) -> None:
    session_id = "tr-fail"
    with TestClient(app).websocket_connect("/ws/translate") as ws:
        _configure(ws, session_id)
        provider = fake_asr_factory[-1]
        translator = fake_translation_factory[-1]
        translator.fail_with = TranslationError("cloud_connection", "boom")
        translator.fail_segment_ids = {"seg-1"}

        provider.script(
            [
                TranscriptSegment(segment_id="seg-1", text="Broken.", is_final=True),
                TranscriptSegment(segment_id="seg-2", text="Fine.", is_final=True),
            ]
        )
        while True:
            event = ws.receive_json()
            if event["type"] == "error":
                assert event["code"] == "translation_failed"
                break
        translations = _drain_until(ws, "translation", 1)
        assert translations[0]["segment_id"] == "seg-2"
        assert translations[0]["translated_text"] == "[Fine.]"

        _stop_and_await(ws, session_id)


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


# --- Async LLM refinement ---------------------------------------------------


def test_refinement_is_dispatched_and_does_not_block_translation(
    fake_asr_factory, fake_translation_factory, fake_llm_factory
) -> None:
    session_id = "ref-1"
    with TestClient(app).websocket_connect("/ws/translate") as ws:
        _configure(ws, session_id)
        provider = fake_asr_factory[-1]
        translator = fake_translation_factory[-1]
        refiner = fake_llm_factory[-1]
        # Slow the LLM down: the live translation must still arrive first.
        refiner.delay = 0.2

        provider.script(
            [
                TranscriptSegment(
                    segment_id="seg-1", text="we need to deploy by friday", is_final=True
                )
            ]
        )

        events = []
        for _ in range(40):
            event = ws.receive_json()
            events.append(event)
            if event["type"] == "refined_transcript":
                break

        types = [event["type"] for event in events]
        assert "final_transcript" in types
        assert "translation" in types
        assert types.index("translation") < types.index("refined_transcript")

        translation = next(e for e in events if e["type"] == "translation")
        assert translation["translated_text"] == "[we need to deploy by friday]"
        assert translator.calls == [
            {
                "segment_id": "seg-1",
                "text": "we need to deploy by friday",
                "source_language": "en",
                "target_language": "es",
                "is_final": True,
            }
        ]

        refined = next(e for e in events if e["type"] == "refined_transcript")
        assert refined["segment_id"] == "seg-1"
        assert refined["refined_text"] == "We need to deploy by friday"
        assert refined["changed"] is True

        # Refinement latency is reported separately, on its own latency event.
        refinement_latencies = [
            e for e in events if e.get("refinement_ms") is not None
        ]
        assert len(refinement_latencies) == 1
        assert refinement_latencies[0]["segment_id"] == "seg-1"
        assert refinement_latencies[0]["refinement_ms"] >= 0

        _stop_and_await(ws, session_id)
        assert refiner.closed is True


def test_refinement_receives_rolling_context_window(
    fake_asr_factory, fake_llm_factory
) -> None:
    session_id = "ref-ctx"
    with TestClient(app).websocket_connect("/ws/translate") as ws:
        _configure(ws, session_id)
        provider = fake_asr_factory[-1]
        refiner = fake_llm_factory[-1]

        provider.script(
            [
                TranscriptSegment(segment_id="seg-1", text="first idea.", is_final=True),
                TranscriptSegment(segment_id="seg-2", text="second idea.", is_final=True),
            ]
        )

        seen = set()
        for _ in range(40):
            event = ws.receive_json()
            if event["type"] == "refined_transcript":
                seen.add(event["segment_id"])
                if len(seen) == 2:
                    break

        assert refiner.calls[0]["segment_id"] == "seg-1"
        assert refiner.calls[0]["context"] == []
        assert refiner.calls[1]["segment_id"] == "seg-2"
        assert refiner.calls[1]["context"] == ["first idea."]

        _stop_and_await(ws, session_id)


def test_refinement_failure_is_non_fatal_and_translation_continues(
    fake_asr_factory, fake_llm_factory
) -> None:
    session_id = "ref-fail"
    with TestClient(app).websocket_connect("/ws/translate") as ws:
        _configure(ws, session_id)
        provider = fake_asr_factory[-1]
        refiner = fake_llm_factory[-1]
        from app.services.llm.base import RefinementError

        refiner.fail_with = RefinementError("llm_api_error", "boom")

        provider.script(
            [
                TranscriptSegment(segment_id="seg-1", text="Broken.", is_final=True),
                TranscriptSegment(segment_id="seg-2", text="Fine.", is_final=True),
            ]
        )

        translations = _drain_until(ws, "translation", 2)
        assert [t["segment_id"] for t in translations] == ["seg-1", "seg-2"]

        # No refinement correction ever arrives; the session just keeps going.
        saw_refined = False
        ws.send_json({"type": "stop_session", "session_id": session_id})
        for _ in range(30):
            event = ws.receive_json()
            if event["type"] == "refined_transcript":
                saw_refined = True
            if event["type"] == "session_stopped":
                break
        assert saw_refined is False
        assert refiner.calls == [
            {"segment_id": "seg-1", "text": "Broken.", "language": "en", "context": []},
            {"segment_id": "seg-2", "text": "Fine.", "language": "en", "context": ["Broken."]},
        ]


def test_refinement_is_skipped_when_disabled(
    monkeypatch, fake_asr_factory, fake_translation_factory
) -> None:
    session_id = "ref-off"
    monkeypatch.setattr(translate_stream, "create_llm_provider", lambda: None)
    with TestClient(app).websocket_connect("/ws/translate") as ws:
        _configure(ws, session_id)
        provider = fake_asr_factory[-1]
        provider.script(
            [TranscriptSegment(segment_id="seg-1", text="hello.", is_final=True)]
        )

        _drain_until(ws, "translation", 1)
        saw_refined = False
        ws.send_json({"type": "stop_session", "session_id": session_id})
        for _ in range(30):
            event = ws.receive_json()
            if event["type"] == "refined_transcript":
                saw_refined = True
            if event["type"] == "session_stopped":
                break
        assert saw_refined is False
