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
                               │   /ws/translate           │
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

It talks to Deepgram's `/v1/listen` WebSocket directly (via `websockets`, not
the SDK) so the failure/backoff behavior is fully under our control and is
testable against a fake server:

- `connect()` never blocks on the network. It spawns a **reader** task (owns
  the connection, reconnects with exponential backoff, base
  `deepgram_reconnect_base_delay_ms`, capped at `deepgram_reconnect_max_attempts`)
  and a **sender** task that drains a bounded audio queue, so streaming audio
  in never back-pressures the browser → backend WebSocket (oldest frames are
  dropped on overflow during a reconnect).
- `partial_transcript` results are forwarded the moment they arrive; finals are
  emitted on utterance end (Deepgram endpointing / `Finalize` / `UtteranceEnd`).
  Empty finals and duplicate finals are dropped; segment ids are stable
  (`<uid>-<n>`) so the UI can update a partial in place and freeze it on final.
- Failure codes (`ASRProviderError.code`): `deepgram_config` (missing API key),
  `deepgram_auth` (HTTP 401/403 or Error message), `deepgram_connection`
  (unreachable after retries), `deepgram_error` (Deepgram `Error` message),
  `deepgram_closed`. A fatal error surfaces once on `stream()` and tears down
  the session.
- `asr_latency_ms` on each `TranscriptSegment` estimates audio-received →
  ASR-result latency by interpolating the streaming timeline; the transport
  surfaces it as the `asr_ms` field of a `latency` WS event.

### `TranslationProvider` (`backend/app/services/translation/base.py`)

```
translate(segment_id, text, source_language, target_language, is_final) -> TranslationSegment
warm_up() -> None            # optional: load models / open connections
health_check() -> bool       # optional: used by the hybrid router
close() -> None              # optional: release HTTP clients / loaded models
```

Three implementations, selected by the `translation_provider` setting:

- `CloudTranslationProvider` — primary, low-latency path. Talks to Google
  Cloud Translation v2 REST directly with httpx (no SDK); endpoint and
  timeout configurable. Failure codes: `cloud_config`, `cloud_connection`,
  `cloud_translation_error`.
- `NLLBTranslationProvider` — offline fallback using the NLLB-200
  distilled-600M model. Loads lazily in a thread on first use; raises
  `translation_failed`/`nllb_model_unavailable` if the runtime can't load it.
- `HybridTranslationProvider` — default. Tries cloud first; on any
  `TranslationError` it falls back to NLLB for that utterance. Both failing
  raises `TranslationError("translation_failed")`. A transient cloud failure
  therefore degrades one utterance instead of failing the meeting.

Language codes are resolved centrally in `languages.py` (each `Language`:
`iso_code`, `display_name`, `cloud_code`, `nllb_code` FLORES-200 token); the
pipeline never branches on language pairs. `create_translation_provider()` in
`translation/__init__.py` is the only entry point the transport uses. See
`docs/translation.md` for the full design.

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
init() -> Promise<void>                       # load model in background; never blocks
start() -> Promise<void>                      # begin processing worklet frames
stop() -> Promise<void>                       # stop + reset the state machine
processFrame(samples: Float32Array) -> void   # feed one 512-sample window @ 16 kHz
onEvent(cb: (e: VADEvent) => void) -> () => void
onStateChange(cb: (s: VADStatus) => void) -> () => void
onProbability(cb: (p: number) => void) -> () => void   # throttled, diagnostics
configure(partial: Partial<VADConfig>) -> void          # live threshold changes
state -> VADStatus                            # idle | loading | speaking | silence | error
```

The pipeline (see `docs/vad.md` for the full write-up):

- The **AudioWorklet** (`pcmCaptureWorklet.js`) does capture + resampling +
  PCM16 streaming exactly as before. It additionally emits the same 16 kHz
  stream as 512-sample Float32 windows for VAD — so streaming is **never
  blocked** by VAD inference.
- **`SileroVADProvider`** (`sileroVADProvider.ts`) is a thin main-thread wrapper
  over a dedicated **Web Worker** (`sileroVADWorker.ts`) that runs the Silero
  VAD v5 ONNX model with onnxruntime-web (WASM). Model loading is
  fire-and-forget; frames arriving before the model is ready are buffered
  (bounded) in the worker and replayed.
- The worker emits five lifecycle events: `speech_started`, `speaking`
  (heartbeat while active), `silence_started` (transient, after the hangover),
  `silence_detected` (utterance boundary after the configurable silence
  threshold), and `speech_resumed`. A 100 ms pause therefore produces no
  boundary; a 600 ms pause produces `silence_detected` (with `duration_ms`).
- Events are forwarded to the UI (● Speaking / ○ Silence detected) and, in
  live mode, to the backend as `vad_event` messages that the ASR provider can
  use as endpointing hints later.

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

Single endpoint: `ws://<backend>/ws/translate`. See
`backend/app/models/schemas.py` for exact payloads. Every message is a JSON
envelope of the form `{"type": "<message>", ...fields}`; audio frames travel as
raw binary WebSocket messages rather than base64-encoded JSON.

