"""
WebSocket endpoint for the live audio -> transcript pipeline.

The transport layer owns the connection: it accepts sockets, validates and
routes client control messages, and manages per-session lifecycle. It never
talks to Deepgram directly -- all ASR happens behind the `ASRProvider`
interface (`app/services/asr/base.py`), so this file stays provider-agnostic.

Per-session flow:
  1. ``session_configuration`` creates the configured ``ASRProvider`` and
     starts a background task that connects upstream and streams
     ``TranscriptSegment`` events back to the client (partial immediately,
     final when the provider finalizes an utterance).
  2. Binary audio frames are forwarded to the provider's ``send_audio`` --
     an O(1) queue push -- so the event loop is never blocked by ASR I/O.
  3. Client ``vad_event`` messages are interpreted by ``SilenceDetector`` and
     turned into ``ASRProvider.notify_silence()`` endpointing hints.
  4. ``stop_session`` / disconnect cancels the ASR task and closes the
     provider.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.models import schemas
from app.services.asr import create_asr_provider
from app.services.asr.base import ASRProvider, ASRProviderError
from app.services.vad.base import SilenceDetector

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/ws", tags=["websocket"])

_AUDIO_BYTES_PER_SECOND_BY_ENCODING = {"linear16": 2, "opus": 1}

# How often (ms) the server reports cumulative audio stats back to the client.
_AUDIO_ACK_INTERVAL_MS = 1000


class Session:
    """One active translation session bound to a single WebSocket connection."""

    def __init__(self, session_id: str, websocket: WebSocket, settings: Settings) -> None:
        self.session_id = session_id
        self.websocket = websocket
        self.settings = settings
        self.config: schemas.SessionConfiguration | None = None
        self.state = "created"
        self.received_chunks = 0
        self.received_bytes = 0
        self.audio_seconds = 0.0
        self.last_audio_at = 0.0
        self.last_ack_at = 0.0
        self.bytes_per_second = 32000.0
        self.last_vad_event: schemas.VADEventMessage | None = None
        self.speech_started_at_ms: int | None = None
        self.asr: ASRProvider | None = None
        self.asr_task: asyncio.Task[None] | None = None
        self.silence_detector: SilenceDetector | None = None
        self._send_lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return self.config is not None

    async def apply_config(self, config: schemas.SessionConfiguration) -> None:
        self.config = config
        self.state = "configured"
        self.bytes_per_second = self._bytes_per_second(config)
        self.silence_detector = SilenceDetector(
            finalize_ms=self.settings.silence_finalize_ms,
            min_speech_ms=self.settings.silence_min_speech_ms,
        )
        self.asr = create_asr_provider()
        self.asr_task = asyncio.create_task(
            self._run_asr(), name=f"asr-{self.session_id}"
        )

    async def receive_audio(self, chunk: bytes) -> None:
        if not self.configured:
            await self._send_error("no_active_session", "Configure a session before sending audio")
            return
        now = time.monotonic()
        self.received_chunks += 1
        self.received_bytes += len(chunk)
        self.audio_seconds += len(chunk) / self.bytes_per_second
        self.last_audio_at = now

        if self.asr is not None:
            await self.asr.send_audio(chunk)

        if now - self.last_ack_at >= _AUDIO_ACK_INTERVAL_MS / 1000:
            self.last_ack_at = now
            await self.send_event(
                schemas.AudioReceivedEvent(
                    session_id=self.session_id,
                    chunks=self.received_chunks,
                    bytes=self.received_bytes,
                    audio_seconds=round(self.audio_seconds, 3),
                )
            )
            logger.info(
                "audio_received",
                session_id=self.session_id,
                chunks=self.received_chunks,
                bytes=self.received_bytes,
                audio_seconds=round(self.audio_seconds, 3),
            )

    async def stop(self, reason: str) -> None:
        if self.state == "stopped":
            return
        self.state = "stopped"
        task = self.asr_task
        self.asr_task = None
        current = asyncio.current_task()
        if task is not None and not task.done() and task is not current:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                logger.debug("asr_task_cancel", session_id=self.session_id)
        asr = self.asr
        self.asr = None
        if asr is not None:
            try:
                await asr.close()
            except Exception:
                logger.debug("asr_close_failed", session_id=self.session_id)
        await self.send_event(
            schemas.SessionStoppedEvent(session_id=self.session_id, reason=reason)
        )

    async def _run_asr(self) -> None:
        """Connect the ASR provider and stream transcript events to the client."""
        config = self.config
        if config is None or self.asr is None:
            return
        try:
            await self.asr.connect(
                sample_rate=config.sample_rate,
                encoding=config.encoding,
                language=config.source_language,
            )
        except ASRProviderError as exc:
            await self.send_event(
                schemas.ErrorMessage(
                    session_id=self.session_id, code=exc.code, message=exc.message
                )
            )
            await self.stop(reason="asr_error")
            return

        try:
            async for segment in self.asr.stream():
                await self.send_event(
                    schemas.TranscriptEvent(
                        type="final_transcript" if segment.is_final else "partial_transcript",
                        session_id=self.session_id,
                        segment_id=segment.segment_id,
                        text=segment.text,
                        is_final=segment.is_final,
                        start_ms=segment.start_ms,
                        end_ms=segment.end_ms,
                        confidence=segment.confidence,
                    )
                )
                if segment.asr_latency_ms is not None:
                    await self.send_event(
                        schemas.LatencyEvent(
                            session_id=self.session_id,
                            segment_id=segment.segment_id,
                            asr_ms=round(segment.asr_latency_ms, 1),
                        )
                    )
        except asyncio.CancelledError:
            pass
        except ASRProviderError as exc:
            await self.send_event(
                schemas.ErrorMessage(
                    session_id=self.session_id, code=exc.code, message=exc.message
                )
            )
            await self.stop(reason="asr_error")
        finally:
            asr = self.asr
            if asr is not None:
                try:
                    await asr.close()
                except Exception:
                    logger.debug("asr_close_failed", session_id=self.session_id)

    async def send_event(self, event: schemas.ServerEvent) -> None:
        async with self._send_lock:
            try:
                await self.websocket.send_json(event.model_dump())
            except Exception:
                logger.debug("ws_send_failed", session_id=self.session_id, event=event.type)

    async def _send_error(self, code: str, message: str) -> None:
        await self.send_event(
            schemas.ErrorMessage(
                session_id=self.session_id,
                code=code,
                message=message,
            )
        )

    @staticmethod
    def _bytes_per_second(config: schemas.SessionConfiguration) -> float:
        factor = _AUDIO_BYTES_PER_SECOND_BY_ENCODING.get(config.encoding, 2)
        return max(1.0, float(config.sample_rate) * factor)


class SessionManager:
    """Registry of live sessions keyed by session id."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self, websocket: WebSocket, session_id: str) -> Session:
        session = Session(session_id, websocket, get_settings())
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def remove(self, session_id: str) -> Session | None:
        return self._sessions.pop(session_id, None)


