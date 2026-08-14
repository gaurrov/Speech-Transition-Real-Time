"""
VADProvider: abstract interface for voice-activity/silence detection.

Silero VAD runs client-side (in an AudioWorklet) for latency reasons,
so the backend does not run VAD on the hot path today. This interface
exists so the server can:
  1) validate/consume silence *events* the client reports (see
     `SilenceDetector` below), and
  2) later support an optional server-side VAD provider (e.g. for
     recorded/meeting-audio ingestion where there is no client worklet),
     without changing the pipeline's call sites.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class VADProvider(ABC):
    @abstractmethod
    async def process_frame(self, frame: bytes) -> bool:
        """Return True if the frame is classified as speech."""


class SilenceDetector:
    """
    Turns raw client VAD events into sentence-boundary decisions.

    The client sends `speech_start` / `speech_end` timestamps (derived
    from Silero VAD probabilities). This helper decides, using
    `silence_finalize_ms` / `silence_min_speech_ms` from settings,
    whether a given silence gap should:
      - be ignored (too short / likely a breath pause), or
      - trigger `ASRProvider.notify_silence()` to force a clean
        utterance boundary and improve punctuation on the final
        transcript.
    """

    def __init__(self, *, finalize_ms: int, min_speech_ms: int) -> None:
        self._finalize_ms = finalize_ms
        self._min_speech_ms = min_speech_ms
        self._speech_started_at: int | None = None

    def should_finalize(self, *, silence_duration_ms: int, speech_duration_ms: int) -> bool:
        if speech_duration_ms < self._min_speech_ms:
            return False
        return silence_duration_ms >= self._finalize_ms