**Client → Server**
| Message | Shape |
|---|---|
| Start session | `{"type": "start_session", "session_id"?: str}` |
| Session configuration | `{"type": "session_configuration", session_id, source_language, target_language, audio_source, sample_rate?, encoding?}` |
| Audio | binary WebSocket frame (raw PCM16 or Opus) |
| Audio chunk (control) | `{"type": "audio_chunk", "session_id": str}` |
| VAD event | `{"type": "vad_event", session_id, event, timestamp_ms, duration_ms?, probability?}` — `event` ∈ `speech_started \| speaking \| silence_started \| silence_detected \| speech_resumed` |
| Stop session | `{"type": "stop_session", "session_id": str}` |

**Server → Client**
| Message | Shape |
|---|---|
| Session started | `{"type": "session_started", session_id, configuration}` |
| Speech lifecycle | `{"type": "speech_started" \| "silence_detected" \| "speech_resumed", session_id, timestamp_ms, duration_ms?}` |
| Partial/final transcript | `{"type": "partial_transcript" \| "final_transcript", session_id, ...TranscriptEvent}` |
| Translation | `{"type": "translation", session_id, ...TranslationEvent}` |
| Async refinement | `{"type": "refined_transcript", session_id, segment_id, refined_text, changed}` |
| Latency report | `{"type": "latency", session_id, segment_id, asr_ms, translation_ms, refinement_ms?, end_to_end_ms}` |
| Error | `{"type": "error", code, message, session_id?}` |
| Session stopped | `{"type": "session_stopped", session_id, reason}` |

## 6. Frontend structure

```
frontend/src/
├── components/         one folder per reusable UI piece (own file + index.ts)
│   ├── CompactHeader/      drag handle + connection dot + mode/settings/pin/
│   │                       minimize/close buttons (the frameless window chrome)
│   ├── CompactPanel/       titled card used for the LIVE SPEECH / TRANSLATION panels
│   ├── LanguageBar/        source → target selectors (Auto Detect → target)
│   ├── TranscriptView/     live speech panel (partials in place, finals frozen)
│   ├── TranslationView/    translation panel; `prominent` layout for compact
│   │                       mode, scrollable per-utterance history in expanded
│   ├── ListeningControls/  Start/Stop footer with ● status
│   ├── SettingsModal/      mode, VAD tuning, and DEV-only diagnostics
│   └── ...                 ConnectionDot, ErrorBanner, icons, status helpers
├── hooks/
│   ├── useTranslatorSession.ts   orchestrates connection + pipeline state
│   └── useAudioCapture.ts        getUserMedia + AudioWorklet plumbing
├── providers/
│   └── vad/                      VADProvider interface + SileroVADProvider
├── lib/
│   └── wsClient.ts                thin WebSocket transport (TranslatorClient)
├── types/                         shared types mirroring backend schemas
├── styles/                        Tailwind entrypoint (.app-drag / .app-no-drag)
├── App.tsx                        compact UI shell: header, language bar,
│                                  transcript/translation panels, controls
└── main.tsx
```