session_manager = SessionManager()


async def _send_error(websocket: WebSocket, code: str, message: str) -> None:
    try:
        await websocket.send_json(
            schemas.ErrorMessage(code=code, message=message).model_dump()
        )
    except Exception:
        logger.debug("ws_send_error_ignored", code=code)


async def _handle_start_session(
    websocket: WebSocket,
    payload: dict,
    current: Session | None,
) -> Session | None:
    try:
        request = schemas.StartSessionRequest.model_validate(payload)
    except ValidationError as exc:
        await _send_error(websocket, "invalid_message", f"Invalid start_session: {exc}")
        return current

    if current is not None:
        await _send_error(
            websocket, "session_already_active", "A session is already active on this connection"
        )
        return current

    session_id = request.session_id or uuid.uuid4().hex
    if session_manager.get(session_id) is not None:
        await _send_error(websocket, "session_exists", f"Session {session_id} already exists")
        return current

    session = session_manager.create(websocket, session_id)
    logger.info("session_created", session_id=session_id, waiting_for_config=True)
    return session


async def _handle_configuration(
    websocket: WebSocket,
    payload: dict,
    current: Session | None,
) -> Session | None:
    try:
        config = schemas.SessionConfiguration.model_validate(payload)
    except ValidationError as exc:
        await _send_error(websocket, "invalid_message", f"Invalid session_configuration: {exc}")
        return current

    session = session_manager.get(config.session_id)
    if session is None:
        session = session_manager.create(websocket, config.session_id)
    elif session.websocket is not websocket:
        await _send_error(
            websocket,
            "session_in_use",
            f"Session {config.session_id} belongs to another connection",
        )
        return current

    if current is not None and current is not session:
        await _send_error(
            websocket,
            "cannot_switch_sessions",
            "Cannot reconfigure a different session on this connection",
        )
        return current

    await session.apply_config(config)
    await session.send_event(
        schemas.SessionStartedEvent(
            session_id=session.session_id,
            configuration=config,
        )
    )
    logger.info(
        "session_configured",
        session_id=session.session_id,
        source_language=config.source_language,
        target_language=config.target_language,
        audio_source=config.audio_source,
    )
    return session


async def _handle_stop_session(
    websocket: WebSocket,
    payload: dict,
    current: Session | None,
) -> Session | None:
    try:
        request = schemas.StopSessionRequest.model_validate(payload)
    except ValidationError as exc:
        await _send_error(websocket, "invalid_message", f"Invalid stop_session: {exc}")
        return current

    session = session_manager.get(request.session_id)
    if session is None or session.websocket is not websocket:
        await _send_error(websocket, "no_active_session", "No matching session on this connection")
        return current

    await session.stop(reason="client_request")
    session_manager.remove(request.session_id)
    logger.info("session_stopped", session_id=request.session_id)
    return None


