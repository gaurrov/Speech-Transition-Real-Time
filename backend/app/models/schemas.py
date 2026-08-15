"""
Shared Pydantic models for the WebSocket translation protocol.

The client/server contract lives here so the WebSocket transport layer and
any future pipeline orchestrator speak the same vocabulary. Every message is
a JSON envelope of the form ``{"type": "<event>", ...fields}``; audio frames
travel as raw binary WebSocket messages rather than base64-encoded JSON.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

AudioEncoding = Literal["linear16", "opus"]


class WSClientEventType(str, Enum):
    """Messages the frontend sends to the backend."""

    START_SESSION = "start_session"
    SESSION_CONFIGURATION = "session_configuration"
    AUDIO_CHUNK = "audio_chunk"
    VAD_EVENT = "vad_event"
    STOP_SESSION = "stop_session"


class WSServerEventType(str, Enum):
    """Messages the backend sends to the frontend."""

    SESSION_STARTED = "session_started"
    PARTIAL_TRANSCRIPT = "partial_transcript"
    FINAL_TRANSCRIPT = "final_transcript"
    SPEECH_STARTED = "speech_started"
    SILENCE_DETECTED = "silence_detected"
    SPEECH_RESUMED = "speech_resumed"
    TRANSLATION = "translation"
    REFINED_TRANSCRIPT = "refined_transcript"
    LATENCY = "latency"
    AUDIO_RECEIVED = "audio_received"
    ERROR = "error"
    SESSION_STOPPED = "session_stopped"


# --- Client -> Server -------------------------------------------------------


class StartSessionRequest(BaseModel):
    """Ask the server to begin a translation session for this connection."""

    session_id: str | None = Field(
        default=None,
        description="Client-generated UUID. The server generates one when omitted.",
    )


class SessionConfiguration(BaseModel):
    """Full configuration for a session: languages, audio source, session id."""

    session_id: str
    source_language: str = Field(description="BCP-47 code, e.g. 'en', or 'auto'")
    target_language: str = Field(description="BCP-47 code, e.g. 'es'")
    audio_source: str = Field(description="'microphone', 'system', or a mock source id")
    sample_rate: int = 16_000
    encoding: AudioEncoding = "linear16"


class AudioChunkMessage(BaseModel):
    """Optional JSON control message around binary audio frames."""

    session_id: str


class VADEventMessage(BaseModel):
    """
    Client-side voice activity detection lifecycle event.

    Mirrors the client's VAD state machine: speech_started / speaking /
    silence_started / silence_detected / speech_resumed. ``duration_ms`` is
    set on ``silence_detected`` (the measured gap that ended the utterance)
    and is the input for server-side utterance finalization.
    """

    type: Literal["vad_event"] = "vad_event"
    session_id: str
    event: Literal[
        "speech_started",
        "speaking",
        "silence_started",
        "silence_detected",
        "speech_resumed",
    ]
    timestamp_ms: int = Field(description="Epoch ms when the transition occurred")
    duration_ms: int | None = Field(default=None, description="Measured silence gap (ms)")
    probability: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Silero speech probability at the event",
    )


class StopSessionRequest(BaseModel):
    """Gracefully end a session."""

    session_id: str


# --- Server -> Client -------------------------------------------------------


class SessionStartedEvent(BaseModel):
    """Emitted when a session exists with a known configuration."""

    type: Literal["session_started"] = "session_started"
    session_id: str
    configuration: SessionConfiguration


class SpeechEvent(BaseModel):
    """speech_started / silence_detected / speech_resumed lifecycle events."""

    type: Literal["speech_started", "silence_detected", "speech_resumed"]
    session_id: str
    timestamp_ms: int
    duration_ms: int | None = None  # silence_detected only: how long the gap was


class TranscriptEvent(BaseModel):
    """partial_transcript / final_transcript streamed ASR results."""

    type: Literal["partial_transcript", "final_transcript"]
    session_id: str
    segment_id: str
    text: str
    is_final: bool
    start_ms: int | None = None
    end_ms: int | None = None
    confidence: float | None = None


class TranslationEvent(BaseModel):
    """A translation of a finalized transcript segment."""

    type: Literal["translation"] = "translation"
    session_id: str
    segment_id: str
    source_text: str
    translated_text: str
    source_language: str
    target_language: str
    is_final: bool = True
    provider: str


class RefinedTranscriptEvent(BaseModel):
    """Async, non-blocking correction of an already-finalized segment."""

    type: Literal["refined_transcript"] = "refined_transcript"
    session_id: str
    segment_id: str
    refined_text: str
    changed: bool


class LatencyEvent(BaseModel):
    """Per-segment timing report (ms)."""

    type: Literal["latency"] = "latency"
    session_id: str
    segment_id: str
    asr_ms: float | None = None
    translation_ms: float | None = None
    # Refinement latency is measured separately from the live path: it is the
    # time spent on the async LLM correction pass, which never gates the
    # transcript/translation that reached the client first.
    refinement_ms: float | None = None
    end_to_end_ms: float | None = None


class AudioReceivedEvent(BaseModel):
    """Progress ack for the live audio stream: totals received so far."""

    type: Literal["audio_received"] = "audio_received"
    session_id: str
    chunks: int
    bytes: int
    audio_seconds: float


class ErrorMessage(BaseModel):
    """Error envelope sent to the client."""

    type: Literal["error"] = "error"
    session_id: str | None = None
    code: str
    message: str


class SessionStoppedEvent(BaseModel):
    """Confirmation that a session has been torn down."""

    type: Literal["session_stopped"] = "session_stopped"
    session_id: str
    reason: str


# --- Internal pipeline data models (used by provider interfaces) -----------


class TranscriptSegment(BaseModel):
    segment_id: str
    text: str
    is_final: bool
    start_ms: int | None = None
    end_ms: int | None = None
    confidence: float | None = None
    # Internal metric: ms from backend audio receipt to this ASR result.
    # Serialized to the client only via the separate `latency` event.
    asr_latency_ms: float | None = None


class TranslationSegment(BaseModel):
    segment_id: str
    source_text: str
    translated_text: str
    source_language: str
    target_language: str
    is_final: bool
    provider: str


class RefinementResult(BaseModel):
    segment_id: str
    refined_text: str
    changed: bool


ServerEvent = (
    SessionStartedEvent
    | SpeechEvent
    | TranscriptEvent
    | TranslationEvent
    | RefinedTranscriptEvent
    | LatencyEvent
    | AudioReceivedEvent
    | ErrorMessage
    | SessionStoppedEvent
)
