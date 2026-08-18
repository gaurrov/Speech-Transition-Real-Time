"""DeepgramASRProvider unit tests against a fake Deepgram WebSocket server.

These tests never touch the real Deepgram API: a local websockets server
mimics the streaming protocol (query params, auth header, Results/Error
messages, connection drops) so behavior is fully deterministic.
"""
from __future__ import annotations

import asyncio
import json

import pytest
import websockets
from websockets.http11 import Response as WSResponse

from app.config import Settings
from app.models.schemas import TranscriptSegment
from app.services.asr.base import ASRProviderError
from app.services.asr.deepgram_provider import DeepgramASRProvider


def _results(*, text: str, is_final: bool, start: float = 0.0, duration: float = 1.0) -> dict:
    return {
        "type": "Results",
        "channel_index": [0, 0],
        "is_final": is_final,
        "channel": {
            "alternatives": [{"transcript": text, "confidence": 0.95, "words": []}],
            "errors": [],
        },
        "start": start,
        "duration": duration,
    }


def _settings(endpoint: str, **overrides) -> Settings:
    base = {
        "deepgram_api_key": "test-key",
        "deepgram_endpoint": endpoint,
        "deepgram_reconnect_base_delay_ms": 10,
        "deepgram_reconnect_max_attempts": 3,
    }
    base.update(overrides)
    return Settings(**base)


class FakeDeepgramServer:
    """Minimal stand-in for Deepgram's /v1/listen WebSocket endpoint."""

    def __init__(
        self,
        *,
        script: list[dict] | None = None,
        on_connect: list[dict] | None = None,
        drop_after_first_audio: bool = False,
        reject_status: int | None = None,
        reject_body: bytes = b"",
    ) -> None:
        self.script = script or []
        self.on_connect = on_connect or []
        self.drop_after_first_audio = drop_after_first_audio
        self.reject_status = reject_status
        self.reject_body = reject_body
        self.connections: list[websockets.ServerConnection] = []
        self.paths: list[str] = []
        self.auth_headers: list[str | None] = []
        self.rejection_count = 0
        self.total_audio_bytes = 0
        self.controls: list[dict] = []
        self._script_sent = False
        self._dropped = False
        self._server = None

    async def start(self) -> str:
        self._server = await websockets.serve(
            self._handler, "127.0.0.1", 0, process_request=self._process_request
        )
        return f"ws://127.0.0.1:{self._server.sockets[0].getsockname()[1]}"

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _process_request(
        self, path: str, headers: websockets.Headers
    ) -> WSResponse | None:
        if self.reject_status is not None:
            self.rejection_count += 1
            return WSResponse(self.reject_status, "Rejected", websockets.Headers(), self.reject_body)
        return None

    async def _handler(self, ws: websockets.ServerConnection) -> None:
        self.connections.append(ws)
        self.paths.append(ws.request.path)
        self.auth_headers.append(ws.request.headers.get("Authorization"))
        for payload in self.on_connect:
            await ws.send(json.dumps(payload))
        self.on_connect = []

        try:
            async for raw in ws:
                if not isinstance(raw, bytes):
                    try:
                        self.controls.append(json.loads(raw))
                    except json.JSONDecodeError:
                        self.controls.append({"raw": raw})
                    continue
                if self.drop_after_first_audio and not self._dropped:
                    self._dropped = True
                    await ws.close(code=1001, reason="simulated upstream drop")
                    return
                self.total_audio_bytes += len(raw)
                if not self._script_sent and self.script:
                    for payload in self.script:
                        await ws.send(json.dumps(payload))
                    self._script_sent = True
        except websockets.ConnectionClosed:
            pass


async def _collect(provider: DeepgramASRProvider, out: list[TranscriptSegment]) -> None:
    async for segment in provider.stream():
        out.append(segment)
        if segment.is_final:
            return