`useTranslatorSession` is the single seam between UI and networking/audio —
components never touch `WebSocket` or `MediaStream` directly, which keeps the
UI layer trivial to test and restyle.

## 6a. Electron desktop companion window

The app ships as a small always-on-top desktop window rather than a full-page
site, so it can sit beside Zoom/Meet/Teams while the meeting runs.

```
Electron
├── Main process (electron/main.js)
│   ├── Creates a compact frameless BrowserWindow (default ~420×600)
│   ├── alwaysOnTop("floating"), resizable, min 320×480
│   ├── Remembers size/position in <userData>/window-state.json
│   ├── Auto-starts the FastAPI backend if :8000 is not already serving
│   │   (set TRANSLATOR_EXTERNAL_BACKEND=true to run it yourself)
│   └── IPC surface: window:minimize / window:close /
│       window:toggle-always-on-top / window:is-always-on-top
├── Renderer process
│   └── The existing React app (dev: Vite server; prod: frontend/dist via file://)
└── Preload (electron/preload.js)
    └── contextBridge exposes a single narrow `window.desktop` object
```

Security model (all enforced in `electron/main.js` webPreferences):

- `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`,
  `webSecurity: true`.
- The only bridge is `window.desktop` (isElectron, platform, minimize, close,
  toggleAlwaysOnTop, isAlwaysOnTop, onAlwaysOnTopChanged). No Node APIs reach
  the React renderer.
- The renderer reaches the backend over the exact same `ws://…/ws/translate`
  protocol as the browser build — the Electron shell adds no AI pipeline code
  and changes nothing in ASR/translation/VAD handling.

UI behavior:

- Two display modes, persisted in `localStorage`:
  - **Expanded**: language selectors + LIVE SPEECH panel + TRANSLATION panel.
  - **Compact**: only the latest translation + ● status (EN → HI + Live dot).
- The header is the drag handle (`.app-drag`); buttons opt out (`.app-no-drag`).
- Always-on-top has a pin/unpin toggle, kept in sync with the OS window state
  via the `window:always-on-top-changed` push event.
- Latency metrics, raw WS events, and audio diagnostics are development-only —
  they render only when built for development and live inside Settings.

Development workflow (see README):

- `npm run dev` (in `electron/`) runs backend + Vite + Electron together.
- The main process loads `VITE_DEV_SERVER_URL` when set, otherwise
  `frontend/dist/index.html`. Vite uses a relative `base: "./"` so the built
  bundle also works over `file://` inside the window.

## 7. Backend structure

```
backend/app/
├── main.py              FastAPI app: CORS, router mounting, /health
├── config.py             pydantic-settings Settings, env-driven
├── websocket/
│   └── translate_stream.py  /ws/translate transport layer (thin) + SessionManager
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

Notice `websocket/translate_stream.py` stays thin on purpose — it's transport, not
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
| Translation (NLLB fallback) | 1–3 s, only on cloud failure |
| Total: speech → on-screen translation | < 500 ms |
| LLM refinement (async, non-blocking) | 1–3 s, off critical path |

These are targets to validate against. ASR latency is now actually measured
(`asr_ms` per segment, plus `asr_partial_ms`/`asr_final_ms`), translation
latency is measured too (`translation_ms` per segment), LLM refinement is
measured separately (`refinement_ms`, sent in the `latency` event after every
refinement attempt — success or failure, and skipped when `llm_skip_when_clean`
detects an already-clean final), and end-to-end timing is composed server-side
as `end_to_end_ms` (live path only, refinement excluded) and client-side as
`speech_to_translation_ms`. Measured numbers and the full T0–T9 legend live in
[`docs/PERFORMANCE.md`](docs/PERFORMANCE.md).
