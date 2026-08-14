"""
DeepgramASRProvider: default streaming ASR implementation.

NOTE: This is a scaffold. The Deepgram streaming session lifecycle
(connect / send_audio / stream / close) is wired to the SDK's async
websocket client, but event-to-`TranscriptSegment` mapping and error
handling are left as the next implementation step -- intentionally, per
the project's phased build-out plan (see DEVELOPMENT_PLAN.md).
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from app.config import get_settings
from app.models.schemas import TranscriptSegment
from app.services.asr.base import ASRProvider


class DeepgramASRProvider(ASRProvider):
    def __init__(self) -> None:
        self._settings = get_settings()
        self._connection = None  # deepgram-sdk live connection, set in connect()
        self._queue: asyncio.Queue[TranscriptSegment] = asyncio.Queue()

    async def connect(self, *, sample_rate: int, encoding: str, language: str) -> None:
        # TODO: instantiate deepgram-sdk AsyncLiveClient with:
        #   model=self._settings.deepgram_model, language=language,
        #   encoding=encoding, sample_rate=sample_rate,
        #   interim_results=True, endpointing=..., punctuate=True,
        #   smart_format=True
        raise NotImplementedError("DeepgramASRProvider.connect is not yet implemented")

    async def send_audio(self, chunk: bytes) -> None:
        raise NotImplementedError

    async def notify_silence(self, duration_ms: int) -> None:
        # Maps to Deepgram's Finalize/UtteranceEnd control message.
        raise NotImplementedError

    async def stream(self) -> AsyncIterator[TranscriptSegment]:
        while True:
            segment = await self._queue.get()
            yield segment

    async def close(self) -> None:
        raise NotImplementedError