@pytest.mark.asyncio
async def test_partial_then_final_maps_to_segments() -> None:
    server = FakeDeepgramServer(
        script=[
            _results(text="We need to discuss", is_final=False, start=0.0, duration=0.7),
            _results(
                text="We need to discuss the project.",
                is_final=True,
                start=0.0,
                duration=2.1,
            ),
        ]
    )
    url = await server.start()
    provider = DeepgramASRProvider(_settings(url))
    await provider.connect(sample_rate=16_000, encoding="linear16", language="en")

    segments: list[TranscriptSegment] = []
    task = asyncio.create_task(_collect(provider, segments))
    await provider.send_audio(b"\x00" * 1600)
    await asyncio.wait_for(task, timeout=5)

    assert len(segments) == 2
    partial, final = segments
    assert partial.is_final is False
    assert partial.text == "We need to discuss"
    assert partial.start_ms == 0
    assert final.is_final is True
    assert final.text == "We need to discuss the project."
    assert final.end_ms == 2100
    assert final.confidence == 0.95
    # Stable segment id across the partial and its final.
    assert final.segment_id == partial.segment_id
    # audio->ASR latency is measured, not null, when audio has been seen.
    assert final.asr_latency_ms is not None and final.asr_latency_ms >= 0
    await provider.close()
    await server.close()


@pytest.mark.asyncio
async def test_duplicate_final_is_deduped() -> None:
    final = _results(text="Only once.", is_final=True, start=0.5, duration=1.0)
    server = FakeDeepgramServer(script=[final, final, _results(text="Second.", is_final=True, start=3.0, duration=0.8)])
    url = await server.start()
    provider = DeepgramASRProvider(_settings(url))
    await provider.connect(sample_rate=16_000, encoding="linear16", language="en")

    collected: list[TranscriptSegment] = []
    await provider.send_audio(b"\x00" * 1600)
    async for segment in provider.stream():
        collected.append(segment)
        if len(collected) == 2:
            break
    assert [s.text for s in collected] == ["Only once.", "Second."]
    await provider.close()
    await server.close()


@pytest.mark.asyncio
async def test_empty_final_is_ignored() -> None:
    server = FakeDeepgramServer(
        script=[
            _results(text="", is_final=True, start=0.0, duration=0.0),
            _results(text="Real speech", is_final=True, start=0.0, duration=0.9),
        ]
    )
    url = await server.start()
    provider = DeepgramASRProvider(_settings(url))
    await provider.connect(sample_rate=16_000, encoding="linear16", language="en")

    segments: list[TranscriptSegment] = []
    await provider.send_audio(b"\x00" * 1600)
    async for segment in provider.stream():
        segments.append(segment)
        if segment.is_final:
            break
    assert [s.text for s in segments] == ["Real speech"]
    await provider.close()
    await server.close()


@pytest.mark.asyncio
async def test_malformed_json_is_ignored() -> None:
    server = FakeDeepgramServer(
        script=[
            {"type": "NotJson"},
            _results(text="Still works", is_final=True, start=0.0, duration=0.9),
        ]
    )
    url = await server.start()
    provider = DeepgramASRProvider(_settings(url))
    await provider.connect(sample_rate=16_000, encoding="linear16", language="en")

    segments: list[TranscriptSegment] = []
    await provider.send_audio(b"\x00" * 1600)
    async for segment in provider.stream():
        segments.append(segment)
        if segment.is_final:
            break
    assert [s.text for s in segments] == ["Still works"]
    await provider.close()
    await server.close()


@pytest.mark.asyncio
async def test_notify_silence_sends_finalize_control() -> None:
    server = FakeDeepgramServer()
    url = await server.start()
    provider = DeepgramASRProvider(_settings(url))
    await provider.connect(sample_rate=16_000, encoding="linear16", language="en")
    await provider.send_audio(b"\x00" * 1600)
    await provider.notify_silence(duration_ms=900)

    for _ in range(50):
        if server.controls:
            break
        await asyncio.sleep(0.01)
    assert server.controls == [{"type": "Finalize"}]
    await provider.close()
    await server.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("en", ["language=en", "sample_rate=16000", "encoding=linear16", "interim_results=true"]),
        ("hi", ["language=hi", "sample_rate=16000", "encoding=linear16"]),
        ("es", ["language=es", "sample_rate=16000", "encoding=linear16"]),
    ],
)
async def test_language_query_params(language: str, expected: list[str]) -> None:
    server = FakeDeepgramServer()
    url = await server.start()
    provider = DeepgramASRProvider(_settings(url))
    await provider.connect(sample_rate=16_000, encoding="linear16", language=language)
    await provider.send_audio(b"\x00" * 1600)
    await asyncio.sleep(0.1)
    await provider.close()

    assert len(server.paths) >= 1
    path = server.paths[-1]
    for token in expected:
        assert token in path
    assert server.auth_headers[-1] == "Token test-key"
    await server.close()


