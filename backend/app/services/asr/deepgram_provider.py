"""
DeepgramASRProvider: streaming ASR via Deepgram's live WebSocket API.

Implementation notes
--------------------
* Audio is pushed over the same WebSocket that receives interim (`Results`
  with ``is_final=false``) and final (`is_final=true``) transcripts.
* ``connect()`` never blocks on the network: it spawns a reader task (owns the
  connection, handles reconnects with backoff) and a sender task (drains a
  bounded queue so audio forwarding is O(1) and never back-pressures the
  browser -> backend WebSocket).
* Partial results are emitted the moment they arrive; final results when
  Deepgram ends an utterance (endpointing / Finalize / UtteranceEnd).
* A short ``Finalize`` control message is sent via ``notify_silence()`` when
  the client-side VAD reports a silence boundary, giving Deepgram an explicit
  endpointing hint.
* The provider never talks to the rest of the app in Deepgram terms: it emits
  ``TranscriptSegment`` and raises ``ASRProviderError``.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import structlog
import websockets
from websockets.protocol import State

from app.config import Settings, get_settings
from app.models.schemas import TranscriptSegment
from app.services.asr.base import ASRProvider, ASRProviderError

logger = structlog.get_logger(__name__)

_AUDIO_BYTES_PER_SECOND_BY_ENCODING = {"linear16": 2, "opus": 1}
_STREAM_CLOSED = object()


@dataclass
class _QueueItem:
    kind: str  # "audio" | "control"
    payload: bytes | dict[str, Any]


class DeepgramASRProvider(ASRProvider):
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._uid = uuid.uuid4().hex[:8]

        self._sample_rate = 16_000
        self._encoding = "linear16"
        self._language = "auto"
        self._bytes_per_second = 32_000.0

        self._ws: websockets.ClientConnection | None = None
        self._connected = asyncio.Event()
        self._closed = asyncio.Event()
        self._fatal_error: ASRProviderError | None = None

        buffer_items = max(4, round(self._settings.deepgram_audio_buffer_seconds * 10))
        self._audio_in: asyncio.Queue[_QueueItem] = asyncio.Queue(maxsize=buffer_items)
        self._results: asyncio.Queue[TranscriptSegment | None] = asyncio.Queue()

        # ---- utterance tracking (stable segment ids across partial -> final) ----
        self._utterance_index = 0
        self._last_partial_text: str | None = None
        self._seen_final_keys: set[tuple[int, str]] = set()

        # ---- audio receive timeline for audio->ASR latency estimation ----
        self._audio_timeline: deque[tuple[float, float]] = deque()
        self._audio_seconds_sent = 0.0

        self._reader_task: asyncio.Task[None] | None = None
        self._sender_task: asyncio.Task[None] | None = None

    # --- public API ---------------------------------------------------------

    async def connect(self, *, sample_rate: int, encoding: str, language: str) -> None:
        self._sample_rate = sample_rate
        self._encoding = encoding
        self._language = language
        factor = _AUDIO_BYTES_PER_SECOND_BY_ENCODING.get(encoding, 2)
        self._bytes_per_second = max(1.0, float(sample_rate) * factor)

        if not self._settings.deepgram_api_key:
            raise ASRProviderError(
                "deepgram_config", "DEEPGRAM_API_KEY is not configured on the backend"
            )

        self._reader_task = asyncio.create_task(self._reader(), name=f"dg-reader-{self._uid}")
        self._sender_task = asyncio.create_task(self._sender(), name=f"dg-sender-{self._uid}")

    async def send_audio(self, chunk: bytes) -> None:
        if self._closed.is_set():
            return
        seconds = len(chunk) / self._bytes_per_second
        self._audio_seconds_sent += seconds
        self._audio_timeline.append((self._audio_seconds_sent, time.monotonic()))
        # Keep a bounded view of the recent audio timeline (prune > 60 s old).
        cutoff = self._audio_seconds_sent - 60.0
        while self._audio_timeline and self._audio_timeline[0][0] < cutoff:
            self._audio_timeline.popleft()

        if self._audio_in.full():
            # Streaming audio can't pause; on reconnect backlog drop the oldest
            # frame so latency stays bounded instead of growing without limit.
            try:
                self._audio_in.get_nowait()
            except asyncio.QueueEmpty:
                pass
            logger.warning("asr_audio_dropped_oldest", provider="deepgram")
        self._audio_in.put_nowait(_QueueItem(kind="audio", payload=chunk))

    async def notify_silence(self, duration_ms: int) -> None:
        if self._closed.is_set():
            return
        logger.debug("asr_notify_silence", provider="deepgram", duration_ms=duration_ms)
        try:
            self._audio_in.put_nowait(_QueueItem(kind="control", payload={"type": "Finalize"}))
        except asyncio.QueueFull:
            logger.warning("asr_control_dropped_queue_full", provider="deepgram")

    async def stream(self) -> AsyncIterator[TranscriptSegment]:
        while True:
            segment = await self._results.get()
            if segment is None:
                break
            yield segment
        if self._fatal_error is not None:
            raise self._fatal_error

    async def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        self._connected.set()  # release anyone waiting on connection
        for task in (self._reader_task, self._sender_task):
            if task is not None and not task.done():
                task.cancel()
        for task in (self._reader_task, self._sender_task):
            if task is not None:
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    logger.debug("asr_task_teardown", provider="deepgram")
        ws = self._ws
        self._ws = None
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                logger.debug("asr_ws_close_failed", provider="deepgram")
        # Unblock any consumer still awaiting stream().
        self._results.put_nowait(None)

    # --- internal: connection lifecycle ------------------------------------

    _SMART_FORMAT_LANGUAGES = {"en", "es", "fr", "de", "it", "pt", "nl"}

    def _build_url(self) -> str:
        params: dict[str, str] = {
            "model": self._settings.deepgram_model,
            "interim_results": "true" if self._settings.deepgram_interim_results else "false",
            "endpointing": str(self._settings.deepgram_endpointing_ms),
            "utterance_end_ms": str(self._settings.deepgram_utterance_end_ms),
            "vad_events": "true",
        }

        language = self._language or "auto"
        is_english = language == "en"
        is_auto = language == "auto"

        if self._settings.deepgram_punctuate:
            params["punctuate"] = "true"
        if self._settings.deepgram_smart_format and (is_auto or language in self._SMART_FORMAT_LANGUAGES):
            params["smart_format"] = "true"

        if is_auto:
            params["multilingual"] = "true"
        else:
            params["language"] = language
            if not is_english:
                params["multilingual"] = "true"

        params["encoding"] = "linear16" if self._encoding == "linear16" else self._encoding
        params["sample_rate"] = str(self._sample_rate)

        separator = "&" if "?" in self._settings.deepgram_endpoint else "?"
        return f"{self._settings.deepgram_endpoint}{separator}{urlencode(params)}"

    @staticmethod
    def _safe_response_body(exc: websockets.exceptions.InvalidStatus) -> str:
        """Extract response body from an InvalidStatus exception safely.

        Never logs API keys or authorization tokens.
        """
        if exc.response is None:
            return ""
        try:
            body = exc.response.body
            if body:
                return body.decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        return ""

    async def _open_connection(self) -> websockets.ClientConnection:
        attempts = 0
        while not self._closed.is_set():
            attempts += 1
            try:
                ws = await asyncio.wait_for(
                    websockets.connect(
                        self._build_url(),
                        additional_headers={
                            "Authorization": f"Token {self._settings.deepgram_api_key}",
                            "Accept": "application/json",
                        },
                        ping_interval=None,
                        open_timeout=self._settings.deepgram_connect_timeout_sec,
                        close_timeout=2.0,
                        max_queue=None,
                    ),
                    timeout=self._settings.deepgram_connect_timeout_sec + 5,
                )
                logger.info(
                    "asr_connected",
                    provider="deepgram",
                    model=self._settings.deepgram_model,
                    encoding=self._encoding,
                    language=self._language,
                    sample_rate=self._sample_rate,
                )
                return ws
            except asyncio.CancelledError:
                raise
            except websockets.exceptions.InvalidStatus as exc:
                status = exc.response.status_code if exc.response is not None else 0
                body_detail = self._safe_response_body(exc)
                logger.warning(
                    "asr_handshake_rejected",
                    provider="deepgram",
                    status_code=status,
                    detail=body_detail,
                )
                if status in (401, 403):
                    raise ASRProviderError(
                        "deepgram_auth",
                        "Deepgram authentication failed",
                    ) from exc
                if status == 400:
                    raise ASRProviderError(
                        "deepgram_config",
                        "Deepgram rejected the request parameters",
                    ) from exc
                if status == 429:
                    raise ASRProviderError(
                        "deepgram_rate_limit",
                        "Deepgram rate limit exceeded",
                    ) from exc
                if attempts >= self._settings.deepgram_reconnect_max_attempts:
                    raise ASRProviderError(
                        "deepgram_connection",
                        f"Deepgram connect failed (HTTP {status}) after {attempts} attempts",
                    ) from exc
                await self._backoff(attempts)
            except (TimeoutError, asyncio.TimeoutError) as exc:
                if attempts >= self._settings.deepgram_reconnect_max_attempts:
                    raise ASRProviderError(
                        "deepgram_timeout",
                        f"Deepgram connection timed out after {attempts} attempts",
                    ) from exc
                await self._backoff(attempts)
            except Exception as exc:
                if attempts >= self._settings.deepgram_reconnect_max_attempts:
                    raise ASRProviderError(
                        "deepgram_connection",
                        f"Could not connect to Deepgram: {type(exc).__name__}",
                    ) from exc
                await self._backoff(attempts)
        raise ASRProviderError("deepgram_closed", "Deepgram provider closed")

    async def _backoff(self, attempts: int) -> None:
        delay = (self._settings.deepgram_reconnect_base_delay_ms / 1000) * 2 ** (attempts - 1)
        logger.warning("asr_reconnect_attempt", provider="deepgram", attempt=attempts, delay_ms=round(delay * 1000))
        await asyncio.sleep(delay)

    async def _reader(self) -> None:
        while not self._closed.is_set():
            try:
                ws = await self._open_connection()
            except asyncio.CancelledError:
                raise
            except ASRProviderError as exc:
                if not self._closed.is_set():
                    self._fail(exc)
                return
            self._ws = ws
            self._connected.set()
            try:
                async for raw in ws:
                    if self._closed.is_set():
                        break
                    if isinstance(raw, str):
                        self._handle_message(raw)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not self._closed.is_set():
                    logger.warning("asr_read_failed", provider="deepgram", error=str(exc))
            finally:
                self._ws = None
                self._connected.clear()
                if not self._closed.is_set():
                    try:
                        await ws.close()
                    except Exception:
                        logger.debug("asr_ws_close_failed", provider="deepgram")

    def _fail(self, error: ASRProviderError) -> None:
        if self._fatal_error is None:
            self._fatal_error = error
            logger.error(
                "asr_fatal",
                provider="deepgram",
                code=error.code,
                message=error.message,
            )
            self._results.put_nowait(None)
            sender = self._sender_task
            if sender is not None and not sender.done():
                sender.cancel()

    async def _sender(self) -> None:
        while not self._closed.is_set():
            item = await self._audio_in.get()
            if item is None:
                break
            await self._wait_until_connected()
            if self._closed.is_set() or self._fatal_error is not None:
                return
            ws = self._ws
            try:
                if item.kind == "control":
                    assert isinstance(item.payload, dict)
                    await asyncio.wait_for(
                        ws.send(json.dumps(item.payload)),
                        timeout=self._settings.deepgram_send_timeout_sec,
                    )
                else:
                    assert isinstance(item.payload, bytes)
                    await asyncio.wait_for(
                        ws.send(item.payload),
                        timeout=self._settings.deepgram_send_timeout_sec,
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("asr_send_failed", provider="deepgram", error=str(exc))
                self._ws = None
                self._connected.clear()

    async def _wait_until_connected(self) -> None:
        while not self._closed.is_set() and self._fatal_error is None:
            ws = self._ws
            if ws is not None and ws.state is State.OPEN:
                return
            try:
                await asyncio.wait_for(self._connected.wait(), timeout=0.25)
            except TimeoutError:
                continue

    # --- internal: Deepgram message handling -------------------------------

    def _handle_message(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("asr_malformed_message", provider="deepgram")
            return
        if not isinstance(payload, dict):
            logger.warning("asr_unexpected_message", provider="deepgram", shape=type(payload).__name__)
            return

        msg_type = payload.get("type")
        if msg_type == "Results":
            self._handle_results(payload)
        elif msg_type == "Error":
            self._handle_error(payload)
        elif msg_type in ("Metadata", "SpeechStarted", "UtteranceEnd", "KeepAlive"):
            logger.debug("asr_event", provider="deepgram", type=msg_type)
        else:
            logger.debug("asr_unknown_message", provider="deepgram", type=msg_type)

    def _handle_results(self, payload: dict[str, Any]) -> None:
        channel = payload.get("channel") or {}
        alternatives = channel.get("alternatives") or []
        if not alternatives:
            return
        alternative = alternatives[0]
        text = (alternative.get("transcript") or "").strip()
        is_final = bool(payload.get("is_final"))
        start_ms = int(float(payload.get("start", 0.0)) * 1000)
        duration_s = float(payload.get("duration", 0.0))
        end_ms = start_ms + round(duration_s * 1000)
        confidence = alternative.get("confidence")

        if is_final and not text:
            # Deepgram emits empty finals at utterance boundaries (silence).
            # They carry no transcript and must not be surfaced.
            logger.debug("asr_empty_final_ignored", provider="deepgram")
            return

        segment_id = f"{self._uid}-{self._utterance_index}"

        if is_final:
            dedupe_key = (start_ms, text)
            if dedupe_key in self._seen_final_keys:
                logger.debug("asr_duplicate_final_ignored", provider="deepgram")
                return
            self._seen_final_keys.add(dedupe_key)
            self._utterance_index += 1
            self._last_partial_text = None
        else:
            if text == self._last_partial_text:
                return  # unchanged interim update; avoid spamming the client
            self._last_partial_text = text

        latency_ms = self._estimate_latency_ms(start_ms / 1000.0 + duration_s)
        self._results.put_nowait(
            TranscriptSegment(
                segment_id=segment_id,
                text=text,
                is_final=is_final,
                start_ms=start_ms,
                end_ms=end_ms,
                confidence=confidence,
                asr_latency_ms=latency_ms,
            )
        )

    def _handle_error(self, payload: dict[str, Any]) -> None:
        status = int(payload.get("status_code") or 0)
        message = payload.get("message") or payload.get("err_msg") or "Unknown Deepgram error"
        logger.warning("asr_error_message", provider="deepgram", status_code=status, message=message)
        if status in (401, 403):
            self._fail(ASRProviderError("deepgram_auth", "Deepgram authentication failed"))
        elif status == 400:
            self._fail(ASRProviderError("deepgram_config", "Deepgram rejected the request parameters"))
        elif status == 429:
            self._fail(ASRProviderError("deepgram_rate_limit", "Deepgram rate limit exceeded"))
        elif status >= 500:
            self._fail(ASRProviderError("deepgram_connection", "Deepgram server error"))
        elif status >= 400 or not status:
            self._fail(ASRProviderError("deepgram_error", "Deepgram reported an error"))

    # --- internal: latency estimation --------------------------------------

    def _estimate_latency_ms(self, content_seconds: float) -> float | None:
        """Estimate how long ago (ms) the audio this result covers was received.

        The provider records ``(cumulative_audio_seconds, monotonic)`` every
        time a chunk is pushed; Deepgram's ``start``/``duration`` describe a
        content position, which we interpolate back onto the receive timeline.
        """
        points = self._audio_timeline
        if not points:
            return None
        prev_sec: float | None = None
        prev_mono: float | None = None
        received_mono: float | None = None
        for sec, mono in points:
            if sec >= content_seconds:
                if prev_sec is None or prev_mono is None:
                    received_mono = mono
                else:
                    frac = (content_seconds - prev_sec) / max(1e-9, sec - prev_sec)
                    received_mono = prev_mono + frac * (mono - prev_mono)
                break
            prev_sec, prev_mono = sec, mono
        if received_mono is None:
            received_mono = prev_mono
        if received_mono is None:
            return None
        return max(0.0, (time.monotonic() - received_mono) * 1000)
