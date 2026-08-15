"""Shared pytest fixtures and helpers."""
from __future__ import annotations

import asyncio
import queue
from collections.abc import AsyncIterator

import pytest

from app.models.schemas import TranscriptSegment
from app.services.asr.base import ASRProvider


class FakeASRProvider(ASRProvider):
    """
    In-memory, scriptable ASR provider used to exercise the transport layer
    without touching the network.

    ``script()`` may be called from any thread; ``stream()`` drains items
    through a thread-safe queue so the test (client thread) can push segments
    while the app runs in the TestClient portal thread.
    """

    def __init__(self) -> None:
        self.connect_args: dict | None = None
        self.chunks: list[bytes] = []
        self.silence_hints: list[int] = []
        self.closed = False
        self._segments: queue.Queue[TranscriptSegment | None] = queue.Queue()

    def script(self, segments: list[TranscriptSegment]) -> None:
        for segment in segments:
            self._segments.put(segment)
        self._segments.put(None)

    async def connect(self, *, sample_rate: int, encoding: str, language: str) -> None:
        self.connect_args = {
            "sample_rate": sample_rate,
            "encoding": encoding,
            "language": language,
        }

    async def send_audio(self, chunk: bytes) -> None:
        self.chunks.append(chunk)

    async def notify_silence(self, duration_ms: int) -> None:
        self.silence_hints.append(duration_ms)

    async def stream(self) -> AsyncIterator[TranscriptSegment]:
        while True:
            try:
                segment = self._segments.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.02)
                continue
            if segment is None:
                break
            yield segment

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_asr_factory(monkeypatch: pytest.MonkeyPatch):
    """Install FakeASRProvider as the ASR factory; return the created instances."""
    from app.websocket import translate_stream

    created: list[FakeASRProvider] = []

    def factory() -> FakeASRProvider:
        provider = FakeASRProvider()
        created.append(provider)
        return provider

    monkeypatch.setattr(translate_stream, "create_asr_provider", factory)
    return created