@pytest.mark.asyncio
async def test_auto_language_enables_detection() -> None:
    server = FakeDeepgramServer()
    url = await server.start()
    provider = DeepgramASRProvider(_settings(url))
    await provider.connect(sample_rate=16_000, encoding="linear16", language="auto")
    await provider.send_audio(b"\x00" * 1600)
    await asyncio.sleep(0.1)
    await provider.close()

    path = server.paths[-1]
    assert "multilingual=true" in path
    assert "language_detection" not in path
    assert "language=" not in path
    await server.close()


@pytest.mark.asyncio
async def test_connect_missing_api_key_is_config_error() -> None:
    provider = DeepgramASRProvider(
        Settings(deepgram_api_key=None, deepgram_endpoint="ws://127.0.0.1:1/v1/listen")
    )
    with pytest.raises(ASRProviderError) as exc_info:
        await provider.connect(sample_rate=16_000, encoding="linear16", language="en")
    assert exc_info.value.code == "deepgram_config"


@pytest.mark.asyncio
async def test_server_error_message_becomes_provider_error() -> None:
    server = FakeDeepgramServer(
        on_connect=[{"type": "Error", "message": "bad language config", "status_code": 400}]
    )
    url = await server.start()
    provider = DeepgramASRProvider(_settings(url))
    await provider.connect(sample_rate=16_000, encoding="linear16", language="en")
    with pytest.raises(ASRProviderError) as exc_info:
        await _collect(provider, [])
    assert exc_info.value.code == "deepgram_config"
    assert "Speech recognition" in exc_info.value.message
    await provider.close()
    await server.close()


@pytest.mark.asyncio
async def test_server_auth_error_is_fatal() -> None:
    server = FakeDeepgramServer(
        on_connect=[{"type": "Error", "message": "unauthorized", "status_code": 401}]
    )
    url = await server.start()
    provider = DeepgramASRProvider(_settings(url))
    await provider.connect(sample_rate=16_000, encoding="linear16", language="en")
    with pytest.raises(ASRProviderError) as exc_info:
        await _collect(provider, [])
    assert exc_info.value.code == "deepgram_auth"
    await provider.close()
    await server.close()


@pytest.mark.asyncio
async def test_reconnects_after_upstream_drop_and_resumes() -> None:
    server = FakeDeepgramServer(
        drop_after_first_audio=True,
        script=[_results(text="Reconnected", is_final=True, start=0.0, duration=0.8)],
    )
    url = await server.start()
    provider = DeepgramASRProvider(_settings(url))
    await provider.connect(sample_rate=16_000, encoding="linear16", language="en")

    segments: list[TranscriptSegment] = []
    task = asyncio.create_task(_collect(provider, segments))
    await provider.send_audio(b"\x00" * 1600)
    await asyncio.sleep(0.2)  # let the reader detect the drop and reconnect
    await provider.send_audio(b"\x00" * 1600)
    await asyncio.wait_for(task, timeout=5)

    assert len(server.connections) >= 2, "expected a reconnection"
    assert segments[-1].is_final is True
    assert segments[-1].text == "Reconnected"
    await provider.close()
    await server.close()


@pytest.mark.asyncio
async def test_connection_refused_is_provider_error() -> None:
    # Nothing is listening on this port: retries exhaust and stream() raises.
    provider = DeepgramASRProvider(
        _settings("ws://127.0.0.1:1/v1/listen", deepgram_reconnect_max_attempts=1)
    )
    await provider.connect(sample_rate=16_000, encoding="linear16", language="en")
    with pytest.raises(ASRProviderError) as exc_info:
        await _collect(provider, [])
    assert exc_info.value.code == "deepgram_connection"
    await provider.close()


