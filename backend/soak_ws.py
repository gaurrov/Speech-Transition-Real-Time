"""Disposable soak test: 10 minutes of continuous speech through the real
FastAPI app + a real WebSocket client, driven by scripted ASR/translation/LLM
providers.

Verifies over a long-running session:
  * WebSocket stays connected the whole time (no reconnect / no close).
  * Final transcript ordering: segment ids strictly increasing, no gaps.
  * Translation synchronization: one translation per final, in order, after
    its final, text matches.
  * Refinement events keep flowing (async path stays healthy).
  * Server process memory is stable (no unbounded growth).
  * The pipeline stays responsive (reader never stalls).

Audio is streamed at 2.5x real time (100 ms of PCM every 40 ms), which pushes
6000 chunks / 60 utterances in ~4 wall-clock minutes and stresses the pipeline
harder than real time.
"""
from __future__ import annotations

import asyncio
import ctypes
import json
import os
import sys
import threading
import time
from collections.abc import AsyncIterator

import websockets

from app.models.schemas import RefinementResult, TranscriptSegment, TranslationSegment
from app.services.asr.base import ASRProvider
from app.services.llm.base import LLMProvider
from app.services.translation.base import TranslationProvider
from app.websocket import translate_stream

PORT = int(os.environ.get("SOAK_PORT", "8011"))
URL = f"ws://127.0.0.1:{PORT}/ws/translate"

CHUNK_BYTES = 1600  # 100 ms of 16 kHz linear16
TOTAL_CHUNKS = int(os.environ.get("SOAK_TOTAL_CHUNKS", "6000"))  # 10 minutes of audio
CHUNKS_PER_UTTERANCE = 100
PARTIAL_AT = 60
SLEEP_PER_CHUNK = float(os.environ.get("SOAK_SLEEP", "0.04"))  # 2.5x real time


class SoakASR(ASRProvider):
    """Chunk-count-driven ASR: emits a partial then a final every N chunks."""

    def __init__(self) -> None:
        self.emit: asyncio.Queue[TranscriptSegment | None] = asyncio.Queue()
        self.bytes_seen = 0
        self.chunks_seen = 0
        self.utterance = 0

    async def connect(self, *, sample_rate: int, encoding: str, language: str) -> None:
        pass

    async def send_audio(self, chunk: bytes) -> None:
        self.chunks_seen += 1
        self.bytes_seen += len(chunk)
        n = self.utterance
        pos = self.chunks_seen % CHUNKS_PER_UTTERANCE
        if pos == PARTIAL_AT:
            self.emit.put_nowait(
                TranscriptSegment(
                    segment_id=f"u{n:04d}",
                    text=f"hello everyone this is utterance number {n}",
                    is_final=False,
                    start_ms=n * 100,
                    end_ms=n * 100 + 60,
                    confidence=0.98,
                    asr_latency_ms=500.0,
                )
            )
        elif pos == 0 and self.chunks_seen > 0:
            self.emit.put_nowait(
                TranscriptSegment(
                    segment_id=f"u{n:04d}",
                    text=f"hello everyone this is utterance number {n}",
                    is_final=True,
                    start_ms=n * 100,
                    end_ms=n * 100 + 100,
                    confidence=0.97,
                    asr_latency_ms=900.0,
                )
            )
            self.utterance += 1

    async def notify_silence(self, duration_ms: int) -> None:
        pass

    async def stream(self) -> AsyncIterator[TranscriptSegment]:
        while True:
            seg = await self.emit.get()
            if seg is None:
                break
            yield seg
            if seg.is_final:
                await asyncio.sleep(0.05)  # pipeline breathing room

    async def close(self) -> None:
        pass


class SoakTranslator(TranslationProvider):
    name = "soak"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def translate(
        self,
        *,
        segment_id: str,
        text: str,
        source_language: str,
        target_language: str,
        is_final: bool,
    ) -> TranslationSegment:
        self.calls.append((segment_id, text))
        await asyncio.sleep(0.03)
        return TranslationSegment(
            segment_id=segment_id,
            source_text=text,
            translated_text=f"[{text}]",
            source_language=source_language,
            target_language=target_language,
            is_final=is_final,
            provider=self.name,
        )

    async def close(self) -> None:
        pass


class SoakLLM(LLMProvider):
    def __init__(self) -> None:
        self.calls = 0

    async def refine(
        self,
        *,
        segment_id: str,
        text: str,
        language: str,
        context: list[str] | None = None,
    ) -> RefinementResult:
        self.calls += 1
        await asyncio.sleep(0.02)
        refined = text.capitalize() + "."
        return RefinementResult(
            segment_id=segment_id,
            refined_text=refined,
            changed=refined != text,
        )

    async def close(self) -> None:
        pass


def _install_fakes() -> None:
    asr = SoakASR()
    translator = SoakTranslator()
    llm = SoakLLM()
    translate_stream.create_asr_provider = lambda: asr
    translate_stream.create_translation_provider = lambda: translator
    translate_stream.create_llm_provider = lambda: llm


