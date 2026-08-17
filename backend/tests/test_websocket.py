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
                    segment_id="seg-0",
                    text="We need to discuss",
                    is_final=False,
                    asr_latency_ms=120.0,
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

        partial_latency = ws.receive_json()
        assert partial_latency["type"] == "latency"
        assert partial_latency["segment_id"] == "seg-0"
        assert partial_latency["asr_partial_ms"] == 120.0

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
        assert latency["asr_final_ms"] == 180.0

        translation = ws.receive_json()
        # The pending_translation event is sent immediately when the transcript
        # is finalized, before NLLB inference starts.
        assert translation["type"] == "pending_translation"
        assert translation["segment_id"] == "seg-0"
        assert translation["source_text"] == "We need to discuss the project."

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
        # Server-side end-to-end (T2 -> T6) = asr final + translation.
        assert translation_latency["asr_final_ms"] == 180.0
        assert (
            translation_latency["end_to_end_ms"]
            >= translation_latency["translation_ms"]
        )

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


def _drain_until(
    ws,
    event_type: str,
    count: int,
    max_events: int = 30,
    *,
    skip_pred=None,
) -> list[dict]:
    found = []
    for _ in range(max_events):
        event = ws.receive_json()
        if event["type"] == event_type:
            if skip_pred and skip_pred(event):
                continue
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
        translations = _drain_until(
            ws,
            "translation",
            2,
            skip_pred=lambda e: e.get("provider") == "pending",
        )
        assert [t["segment_id"] for t in translations] == ["seg-1", "seg-2"]
        assert [t["translated_text"] for t in translations] == [
            "[First idea.]",
            "[Second idea.]",
        ]
        assert [c["segment_id"] for c in translator.calls] == ["seg-1", "seg-2"]
        assert translator.calls[0]["is_final"] is True

        _stop_and_await(ws, session_id)
        assert translator.closed is True


def test_translation_queue_drops_stale_items(
    fake_asr_factory, slow_translation_factory
) -> None:
    """When translations are slower than the utterance rate, stale items are
    dropped from the bounded queue and only the most recent is translated."""
    session_id = "tr-drop"
    with TestClient(app).websocket_connect("/ws/translate") as ws:
        _configure(ws, session_id)
        provider = fake_asr_factory[-1]

        provider.script(
            [
                TranscriptSegment(segment_id=f"seg-{i}", text=f"Sentence {i}.", is_final=True)
                for i in range(5)
            ]
        )

        translations: list[dict] = []
        skipped: list[dict] = []
        for _ in range(50):
            event = ws.receive_json()
            if event["type"] == "translation":
                translations.append(event)
            elif event["type"] == "translation_skipped":
                skipped.append(event)
            elif event["type"] == "session_stopped":
                break
            # Stop once we have enough evidence.
            if len(translations) >= 2 and len(skipped) >= 1:
                _stop_and_await(ws, session_id)
                break

        assert len(skipped) >= 1, f"Expected skipped events, got {skipped}"
        skipped_ids = [s["segment_id"] for s in skipped]
        assert all(sID.startswith("seg-") for sID in skipped_ids)

        # The last translation received must be for seg-4 (the most recent).
        assert translations[-1]["segment_id"] == "seg-4"


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
        translation = _drain_until(
            ws,
            "translation",
            1,
            skip_pred=lambda e: e.get("provider") == "pending",
        )[0]
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
        translations = _drain_until(
            ws,
            "translation",
            1,
            skip_pred=lambda e: e.get("provider") == "pending",
        )
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

        translation = next(
            e
            for e in events
            if e["type"] == "translation" and e.get("provider") != "pending"
        )
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

        translations = _drain_until(
            ws,
            "translation",
            2,
            skip_pred=lambda e: e.get("provider") == "pending",
        )
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


# --- Latency instrumentation + LLM call avoidance ---------------------------


def test_looks_clean_heuristic() -> None:
    clean = translate_stream._looks_clean
    assert clean("This sentence is already clean.") is True
    assert clean("The project ships on Friday.") is True
    # Needs the LLM: no terminal punctuation, lowercase start, fragments...
    assert clean("the project ships on friday") is False
    assert clean("no punctuation") is False
    assert clean("Short.") is False  # fragment (< 12 chars)
    assert clean("This has  double spaces.") is False
    assert clean("This has repeated repeated words.") is False
    assert clean("API API needs cleanup.") is False
    assert clean("HELLO WORLD THIS IS LOUD.") is False


def test_refinement_is_skipped_for_clean_finals(
    monkeypatch, fake_asr_factory, fake_translation_factory, fake_llm_factory
) -> None:
    session_id = "ref-clean"
    monkeypatch.setattr(translate_stream, "_looks_clean", lambda text: True)
    with TestClient(app).websocket_connect("/ws/translate") as ws:
        _configure(ws, session_id)
        provider = fake_asr_factory[-1]
        refiner = fake_llm_factory[-1]
        provider.script(
            [TranscriptSegment(segment_id="seg-1", text="Fine.", is_final=True)]
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
        # The LLM was never called for a transcript that needs no work.
        assert refiner.calls == []


# --- WebSocket Origin policy -------------------------------------------------


def test_origin_policy_allows_whitelisted_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import Settings

    monkeypatch.setattr(
        translate_stream,
        "get_settings",
        lambda: Settings(ws_allowed_origins=["https://app.example.com"]),
    )
    with TestClient(app).websocket_connect(
        "/ws/translate", headers={"Origin": "https://app.example.com"}
    ) as ws:
        ws.send_json({"type": "start_session", "session_id": "origin-ok"})
        started = _configure(ws, "origin-ok")
        assert started["type"] == "session_started"


def test_origin_policy_rejects_disallowed_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    from starlette.websockets import WebSocketDisconnect

    from app.config import Settings

    monkeypatch.setattr(
        translate_stream,
        "get_settings",
        lambda: Settings(ws_allowed_origins=["https://app.example.com"]),
    )
    with (
        pytest.raises(WebSocketDisconnect) as exc_info,
        TestClient(app).websocket_connect(
            "/ws/translate", headers={"Origin": "https://evil.example.com"}
        ) as ws,
    ):
        ws.receive_json()
    assert exc_info.value.code == 1008


def test_origin_policy_rejects_missing_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    from starlette.websockets import WebSocketDisconnect

    from app.config import Settings

    monkeypatch.setattr(
        translate_stream,
        "get_settings",
        lambda: Settings(ws_allowed_origins=["https://app.example.com"]),
    )
    with (
        pytest.raises(WebSocketDisconnect) as exc_info,
        TestClient(app).websocket_connect("/ws/translate") as ws,
    ):
        ws.receive_json()
    assert exc_info.value.code == 1008
