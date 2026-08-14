"""
ASRProvider: abstract interface for streaming speech-to-text.

Any speech recognition backend (Deepgram, Whisper streaming, Google STT,
etc.) implements this interface. The websocket layer and pipeline
orchestrator depend only on this abstraction -- never on a concrete
provider -- so providers can be swapped or run side-by-side (e.g. for
A/B testing or regional failover) without touching business logic.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable

from app.models.schemas import TranscriptSegment


class ASRProvider(ABC):
    """Streaming ASR contract.

    Implementations receive raw audio frames pushed via `send_audio` and
    emit `TranscriptSegment` events (partial and final) through the
    async generator returned by `stream()`.
    """

    @abstractmethod
    async def connect(self, *, sample_rate: int, encoding: str, language: str) -> None:
        """Open the upstream connection/session for a single utterance stream."""

    @abstractmethod
    async def send_audio(self, chunk: bytes) -> None:
        """Push a raw PCM/Opus audio frame to the provider."""

    @abstractmethod
    async def notify_silence(self, duration_ms: int) -> None:
        """
        Inform the provider of a client-detected silence boundary.

        Providers that support endpointing hints (e.g. Deepgram's
        `finalize`/`utterance_end`) can use this to force an early final
        result and cleaner sentence boundaries.
        """

    @abstractmethod
    def stream(self) -> AsyncIterator[TranscriptSegment]:
        """Yield transcript segments (partial and final) as they arrive."""

    @abstractmethod
    async def close(self) -> None:
        """Close the upstream connection and release resources."""


ASRProviderFactory = Callable[[], Awaitable[ASRProvider]]
