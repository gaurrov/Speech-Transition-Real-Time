# Architecture

## 1. Goals and constraints

- **Low latency end-to-end.** Speech must appear as translated captions within a
  few hundred milliseconds, not seconds.
- **Provider independence.** Deepgram, the cloud translation API, NLLB-200, and
  the LLM refinement provider must all be swappable without touching pipeline
  or UI code. This is enforced with abstract provider interfaces.
- **Correctness improves without blocking speed.** Punctuation/terminology
  refinement is valuable but must never sit on the hot path.
- **Silence is a first-class signal**, not just "no audio" — it's used both to
  save bandwidth/compute and to produce clean sentence boundaries.
- **Extensible to meeting audio.** The pipeline should not assume "microphone"
  as the only audio source; system/meeting audio capture is a planned input,
  not an architectural afterthought.

## 2. High-level data flow

```
┌─────────────┐   PCM frames    ┌──────────────────┐
│  Microphone /│ ───────────────▶│  Silero VAD       │  (AudioWorklet, client-side)
│  meeting audio│                │  speech/silence   │
└─────────────┘                 └─────────┬─────────┘
                                           │ speech_start / speech_end events
                                           ▼
                              ┌────────────────────────┐
                              │  Audio capture pipeline  │  (client-side)
                              │  getUserMedia → Worklet  │
                              └────────────┬─────────────┘
                                           │ 16kHz PCM frames + silence events
                                           ▼  (WebSocket, binary + JSON control)
                              ┌────────────────────────┐
                              │   FastAPI WS endpoint    │  backend/app/websocket
                              │   /ws/audio               │
                              └────────────┬─────────────┘
                                           │
                          ┌────────────────┼────────────────┐
                          ▼                                   ▼
              ┌─────────────────────┐             notify_silence() hints
              │   ASRProvider         │◀───────────────────────────────┐
              │   (Deepgram default)  │                                 │
              └───────────┬───────────┘                                 │
                          │ partial + final TranscriptSegment            │
                          ▼                                              │
              ┌─────────────────────┐                                   │
              │  TranslationProvider  │  hybrid: cloud (default) ────────┘
              │  cloud / NLLB          │  or NLLB-200 (fallback/offline)
              └───────────┬───────────┘
                          │ partial + final TranslationSegment
                          ▼
              ┌─────────────────────┐        (fire-and-forget, async)
              │  Client (React UI)    │◀────────────┐
              │  transcript + captions │             │
              └───────────┬───────────┘             │
                          │ final segment id          │
                          ▼                            │
              ┌─────────────────────┐                 │
              │   LLMProvider          │────────────────┘
              │   async refinement pass │  REFINEMENT event, replaces
              └─────────────────────┘  displayed text in place, non-blocking
```

Key point: **the LLM box is not in the request/response chain that produces the
first visible caption.** It's triggered after a segment is finalized, runs in
a background asyncio task, and pushes a correction later via a separate
`refinement` WebSocket event. The UI already has *something* on screen; the
refinement just makes it better.

## 3. Provider abstractions

All providers are ABCs so the pipeline/orchestrator and the UI depend only on
interfaces, never concrete vendors.

### `ASRProvider` (`backend/app/services/asr/base.py`)

```
connect(sample_rate, encoding, language) -> None
send_audio(chunk: bytes) -> None
notify_silence(duration_ms: int) -> None
stream() -> AsyncIterator[TranscriptSegment]
close() -> None
```

`DeepgramASRProvider` is the default implementation. `notify_silence` maps to
Deepgram's endpointing/finalize controls, letting client-detected silence force
a clean utterance boundary rather than waiting on server-side heuristics alone.

### `TranslationProvider` (`backend/app/services/translation/base.py`)

```
translate(segment_id, text, source_language, target_language, is_final) -> TranslationSegment
warm_up() -> None            # optional: load models / open connections
health_check() -> bool       # optional: used by the hybrid router
```

Two implementations:
- `CloudTranslationProvider` — default. Wraps a cloud translation API
  (Google / DeepL / Azure, selected via config) for lowest latency.
- `NLLBTranslationProvider` — offline fallback using the NLLB-200 model,
  used when the cloud provider's `health_check()` fails, when explicitly
  configured for offline operation, or for languages the cloud provider
  doesn't cover well.

A thin **hybrid router** (planned in `DEVELOPMENT_PLAN.md` Phase 2) selects
between them per request based on `health_check()` and configuration, so
callers just call "the" `TranslationProvider`.

### `LLMProvider` (`backend/app/services/llm/base.py`)

```
refine(segment_id, text, language, context) -> RefinementResult
```

`LLMRefinementProvider` is the default implementation. `context` is a short
window of recent finalized segments so terminology stays consistent across an
utterance or meeting (e.g. a company/product name transcribed inconsistently).

### `VADProvider` (frontend: `frontend/src/providers/vad/types.ts`)

VAD runs **client-side** for latency reasons (a round-trip to the server just
to learn "the user stopped talking" would defeat the purpose). The interface:

```
init() -> Promise<void>
start(stream: MediaStream) -> Promise<void>
stop() -> Promise<void>
onEvent(callback: (event: VADEvent) => void) -> void
```