async def _handle_audio_chunk_control(
    websocket: WebSocket,
    payload: dict,
    current: Session | None,
) -> None:
    try:
        schemas.AudioChunkMessage.model_validate(payload)
    except ValidationError as exc:
        await _send_error(websocket, "invalid_message", f"Invalid audio_chunk: {exc}")
        return
    if current is None:
        await _send_error(websocket, "no_active_session", "No session on this connection")
        return
    logger.debug("audio_chunk_control", session_id=current.session_id)


async def _handle_vad_event(
    websocket: WebSocket,
    payload: dict,
    current: Session | None,
) -> None:
    try:
        message = schemas.VADEventMessage.model_validate(payload)
    except ValidationError as exc:
        await _send_error(websocket, "invalid_message", f"Invalid vad_event: {exc}")
        return
    if current is None or current.session_id != message.session_id:
        await _send_error(websocket, "no_active_session", "No matching session on this connection")
        return

    if message.event == "speech_started":
        current.speech_started_at_ms = message.timestamp_ms

    # Stash the latest transition so utterance finalization can use the last
    # measured silence gap (duration_ms on silence_detected).
    current.last_vad_event = message
    logger.debug(
        "vad_event",
        session_id=message.session_id,
        vad_event=message.event,
        timestamp_ms=message.timestamp_ms,
        duration_ms=message.duration_ms,
    )

    # A client-detected silence boundary becomes an endpointing hint for the
    # ASR provider (Deepgram "Finalize"), but only when the gap is significant
    # enough per server-side SilenceDetector policy.
    if message.event == "silence_detected" and current.asr is not None:
        detector = current.silence_detector
        duration_ms = message.duration_ms or 0
        if detector is not None:
            if current.speech_started_at_ms is not None:
                speech_ms = max(0, message.timestamp_ms - current.speech_started_at_ms)
            else:
                speech_ms = current.settings.silence_min_speech_ms + 1
            if detector.should_finalize(
                silence_duration_ms=duration_ms, speech_duration_ms=speech_ms
            ):
                await current.asr.notify_silence(duration_ms)


async def _handle_text_message(
    websocket: WebSocket,
    raw_text: str,
    current: Session | None,
) -> Session | None:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        await _send_error(websocket, "invalid_json", "Message is not valid JSON")
        return current

    if not isinstance(payload, dict):
        await _send_error(websocket, "invalid_message", "Message must be a JSON object")
        return current

    message_type = payload.get("type")
    if message_type == schemas.WSClientEventType.START_SESSION.value:
        return await _handle_start_session(websocket, payload, current)
    if message_type == schemas.WSClientEventType.SESSION_CONFIGURATION.value:
        return await _handle_configuration(websocket, payload, current)
    if message_type == schemas.WSClientEventType.AUDIO_CHUNK.value:
        await _handle_audio_chunk_control(websocket, payload, current)
        return current
    if message_type == schemas.WSClientEventType.VAD_EVENT.value:
        await _handle_vad_event(websocket, payload, current)
        return current
    if message_type == schemas.WSClientEventType.STOP_SESSION.value:
        return await _handle_stop_session(websocket, payload, current)

    await _send_error(websocket, "unknown_message", f"Unknown message type: {message_type!r}")
    return current


@router.websocket("/translate")
async def translate_stream(websocket: WebSocket) -> None:
    """
    Protocol (see app/models/schemas.py for exact payloads):
      Client -> Server:
        - JSON {"type": "start_session", "session_id"?: str}
        - JSON {"type": "session_configuration", ...SessionConfiguration}
        - binary frames: raw PCM16/Opus audio chunks
        - JSON {"type": "audio_chunk", "session_id": str} (control, optional)
        - JSON {"type": "vad_event", "session_id": str, "event": str, ...}
        - JSON {"type": "stop_session", "session_id": str}
      Server -> Client (all JSON envelopes):
        - session_started / audio_received / error / session_stopped
        - partial_transcript / final_transcript (streamed ASR results)
        - latency (per-segment asr_ms timing)
    """
    await websocket.accept()
    session: Session | None = None
    logger.info("ws_connected", websocket=id(websocket))

    try:
        while True:
            message = await websocket.receive()

            if message.get("type") == "websocket.disconnect":
                break

            if "text" in message and message["text"] is not None:
                session = await _handle_text_message(websocket, message["text"], session)
                continue

            if "bytes" in message and message["bytes"] is not None:
                chunk = message["bytes"]
                if len(chunk) > get_settings().max_ws_message_bytes:
                    await _send_error(websocket, "message_too_large", "Audio chunk exceeds size limit")
                    continue
                if session is None:
                    await _send_error(
                        websocket, "no_active_session", "Start and configure a session before sending audio"
                    )
                    continue
                await session.receive_audio(chunk)
                continue

    except WebSocketDisconnect:
        logger.info("ws_disconnected", websocket=id(websocket))
    except Exception as exc:
        logger.exception("ws_error", websocket=id(websocket))
        await _send_error(websocket, "internal_error", str(exc))
    finally:
        if session is not None:
            await session.stop(reason="connection_closed")
            session_manager.remove(session.session_id)
            logger.info("ws_session_ended", session_id=session.session_id, reason="connection_closed")