class ProcessMemoryInfo(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _rss_mb() -> float:
    if sys.platform != "win32":
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    try:
        from ctypes import wintypes

        counters = ProcessMemoryInfo()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL("psapi.dll")
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryInfo),
            ctypes.c_size_t,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        ok = psapi.GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(), ctypes.byref(counters), ctypes.sizeof(counters)
        )
        return counters.WorkingSetSize / (1024 * 1024) if ok else 0.0
    except Exception:
        return 0.0


async def run() -> int:
    import uvicorn

    from app.main import app

    _install_fakes()

    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        try:
            async with websockets.connect(URL):
                break
        except OSError:
            await asyncio.sleep(0.1)
    else:
        print("FAIL: backend did not start")
        return 1

    print(f"soak: backend up, streaming {TOTAL_CHUNKS} chunks at 2.5x", flush=True)

    expected_utterances = TOTAL_CHUNKS // CHUNKS_PER_UTTERANCE
    next_final = 0
    finals_seen = set()
    translations_seen = 0
    e2e_seen = 0
    refined_seen = 0
    events_total = 0
    last_event_at = time.monotonic()
    memory_samples: list[tuple[float, float]] = []
    failed = []

    async with websockets.connect(URL) as ws:
        await ws.send(json.dumps({"type": "start_session", "session_id": "soak-1"}))
        await ws.send(
            json.dumps(
                {
                    "type": "session_configuration",
                    "session_id": "soak-1",
                    "source_language": "en",
                    "target_language": "es",
                    "audio_source": "microphone",
                    "sample_rate": 16000,
                    "encoding": "linear16",
                }
            )
        )

        last_seen = [0]

        async def reader():
            nonlocal next_final, translations_seen, e2e_seen, refined_seen, events_total
            nonlocal last_event_at, last_seen
            async for raw in ws:
                events_total += 1
                last_event_at = time.monotonic()
                msg = json.loads(raw)
                t = msg["type"]
                if t == "final_transcript":
                    idx = int(msg["segment_id"][1:])
                    if idx != next_final:
                        failed.append(f"ordering: got final {idx}, expected {next_final}")
                    finals_seen.add(idx)
                    next_final = idx + 1
                    last_seen[0] = idx
                elif t == "translation":
                    if msg["segment_id"] != f"u{translations_seen:04d}":
                        failed.append(
                            f"sync: translation {msg['segment_id']} expected u{translations_seen:04d}"
                        )
                    expected_text = f"[hello everyone this is utterance number {translations_seen}]"
                    if msg["translated_text"] != expected_text:
                        failed.append(f"sync: translation text mismatch for u{translations_seen:04d}")
                    translations_seen += 1
                elif t == "refined_transcript":
                    refined_seen += 1
                elif t == "latency":
                    if msg.get("end_to_end_ms") is not None:
                        e2e_seen += 1
                elif t == "error":
                    failed.append(f"server error: {msg}")

        async def monitor():
            while True:
                await asyncio.sleep(5)
                memory_samples.append((time.monotonic(), _rss_mb()))
                if time.monotonic() - last_event_at > 10:
                    failed.append(f"stall: no event for >10s (reader at u{last_seen[0]})")

        reader_task = asyncio.create_task(reader())
        monitor_task = asyncio.create_task(monitor())
        payload = bytes(CHUNK_BYTES)
        for _ in range(TOTAL_CHUNKS):
            await ws.send(payload)
            await asyncio.sleep(SLEEP_PER_CHUNK)
            if len(failed) > 20:
                break

        # Wait for the tail of the queue to drain (translations + refinement).
        deadline = time.monotonic() + 30
        while (
            translations_seen < expected_utterances and time.monotonic() < deadline
        ):
            await asyncio.sleep(0.5)
        await asyncio.sleep(5)  # let refinement finish
        await ws.close()
        await reader_task
        monitor_task.cancel()

    server.should_exit = True
    thread.join(timeout=10)

    print(f"soak: finals={len(finals_seen)}/{expected_utterances} "
          f"translations={translations_seen} e2e_latency={e2e_seen} refined={refined_seen} "
          f"events={events_total}", flush=True)
    if len(finals_seen) != expected_utterances:
        failed.append(f"expected {expected_utterances} finals, got {len(finals_seen)}")
    if translations_seen != expected_utterances:
        failed.append(f"expected {expected_utterances} translations, got {translations_seen}")
    if refined_seen == 0:
        failed.append("no refinement events over 10-minute session")
    if e2e_seen == 0:
        failed.append("no end_to_end_ms latency events")
    if len(memory_samples) >= 4:
        first = sum(m for _, m in memory_samples[:2]) / 2
        last5 = memory_samples[-5:]
        last = sum(m for _, m in last5) / len(last5)
        peak = max(m for _, m in memory_samples)
        print(f"soak: rss first={first:.1f}MB last={last:.1f}MB peak={peak:.1f}MB "
              f"({len(memory_samples)} samples)", flush=True)
        if last - first > 60:
            failed.append(f"memory grew {last - first:.1f}MB over the run (>=60MB)")
    else:
        print(f"soak: too few memory samples ({len(memory_samples)})", flush=True)
        failed.append("too few memory samples to judge stability")

    if failed:
        print("FAIL:")
        for line in failed[:25]:
            print("  -", line)
        return 1
    print("PASS: ordering, translation sync, refinement, latency, memory all healthy", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