@pytest.mark.asyncio
async def test_http_400_handshake_rejection_is_config_error() -> None:
    """HTTP 400 during WebSocket handshake → deepgram_config, no retry."""
    server = FakeDeepgramServer(
        reject_status=400,
        reject_body=b'{"err_msg":"Invalid parameter: encoding"}',
    )
    url = await server.start()
    provider = DeepgramASRProvider(_settings(url))
    await provider.connect(sample_rate=16_000, encoding="linear16", language="en")
    with pytest.raises(ASRProviderError) as exc_info:
        await _collect(provider, [])
    assert exc_info.value.code == "deepgram_config"
    assert "Speech recognition" in exc_info.value.message
    assert server.rejection_count == 1
    assert len(server.connections) == 0
    await provider.close()
    await server.close()


@pytest.mark.asyncio
async def test_http_429_handshake_rejection_is_rate_limit() -> None:
    """HTTP 429 during WebSocket handshake → deepgram_rate_limit, no retry."""
    server = FakeDeepgramServer(
        reject_status=429,
        reject_body=b'{"err_msg":"Rate limit exceeded"}',
    )
    url = await server.start()
    provider = DeepgramASRProvider(_settings(url))
    await provider.connect(sample_rate=16_000, encoding="linear16", language="en")
    with pytest.raises(ASRProviderError) as exc_info:
        await _collect(provider, [])
    assert exc_info.value.code == "deepgram_rate_limit"
    assert "rate limit" in exc_info.value.message.lower()
    assert server.rejection_count == 1
    assert len(server.connections) == 0
    await provider.close()
    await server.close()


@pytest.mark.asyncio
async def test_http_500_handshake_rejection_retries_then_fails() -> None:
    """HTTP 500 during WebSocket handshake → transient, retries then fails."""
    server = FakeDeepgramServer(
        reject_status=500,
        reject_body=b'{"err_msg":"Internal error"}',
    )
    url = await server.start()
    provider = DeepgramASRProvider(
        _settings(url, deepgram_reconnect_max_attempts=3, deepgram_reconnect_base_delay_ms=5)
    )
    await provider.connect(sample_rate=16_000, encoding="linear16", language="en")
    with pytest.raises(ASRProviderError) as exc_info:
        await _collect(provider, [])
    assert exc_info.value.code == "deepgram_connection"
    assert "speech recognition" in exc_info.value.message.lower()
    assert server.rejection_count == 3
    assert len(server.connections) == 0
    await provider.close()
    await server.close()


@pytest.mark.asyncio
async def test_in_band_400_is_config_error() -> None:
    """In-band Error message with status 400 → deepgram_config."""
    server = FakeDeepgramServer(
        on_connect=[{"type": "Error", "message": "bad parameter", "status_code": 400}]
    )
    url = await server.start()
    provider = DeepgramASRProvider(_settings(url))
    await provider.connect(sample_rate=16_000, encoding="linear16", language="en")
    with pytest.raises(ASRProviderError) as exc_info:
        await _collect(provider, [])
    assert exc_info.value.code == "deepgram_config"
    await provider.close()
    await server.close()


@pytest.mark.asyncio
async def test_in_band_429_is_rate_limit() -> None:
    """In-band Error message with status 429 → deepgram_rate_limit."""
    server = FakeDeepgramServer(
        on_connect=[{"type": "Error", "message": "quota exceeded", "status_code": 429}]
    )
    url = await server.start()
    provider = DeepgramASRProvider(_settings(url))
    await provider.connect(sample_rate=16_000, encoding="linear16", language="en")
    with pytest.raises(ASRProviderError) as exc_info:
        await _collect(provider, [])
    assert exc_info.value.code == "deepgram_rate_limit"
    await provider.close()
    await server.close()


@pytest.mark.asyncio
async def test_in_band_500_is_connection_error() -> None:
    """In-band Error message with status 500 → deepgram_connection."""
    server = FakeDeepgramServer(
        on_connect=[{"type": "Error", "message": "server exploded", "status_code": 500}]
    )
    url = await server.start()
    provider = DeepgramASRProvider(_settings(url))
    await provider.connect(sample_rate=16_000, encoding="linear16", language="en")
    with pytest.raises(ASRProviderError) as exc_info:
        await _collect(provider, [])
    assert exc_info.value.code == "deepgram_connection"
    await provider.close()
    await server.close()
