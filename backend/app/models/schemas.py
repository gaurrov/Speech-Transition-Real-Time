"""
Shared Pydantic models for WebSocket messages and internal pipeline data.

Keeping these in one place makes the client/server message contract
explicit and lets both the websocket layer and the service layer speak
the same vocabulary.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class WSClientEventType(str, Enum):
    """Messages the frontend sends to the backend."""

    START = "start"           # begin a session: languages, sample rate, etc.
    AUDIO_CHUNK = "audio_chunk"  # base64 or binary frame handled out-of-band
    SILENCE = "silence"        # client-side VAD detected silence boundary
    STOP = "stop"


class WSServerEventType(str, Enum):
    """Messages the backend sends to the frontend."""

    TRANSCRIPT_PARTIAL = "transcript_partial"
    TRANSCRIPT_FINAL = "transcript_final"
    TRANSLATION_PARTIAL = "translation_partial"
    TRANSLATION_FINAL = "translation_final"
    REFINEMENT = "refinement"   # async LLM-corrected version of a final segment
    STATUS = "status"
    ERROR = "error"
    LATENCY = "latency"


class SessionStartRequest(BaseModel):
    source_language: str = Field(description="BCP-47 code, e.g. 'en-US', or 'auto'")
    target_language: str = Field(description="BCP-47 code, e.g. 'es'")
    sample_rate: int = 16_000
    encoding: Literal["linear16", "opus"] = "linear16"


class TranscriptSegment(BaseModel):
    segment_id: str
    text: str
    is_final: bool
    start_ms: int | None = None
    end_ms: int | None = None
    confidence: float | None = None


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


class ErrorMessage(BaseModel):
    code: str
    message: str


class LatencyReport(BaseModel):
    segment_id: str
    asr_ms: float | None = None
    translation_ms: float | None = None
    end_to_end_ms: float | None = None