`SileroVADProvider` runs the Silero VAD model inside an `AudioWorkletProcessor`
so classification happens off the main thread, frame-by-frame, with no
network round trip. `speech_start`/`speech_end` events are turned into
`silence` WebSocket messages the backend forwards to the ASR provider as
endpointing hints.

The backend also defines a `SilenceDetector` helper
(`backend/app/services/vad/base.py`) that turns raw silence-duration reports
into a "should this finalize the utterance?" decision, using two tunables:
- `SILENCE_FINALIZE_MS` — how much silence implies "sentence is over".
- `SILENCE_MIN_SPEECH_MS` — minimum preceding speech to avoid false triggers
  from breath sounds / noise.

## 4. Why VAD is client-side but the interface lives on both sides

Silero VAD executes in the browser for latency. But the *concept* of "was this
gap in audio significant enough to be a sentence boundary" is also useful
server-side (e.g. if audio ever arrives from a source without a client
worklet — a recorded meeting file, or server-side capture of meeting audio).
That's why there's a `VADProvider` interface on the frontend for the live
capture path, and a separate `SilenceDetector`/`VADProvider` on the backend for
interpreting silence signals and, later, for any server-side VAD fallback —
without changing how the ASR/translation pipeline consumes "silence happened
here" events.

## 5. WebSocket protocol

Single endpoint: `ws://<backend>/ws/audio`. See
`backend/app/models/schemas.py` for exact payloads.

**Client → Server**
| Message | Shape |
|---|---|
| Start session | `{"type": "start", "source_language", "target_language", "sample_rate", "encoding"}` |
| Audio | binary WebSocket frame (raw PCM16 or Opus) |
| Silence event | `{"type": "silence", "duration_ms": N}` |
| Stop session | `{"type": "stop"}` |

**Server → Client**
| Message | Shape |
|---|---|
| Partial/final transcript | `{"type": "transcript_partial" \| "transcript_final", ...TranscriptSegment}` |
| Partial/final translation | `{"type": "translation_partial" \| "translation_final", ...TranslationSegment}` |
| Async refinement | `{"type": "refinement", ...RefinementResult}` |
| Status | `{"type": "status", "message": str}` |
| Error | `{"type": "error", "code": str, "message": str}` |
| Latency report | `{"type": "latency", ...LatencyReport}` |

## 6. Frontend structure

```
frontend/src/
├── components/         one folder per reusable UI piece (own file + index.ts)
│   ├── LanguageSelector/
│   ├── AudioControls/
│   ├── ConnectionStatus/
│   ├── LatencyIndicator/
│   ├── ErrorBanner/
│   ├── TranscriptPanel/
│   └── TranslationPanel/
├── hooks/
│   ├── useTranslatorSession.ts   orchestrates connection + pipeline state
│   └── useAudioCapture.ts        getUserMedia + AudioWorklet plumbing
├── providers/
│   └── vad/                      VADProvider interface + SileroVADProvider
├── lib/
│   └── wsClient.ts                thin WebSocket transport (TranslatorClient)
├── types/                         shared types mirroring backend schemas
├── styles/                        Tailwind entrypoint
├── App.tsx                        UI shell: selectors, controls, two panels
└── main.tsx
```

`useTranslatorSession` is the single seam between UI and networking/audio —
components never touch `WebSocket` or `MediaStream` directly, which keeps the
UI layer trivial to test and restyle.

## 7. Backend structure

```
backend/app/
├── main.py              FastAPI app: CORS, router mounting, /health
├── config.py             pydantic-settings Settings, env-driven
├── websocket/
│   └── audio_stream.py   /ws/audio transport layer (thin)
├── services/
│   ├── asr/               ASRProvider + DeepgramASRProvider
│   ├── translation/        TranslationProvider + Cloud/NLLB implementations
│   ├── vad/                 VADProvider + SilenceDetector
│   └── llm/                  LLMProvider + LLMRefinementProvider
├── models/
│   └── schemas.py          shared Pydantic models (WS + internal)
└── utils/
    └── logging.py           structlog setup
```

Notice `websocket/audio_stream.py` stays thin on purpose — it's transport, not
orchestration. As Phase 2 (see `DEVELOPMENT_PLAN.md`) lands, a
`PipelineOrchestrator` (or similar) will sit between the transport layer and
the providers, owning per-session state, provider selection, and the async
refinement dispatch — keeping the WebSocket handler itself simple regardless
of how complex the pipeline gets.

## 8. Path to meeting/system audio

Today's design already generalizes past "microphone": the WebSocket protocol
and `ASRProvider` interface don't care where PCM frames come from. Consuming
Zoom/Meet system audio is a matter of adding a capture source (e.g. a
platform-level loopback capture, a meeting-bot integration, or a browser tab
audio capture) that feeds the same `useAudioCapture` → WebSocket → `ASRProvider`
path. No changes to ASR, translation, VAD-interpretation, or refinement layers
are expected.

## 9. Latency budget (target, for tuning once implemented)

| Stage | Target |
|---|---|
| Client capture → WS send | < 20 ms |
| ASR partial result | < 300 ms |
| Translation (cloud) | < 150 ms |
| Total: speech → on-screen translation | < 500 ms |
| LLM refinement (async, non-blocking) | 1–3 s, off critical path |

These are targets to validate against once providers are implemented, not
measured results.
