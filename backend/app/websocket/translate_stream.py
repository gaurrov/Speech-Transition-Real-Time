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
  4. Finalized utterances are queued to a per-session translation worker that
     calls the configured ``TranslationProvider`` (hybrid: cloud -> NLLB
     fallback) and streams ``TranslationEvent`` + ``translation_ms`` latency
     back to the client. Partials are never translated.
  5. ``stop_session`` / disconnect cancels both tasks and closes providers.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import time
import uuid

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from starlette.websockets import WebSocketState

from app.config import Settings, get_settings
from app.models import schemas
from app.services.asr import create_asr_provider
from app.services.asr.base import ASRProvider, ASRProviderError
from app.services.llm import create_llm_provider
from app.services.llm.base import LLMProvider
from app.services.translation import create_translation_provider
from app.services.translation.base import TranslationError, TranslationProvider
from app.services.vad.base import SilenceDetector

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/ws", tags=["websocket"])

_AUDIO_BYTES_PER_SECOND_BY_ENCODING = {"linear16": 2, "opus": 1}

# How often (ms) the server reports cumulative audio stats back to the client.
_AUDIO_ACK_INTERVAL_MS = 1000


def _looks_clean(text: str) -> bool:
    """Cheap heuristic: is this transcript already well-formed enough to skip
    an LLM refinement round-trip?

    Conservative by design -- it only returns True when the text almost
    certainly needs no correction, so quality-sensitive cases still reach the
    LLM:
      * ends in sentence punctuation
      * starts with a capital letter
      * no double spaces, no repeated words, no long all-caps runs
    Short/fragmentary utterances are never skipped (they usually need the LLM).
    """
    t = text.strip()
    if not t:
        return True
    if len(t) < 12:
        return False
    if t[-1] not in ".!?":
        return False
    if t[0].islower():
        return False
    if "  " in t:
        return False
    words = t.split()
    if any(a == b for a, b in itertools.pairwise(words)):
        return False
    # No long all-caps run (e.g. an uncorrected acronym sequence like "API API").
    return not any(len(w) >= 5 and w.isupper() for w in words)


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
        self.translator: TranslationProvider | None = None
        self.translation_queue: (
            asyncio.Queue[tuple[str, str, float | None]] | None
        ) = None
        self.translation_task: asyncio.Task[None] | None = None
        # Async LLM refinement: a separate, non-blocking worker that corrects
        # finalized segments after the live caption/translation already
        # reached the client. Never awaited on the hot path.
        self.refiner: LLMProvider | None = None
        self.refinement_queue: (
            asyncio.Queue[tuple[str, str, str, list[str]]] | None
        ) = None
        self.refinement_task: asyncio.Task[None] | None = None
        self.context_window: list[str] = []
        self.refinement_context_size = 4
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
        await self._teardown_providers()
        self.asr = create_asr_provider()
        self.asr_task = asyncio.create_task(
            self._run_asr(), name=f"asr-{self.session_id}"
        )
        self.translator = create_translation_provider()
        self.translation_queue = asyncio.Queue()
        self.translation_task = asyncio.create_task(
            self._run_translation(), name=f"translation-{self.session_id}"
        )

        self.refinement_context_size = max(0, self.settings.llm_context_segments)
        self.context_window = []
        self.refiner = create_llm_provider()
        if self.refiner is not None:
            self.refinement_queue = asyncio.Queue()
            self.refinement_task = asyncio.create_task(
                self._run_refinement(), name=f"refinement-{self.session_id}"
            )
        else:
            self.refinement_queue = None
            self.refinement_task = None

    async def _teardown_providers(self) -> None:
        """Cancel/close any providers from a previous configuration (defensive)."""
        for task in (self.asr_task, self.translation_task, self.refinement_task):
            if task is not None and not task.done() and task is not asyncio.current_task():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    logger.debug("provider_task_cancel", session_id=self.session_id)
        for provider in (self.asr, self.translator, self.refiner):
            if provider is not None:
                try:
                    await provider.close()
                except Exception:
                    logger.debug("provider_close_failed", session_id=self.session_id)
        self.asr = None
        self.asr_task = None
        self.translator = None
        self.translation_queue = None
        self.translation_task = None
        self.refiner = None
        self.refinement_queue = None
        self.refinement_task = None
        self.context_window = []

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
        current = asyncio.current_task()
        for attr in ("asr_task", "translation_task", "refinement_task"):
            task = getattr(self, attr)
            setattr(self, attr, None)
            if task is not None and not task.done() and task is not current:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    logger.debug("session_task_cancel", session_id=self.session_id)
        for attr, provider in (
            ("asr", self.asr),
            ("translator", self.translator),
            ("refiner", self.refiner),
        ):
            setattr(self, attr, None)
            if provider is not None:
                try:
                    await provider.close()
                except Exception:
                    logger.debug("provider_close_failed", session_id=self.session_id)
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
                    # asr_latency_ms is T2 (content received) -> result emitted.
                    latency = round(segment.asr_latency_ms, 1)
                    if segment.is_final:
                        await self.send_event(
                            schemas.LatencyEvent(
                                session_id=self.session_id,
                                segment_id=segment.segment_id,
                                asr_ms=latency,
                                asr_final_ms=latency,
                            )
                        )
                    else:
                        await self.send_event(
                            schemas.LatencyEvent(
                                session_id=self.session_id,
                                segment_id=segment.segment_id,
                                asr_ms=latency,
                                asr_partial_ms=latency,
                            )
                        )
                # Only finalized, meaningful utterances are translated --
                # partials stream straight to the client and never enqueue.
                # The ASR final latency is threaded through so the translation
                # latency report can carry a true server-side end-to-end figure.
                if segment.is_final and self.translation_queue is not None:
                    self.translation_queue.put_nowait(
                        (
                            segment.segment_id,
                            segment.text,
                            segment.asr_latency_ms,
                        )
                    )

                # Async LLM refinement: enqueue right after finalization, but
                # NEVER await the result before the final transcript/translation
                # events have already been sent above. A rolling window of prior
                # finalized segments is captured as context.
                if (
                    segment.is_final
                    and self.refinement_queue is not None
                    and self.refiner is not None
                ):
                    context = list(self.context_window)
                    self.refinement_queue.put_nowait(
                        (segment.segment_id, segment.text, config.source_language, context)
                    )
                    self.context_window.append(segment.text)
                    if len(self.context_window) > self.refinement_context_size:
                        self.context_window = self.context_window[-self.refinement_context_size:]
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

    async def _run_translation(self) -> None:
        """Translate finalized utterances in order and stream results to the client.

        A single queue + worker per session keeps translation results in
        utterance order. A translation failure is non-fatal: the error is
        reported but the session (and all later utterances) keep going.
        """
        config = self.config
        translator = self.translator
        queue = self.translation_queue
        if config is None or translator is None or queue is None:
            return
        while True:
            segment_id, text, asr_final_ms = await queue.get()
            started = time.monotonic()
            try:
                result = await translator.translate(
                    segment_id=segment_id,
                    text=text,
                    source_language=config.source_language,
                    target_language=config.target_language,
                    is_final=True,
                )
            except asyncio.CancelledError:
                raise
            except TranslationError as exc:
                logger.warning(
                    "translation_failed",
                    session_id=self.session_id,
                    code=exc.code,
                    message=exc.message,
                )
                await self.send_event(
                    schemas.ErrorMessage(
                        session_id=self.session_id,
                        code="translation_failed",
                        message=exc.message,
                    )
                )
                continue
            except Exception as exc:
                logger.warning(
                    "translation_failed",
                    session_id=self.session_id,
                    error=str(exc),
                )
                await self.send_event(
                    schemas.ErrorMessage(
                        session_id=self.session_id,
                        code="translation_failed",
                        message=str(exc),
                    )
                )
                continue

            translation_ms = round((time.monotonic() - started) * 1000, 1)
            # Server-side live-path end-to-end: T2 -> T6. ASR final latency
            # ends at T4 and translation begins immediately after (T5 ~ T4),
            # so end_to_end = asr_final + translation. Refinement is excluded.
            end_to_end_ms = (
                round(asr_final_ms + translation_ms, 1)
                if asr_final_ms is not None
                else None
            )
            await self.send_event(
                schemas.TranslationEvent(
                    session_id=self.session_id,
                    segment_id=result.segment_id,
                    source_text=result.source_text,
                    translated_text=result.translated_text,
                    source_language=result.source_language,
                    target_language=result.target_language,
                    is_final=result.is_final,
                    provider=result.provider,
                )
            )
            await self.send_event(
                schemas.LatencyEvent(
                    session_id=self.session_id,
                    segment_id=result.segment_id,
                    asr_final_ms=round(asr_final_ms, 1)
                    if asr_final_ms is not None
                    else None,
                    translation_ms=translation_ms,
                    end_to_end_ms=end_to_end_ms,
                )
            )

    async def _run_refinement(self) -> None:
        """Correct finalized segments in the background, never blocking anything.

        Runs as its own task with its own queue, fully independent of the ASR
        and translation tasks. A failure (timeout, API error, invalid output)
        is logged and the original transcript/translation is kept as-is -- the
        live captioning path never notices.
        """
        queue = self.refinement_queue
        refiner = self.refiner
        if queue is None or refiner is None:
            return
        while True:
            segment_id, text, language, context = await queue.get()
            if self.settings.llm_skip_when_clean and _looks_clean(text):
                logger.debug(
                    "refinement_skipped_clean",
                    session_id=self.session_id,
                    segment_id=segment_id,
                )
                continue
            started = time.monotonic()
            result = None
            try:
                result = await refiner.refine(
                    segment_id=segment_id,
                    text=text,
                    language=language,
                    context=context,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "refinement_failed",
                    session_id=self.session_id,
                    segment_id=segment_id,
                    error=str(exc),
                )
            finally:
                # Refinement latency is reported separately from the live path,
                # even when the attempt itself failed.
                refinement_ms = round((time.monotonic() - started) * 1000, 1)
                await self.send_event(
                    schemas.LatencyEvent(
                        session_id=self.session_id,
                        segment_id=segment_id,
                        refinement_ms=refinement_ms,
                    )
                )
            if result is not None and result.changed:
                await self.send_event(
                    schemas.RefinedTranscriptEvent(
                        session_id=self.session_id,
                        segment_id=segment_id,
                        refined_text=result.refined_text,
                        changed=True,
                    )
                )

    async def send_event(self, event: schemas.ServerEvent) -> None:
        async with self._send_lock:
            try:
                # Serialize once to JSON-safe primitives (compact, like the
                # built-in send_json); audio stays binary on the wire.
                text = json.dumps(
                    event.model_dump(mode="json"), separators=(",", ":"), ensure_ascii=False
                )
                await self.websocket.send_text(text)
            except Exception:
                logger.debug("ws_send_failed", session_id=self.session_id, event_type=event.type)

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
        if session.websocket.client_state == WebSocketState.DISCONNECTED:
            # The old connection already died; take over the session so a
            # legitimate reconnect with the same session_id succeeds even
            # before the server processes the old socket's teardown.
            logger.info(
                "session_takeover",
                session_id=config.session_id,
                old_websocket=id(session.websocket),
                new_websocket=id(websocket),
            )
            session.websocket = websocket
        else:
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

    # Optional Origin allowlist (cross-site WebSocket hijacking protection).
    # Browsers do not enforce CORS on WebSocket handshakes, so the server must
    # check the Origin itself when a policy is configured.
    allowed_origins = get_settings().ws_allowed_origins
    if allowed_origins:
        origin = websocket.headers.get("origin")
        if origin is None or origin not in allowed_origins:
            logger.warning("ws_origin_rejected", websocket=id(websocket), origin=origin)
            await websocket.close(code=1008)
            return

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
