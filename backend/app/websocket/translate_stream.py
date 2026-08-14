"""
WebSocket endpoint for the live audio -> transcript -> translation pipeline.

The transport layer owns the connection: it accepts sockets, validates and
routes client control messages, and manages per-session lifecycle. Real ASR /
translation providers are not wired in yet (see DEVELOPMENT_PLAN.md), so this
transport currently does two things:

1. Accepts the audio stream and tracks how much real audio arrived
   (chunks/bytes/seconds), confirming progress to the client with a
   throttled ``audio_received`` event so the browser -> backend audio path is
   observable end to end.
2. Maintains the session registry and lifecycle (start/stop) contracts.

No transcripts or translations are produced or faked at this stage. The event
loop is never blocked: audio handling is O(1) bookkeeping and every network
write is guarded by a per-session lock.
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
        self._send_lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return self.config is not None

    async def apply_config(self, config: schemas.SessionConfiguration) -> None:
        self.config = config
        self.state = "configured"
        self.bytes_per_second = self._bytes_per_second(config)

    async def receive_audio(self, chunk: bytes) -> None:
        if not self.configured:
            await self._send_error("no_active_session", "Configure a session before sending audio")
            return
        now = time.monotonic()
        self.received_chunks += 1
        self.received_bytes += len(chunk)
        self.audio_seconds += len(chunk) / self.bytes_per_second
        self.last_audio_at = now

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
        await self.send_event(
            schemas.SessionStoppedEvent(session_id=self.session_id, reason=reason)
        )

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
        - JSON {"type": "stop_session", "session_id": str}
      Server -> Client (all JSON envelopes):
        - session_started / audio_received / error / session_stopped
        (transcript/translation events appear once ASR is wired in)
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
            session_manager.remove(session.session_id)
            logger.info("ws_session_ended", session_id=session.session_id, reason="connection_closed")
