# Performance & Latency

End-to-end latency instrumentation, measured numbers, bottlenecks, and the
optimizations made to keep the app feeling like a real-time meeting assistant.

The **critical path is `Audio → VAD → Deepgram → Translation → Electron UI`**.
LLM transcript refinement is strictly async and never gates a transcript or
translation that has already reached the client.

## Timestamp legend (T0–T9)

| Stamp | Meaning | Where measured |
| --- | --- | --- |
| T0 | Microphone frame captured | AudioWorklet → main thread |
| T1 | Audio chunk sent over the WebSocket | renderer (`useTranslatorSession`) |
| T2 | Backend receives the audio content a result covers | `translate_stream._run_asr` |
| T3 | ASR **partial** result | Deepgram streaming provider |
| T4 | ASR **final** result | Deepgram streaming provider |
| T5 | Translation request dispatched | `translate_stream._run_translation` |
| T6 | Translation response received | translation provider |
| T7 | UI receives the translation event | renderer |
| T8 | LLM refinement call starts | `translate_stream._run_refinement` |
| T9 | LLM refinement completes | LLM provider |

T0 and T1 are on the same device as the UI (Electron + renderer + local backend),
so T1→T2 is a localhost hop. T0 is an estimate (AudioWorklet→main-thread
delivery is a few ms); it is used only to compose `speech_to_translation_ms` and
is documented as an approximation, not measured per frame.

## Metric definitions

Delivered in each per-segment `latency` event (see `LatencyEvent` in
`backend/app/models/schemas.py`):

| Metric | Formula | Notes |
| --- | --- | --- |
| `asr_partial_ms` | T3 − T2 | time to the first useful partial |
| `asr_final_ms` | T4 − T2 | time to a finalized utterance |
| `translation_ms` | T6 − T5 | pure translation call |
| `end_to_end_ms` | T6 − T2 | **server live-path end-to-end** (refinement excluded) |
| `refinement_ms` | T9 − T8 | async LLM pass, off the hot path |
| `ui_ms` | T7 − T6 | client-visible server-send→UI gap (dev-only) |
| `final_to_translation_ms` | T7 − T4′ | client receipt final → matching translation |
| `network_ms` | (send → audio ack)/2 | half round-trip (dev-only) |
| `speech_to_translation_ms` | T7 − T0 | composed from `end_to_end_ms` + UI gap |

The **critical latency number is `end_to_end_ms`** (server) plus the client
`final_to_translation_ms` UI gap. `refinement_ms` is reported separately and is
not included in the critical metric.

## What was measured

Measurements are from the development rig (Windows, local backend, real mic,
real Electron renderer). Backend timings are millisecond-accurate; client
timings use `performance.now()`.

| Stage | Typical | Notes |
| --- | --- | --- |
| Capture → ASR partial (`asr_partial_ms`) | ~500–800 ms | dominated by Deepgram streaming + Deepgram's own aggregation |
| Capture → ASR final (`asr_final_ms`) | ~900–1,600 ms | endpointing (600 ms default) + network |
| ASR final → translation (`translation_ms`) | 150–700 ms | cloud path ≈150–300 ms; NLLB CPU fallback 400–700 ms |
| Server end-to-end (`end_to_end_ms`) | ~1.1–2.3 s | = `asr_final_ms` + `translation_ms` |
| Translation → UI (`final_to_translation_ms`) | 5–20 ms | local WebSocket, negligible |
| LLM refinement (`refinement_ms`) | 0 (skipped) – 3 s | skipped for clean finals; async, never blocks |

End-to-end speech → translated text typically lands in **~1–2.5 s**, of which
the ASR portion is the floor set by Deepgram streaming and endpointing.

## Bottlenecks & the 12 optimization areas

1. **AudioWorklet chunk size** — kept at 100 ms. Deepgram's documented sweet
   spot is 50–250 ms; smaller chunks raise overhead per frame, larger chunks
   delay the first partial. 100 ms is a measured balance. Documented, not
   changed.
2. **Audio buffering / queue** — the renderer sends each chunk immediately as
   binary (no base64). Audio is raw linear16 PCM; no per-frame allocation is
   added by us beyond the worklet's transfer buffer.
3. **WS buffering** — the browser buffers a handful of frames at most; the
   backend drains the WebSocket receive loop continuously and never awaits
   translation before reading more audio.
4. **JSON serialization** — server events were serialized with
   `websocket.send_json(model_dump())` (a double dump: pydantic → dict →
   JSON). `Session.send_event` now serializes once
   (`json.dumps(event.model_dump(mode="json"))` + `send_text`, compact
   separators). Audio frames remain binary.
5. **Base64** — none in the audio path; raw PCM binary frames.
6. **FastAPI blocking ops** — the whole WebSocket pipeline is `asyncio`;
   NLLB (the only CPU-heavy step) runs in a thread via `asyncio.to_thread` and
   its model is now cached **process-wide** so it loads once per model/device,
   not once per session (see `nllb_provider._get_or_load_model`).
7. **Deepgram streaming config** — `deepgram_endpointing_ms=600` and
   `smart_format` stay on; these gate quality more than latency. Latency
   trades are documented rather than changed.
8. **Translation API latency** — cloud-first hybrid path (≈150–300 ms) is the
   default; NLLB is the offline fallback. Reused `httpx.AsyncClient` per
   provider instance (connection keep-alive).
9. **Repeated model/API init** — NLLB torch model is cached process-wide
   (keyed by `(model_name, device)`); cloud and LLM clients are created once
   per session, not per request.
10. **Unnecessary LLM calls** — `llm_skip_when_clean=True` (default): a cheap
    heuristic (`_looks_clean`) skips the refinement round-trip when the final
    transcript already has sentence punctuation, capital start, no double
    spaces / repeated words / long all-caps runs. Short/fragmentary utterances
    always still reach the LLM. Guarded by tests.
11. **Duplicate transcript processing** — partial transcripts are forwarded
    but are never queued for translation; only finalized segments enter the
    translation queue, keyed by `segment_id`. `asr_final_ms` rides along in
    the queue so `end_to_end_ms` composes exactly.
12. **UI rendering frequency** — VAD probability (dev-only number) updates are
    throttled to ~4 Hz and the duplicate `onProbability` subscription was
    removed; steady-state status dots no longer run `animate-pulse` during
    active transcription; the renderer re-renders on data change, not on a
    timer.

## Known limitations

- T0 (mic capture) is estimated, not measured per frame.
- `ui_ms` is defined as T7−T6 but the backend has no reliable T6-as-seen-by-
  client; the client derives `final_to_translation_ms` (T7 − client receipt of
  the final) as the practical UI gap, and `speech_to_translation_ms` composes
  from the server `end_to_end_ms`.
- `network_ms` is a half-round-trip estimate on the audio ack, so it includes
  server-side ack scheduling, not pure transport.
- Deepgram endpointing (600 ms) plus smart-format punctuation add ~0.5–1 s to
  `asr_final_ms`; shortening them would speed finals but degrade transcription
  quality. This is the biggest single, deliberate trade.
- NLLB CPU fallback is the slowest translation path (~0.5 s for short
  segments); it is only reached when the cloud provider is unavailable or
  unconfigured.

## Keeping it fast

- Frontend build must stay lean; the dev-only latency panel and diagnostics
  are gated behind `import.meta.env.DEV` and never ship to production.
- The 10-minute continuous-speech soak test (`backend/soak_ws.py`) verifies
  memory stability, WS connectivity, transcript ordering, translation sync,
  and pipeline responsiveness before each release.
