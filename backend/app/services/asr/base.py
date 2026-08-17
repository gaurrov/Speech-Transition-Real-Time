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


class ASRProviderError(Exception):
    """
    Recoverable-vs-not distinction for callers.

    ``code`` is a stable machine-readable string that the transport layer
    can surface as a typed ``error`` event without knowing provider internals.

    Known codes:

    * ``deepgram_config`` — permanent: invalid parameters / 400
    * ``deepgram_auth`` — permanent: missing or rejected API key / 401/403
    * ``deepgram_rate_limit`` — permanent: quota or rate limit exceeded / 429
    * ``deepgram_timeout`` — transient: connection timed out
    * ``deepgram_connection`` — transient: network or server error
    * ``deepgram_protocol`` — permanent: unexpected protocol behaviour
    * ``deepgram_audio`` — permanent: audio format issue
    * ``deepgram_closed`` — provider was closed externally
    * ``deepgram_error`` — generic provider error
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


ASRProviderFactory = Callable[[], Awaitable[ASRProvider]]
