# Development Plan

This tracks the phased build-out. Each phase should leave the app in a
runnable state (`/health` responds, frontend renders) even if features inside
it are incomplete.

## Phase 0 — Scaffolding ✅ (this change)

- [x] Repository structure: `frontend/`, `backend/`, `docs/`, `tests/`.
- [x] Backend: FastAPI app, `/health` endpoint, CORS, `.env`-driven config.
- [x] Backend: provider ABCs — `ASRProvider`, `TranslationProvider`, `LLMProvider`,
      `VADProvider`/`SilenceDetector` — with one default implementation stub each
      (`DeepgramASRProvider`, `CloudTranslationProvider`, `NLLBTranslationProvider`,
      `LLMRefinementProvider`), all raising `NotImplementedError` where real
      integration work remains.
- [x] Backend: WebSocket transport scaffold at `/ws/audio` (accepts connections,
      parses message envelopes, does not yet drive providers).
- [x] Backend: shared Pydantic schemas for the WS protocol.
- [x] Frontend: Vite + React + TypeScript + Tailwind app that builds and runs.
- [x] Frontend: reusable component set (language selector, audio controls,
      transcript/translation panels, connection status, latency indicator,
      error banner) wired into a single-screen UI needing no instructions.
- [x] Frontend: `useTranslatorSession`/`useAudioCapture` hooks and
      `TranslatorClient` WS wrapper scaffolded with the final state shape,
      pipeline wiring stubbed.
- [x] Frontend: client-side `VADProvider` interface + `SileroVADProvider` stub.
- [x] `.env.example`, `.gitignore`, `README.md`, `ARCHITECTURE.md` (this plan).

**Exit criteria:** `uv run uvicorn app.main:app` serves `/health`; `npm run dev`
renders the UI shell. Both verified structurally; see "Verification" below for
what could and couldn't be executed in the authoring environment.

## Phase 1 — Live transcription (ASR only, no translation yet)

- [x] Implement `DeepgramASRProvider.connect/send_audio/stream/close` against
      the real Deepgram streaming API (interim + final results, punctuation,
      smart formatting), using the `websockets` library directly for full
      control over reconnects, timeouts, and malformed-response handling.
- [x] Implement `useAudioCapture`: `getUserMedia` → `AudioWorkletProcessor` that
      resamples to 16kHz PCM16 and posts frames to the main thread.
- [x] Implement a minimal `pcm-capture-processor.js` AudioWorklet module
      (`frontend/public/worklets/`).
- [x] Wire `useTranslatorSession.start()` to open a `TranslatorClient`, send
      `start`, stream audio frames, and populate `transcript` from
      `partial_transcript`/`final_transcript` events.
- [x] Backend: flesh out `translate_stream.py` to parse `start`, instantiate the
      configured `ASRProvider`, forward binary frames to `send_audio`, and
      stream `TranscriptSegment`s back as WS events (partials immediately,
      finals on utterance end).
- [x] Backend: client-side VAD `silence_detected` events drive
      `ASRProvider.notify_silence` → a Deepgram `Finalize` control for clean
      utterance boundaries (see `docs/vad.md` and Phase 2 notes below).
- [x] Backend: measure and report audio→ASR latency (`asr_ms` in the `latency`
      WS event), surfaced in the UI's latency indicator.
- [ ] Manual test: speak into the mic with a real `DEEPGRAM_API_KEY`, see live
      captions in the Transcript panel with reasonable latency (English, Hindi,
      and a third language for the multilingual path).

## Phase 1.5 — Client-side Silero VAD ✅ (this change)

- [x] Silero VAD v5 model runs fully in the browser via onnxruntime-web (WASM)
      inside a dedicated Web Worker (`sileroVADWorker.ts`); model + WASM runtime
      provisioned by `frontend/scripts/setup-vad.mjs` into `frontend/public/`.
- [x] `SileroVADProvider` (`sileroVADProvider.ts`) implements the client
      `VADProvider` interface; the AudioWorklet keeps resampling/streaming and
      additionally posts 512-sample Float32 windows, so VAD never blocks audio.
- [x] Five VAD lifecycle events: `speech_started`, `speaking`,
      `silence_started`, `silence_detected`, `speech_resumed`, driven by a
      hysteresis + hangover + configurable silence-threshold state machine
      (100 ms pause ⇒ no boundary; ≥ 600 ms silence ⇒ `silence_detected`).
- [x] UI: ● Speaking / ○ Silence detected indicator in the header; settings
      sliders for the silence threshold and speech sensitivity; diagnostics
      rows for model status / probability.
- [x] Backend: `vad_event` client message added to the WS protocol
      (`schemas.VADEventMessage`), recorded per session for future
      utterance finalization; transport tests added.

**Exit criteria:** `npm run typecheck` / `npm run lint` / `npm run build` and
`uv run pytest` all pass (see "Verification"). Manual microphone testing must
still be run by a human in a real browser (see `docs/vad.md`).

## Phase 2 — Translation + silence-driven finalization ✅ (this change)

- [x] Implement `CloudTranslationProvider.translate` against the Google Cloud
      Translation v2 REST API (plain httpx, no SDK); implement `health_check`
      and `close`; error codes `cloud_config` / `cloud_connection` /
      `cloud_translation_error`.
- [x] Add the hybrid router (`HybridTranslationProvider`) behind the same
      `TranslationProvider` call site (no branching in the pipeline code):
      cloud first, NLLB-200 fallback per utterance on `TranslationError`;
      both failing raises `translation_failed` (non-fatal for the session).
- [x] Implement `NLLBTranslationProvider.warm_up`/`translate` (lazy model
      load, thread-executor to avoid blocking the event loop, FLORES-200
      codes via the central registry).
- [x] Central language registry (`languages.py`): `iso_code`, `display_name`,
      `cloud_code`, `nllb_code`; `register_language` /
      `TRANSLATION_EXTRA_LANGUAGES` for extra languages; `auto` semantics
      (cloud detects, NLLB rejects).
- [x] Transport: per-session ordered translation queue/worker in
      `translate_stream.py`; finals-only enqueue; `translation` +
      `translation_ms` latency events; `translation_failed` error events are
      non-fatal.
- [x] Implement `SileroVADProvider` fully (Web Worker running the Silero ONNX
      model, fed by the AudioWorklet) and wire VAD lifecycle events →
      `vad_event` WS messages (Phase 1.5).
- [x] Backend: use `SilenceDetector` + `ASRProvider.notify_silence` to force
      clean utterance boundaries; verify punctuation/finalization improves.
- [x] Backend: consume `session.last_vad_event` (`silence_detected`) to drive
      that finalization.
- [ ] Introduce a `PipelineOrchestrator` (backend) that owns per-session state
      and coordinates ASR → translation, keeping `translate_stream.py` thin.
      (Current design keeps that logic on `Session` in `translate_stream.py`.)
- [x] Frontend: populate `translation` state from `translation` events
      (latest + history panels); `LatencyIndicator` shows the most specific
      metric (`translation_ms` → `asr_ms` → `end_to_end_ms`);
      `translation_failed` is treated as non-fatal.
- [x] Tests: `test_languages.py`, `test_translation_providers.py` (cloud via
      `httpx.MockTransport`, NLLB via monkeypatched engine, hybrid fallback,
      factory modes), transport tests in `test_websocket.py` (finals-only,
      in-order, per-session languages, non-fatal failure).

**Exit criteria:** `uv run pytest` (74 passed), `uv run ruff check .`,
`npm run typecheck` / `npm run lint` / `npm run build` all pass (see
"Verification"). Real cloud + NLLB runs still require credentials / the
`offline` extra (see `docs/translation.md`).

## Phase 3 — Async LLM refinement

- [ ] Implement `LLMRefinementProvider.refine` with a tightly scoped prompt:
      fix punctuation/casing/obvious ASR errors and known terminology only —
      never rephrase or change meaning.
- [ ] Dispatch refinement as a fire-and-forget `asyncio.create_task` right
      after a segment is finalized; never `await` it before responding to
      the client.
- [ ] Push `refinement` events to the client; update the on-screen segment
      in place (with a subtle visual diff/highlight, then settle).
- [ ] Add a short rolling context window (recent finalized segments) passed
      into `refine()` for cross-segment terminology consistency.
- [ ] Verify: artificially slow down the LLM call and confirm captions are
      never delayed waiting on it.

## Phase 4 — Offline fallback + NLLB-200 ✅ (implemented; manual load-test pending)

- [x] Implement `NLLBTranslationProvider.warm_up`/`translate` (lazy model
      load, thread-executor to avoid blocking the event loop).
- [x] Automatic failover: `HybridTranslationProvider` falls back to NLLB per
      utterance whenever the cloud provider raises `TranslationError`, and
      reports the failure to the UI as a non-fatal `translation_failed`
      error event. (Implemented as per-utterance fallback rather than a
      session-level health-check switch.)
- [ ] Load-test NLLB latency on target hardware; document expected latency
      delta vs. cloud in `ARCHITECTURE.md`. Requires the `offline` extra on
      Python 3.11/3.12 (see `docs/translation.md`).

## Phase 5 — Meeting/system audio ingestion

- [ ] Design a second audio-capture source (tab/system audio capture or a
      meeting-bot integration) that feeds the same WS protocol.
- [ ] Handle multi-speaker audio: either accept diarization from the ASR
      provider or scope this explicitly out for v1.
- [ ] Document setup for Zoom/Google Meet in `docs/`.

## Phase 6 — Production hardening

- [ ] Reconnect/backoff logic in `TranslatorClient` (`reconnecting` state is
      already modeled in `ConnectionState`).
- [ ] Rate limiting / message size enforcement on the WS endpoint
      (`MAX_WS_MESSAGE_BYTES` already in config).
- [ ] Structured latency metrics end-to-end (`LatencyReport` already modeled);
      wire up real timing instead of `null`.
- [ ] Load testing for concurrent sessions; horizontal scaling notes for the
      FastAPI/WebSocket layer.
- [ ] Basic auth / meeting-scoped session tokens if deployed beyond local use.
- [ ] CI: run `ruff`, `mypy`, `pytest` (backend) and `tsc`, `eslint` (frontend)
      on every push.

## Verification performed for Phase 0

Actually executed on a Windows machine (Python 3.14, uv 0.11.8, Node 24/npm 11):

- Backend: `uv sync` resolves and installs cleanly.
- Backend: `uv run pytest` — 7 tests pass (health, config, websocket transport,
  VAD `SilenceDetector`).
- Backend: `uv run ruff check .` — clean.
- Backend: `uvicorn app.main:app` boots; `GET /health` returns
  `{"status":"ok","env":"development","asr_provider":"deepgram","translation_provider":"hybrid"}`.
- Frontend: `npm install` succeeds; `npm run lint` and `npm run typecheck` are
  clean; `npm run build` produces a production bundle.
- Frontend: `npm run dev` serves the UI shell at `http://localhost:5173` (HTTP 200).

Not yet verified: live ASR/translation (Phase 1+) — requires provider API keys.

## Verification performed for Phase 1.5 (VAD)

- Backend: `uv run pytest` — 18 tests pass, including three new `vad_event`
  transport tests.
- Backend: `uv run ruff check .` — clean.
- Frontend: `npm run typecheck`, `npm run lint`, `npm run build` all clean.
  The build no longer embeds the 13.5 MB onnxruntime wasm; it is served from
  `public/vendor/onnx/` via `ort.env.wasm.wasmPaths`.
- Model contract validated in both onnxruntime (Python) and onnxruntime-web
  (Node): Silero VAD v5 `input[1,576]` (64 context + 512 window), `state[2,1,128]`,
  `sr=16000` → `output[1,1]`, `stateN[2,1,128]`. Real speech yields p≈0.2–1.0,
  silence p<0.01; the JS API produced identical results to the Python probe
  (1452/1875 windows ≥ 0.5 on the reference test clip).
- Not verified: real-browser microphone capture and WASM loading in the
  worker — requires a human with a mic (checklist in `docs/vad.md`).

## Verification performed for Phase 1 (Deepgram streaming ASR)

- Backend: `uv run pytest` — **37 tests pass** (health, config, websocket
  transport, VAD, Deepgram provider). The ASR provider is tested against a
  local `FakeDeepgramServer` (no real API needed): partial→final mapping with
  stable segment ids, duplicate/empty-final dedup, malformed-message handling,
  `Finalize` control from `notify_silence`, per-language query params
  (en/hi/es) + `Authorization: Token` header, multilingual/language-detection
  for "auto", config/auth/server-error failure codes, reconnect-after-drop with
  backoff, and connection-refused handling. Transport tests verify partial/final
  forwarding, audio forwarding, latency events, and silence→endpointing hints.
- Backend: `uv run ruff check .` — clean.
- Frontend: `npm run typecheck`, `npm run lint`, `npm run build` all clean.
  On a final transcript the panel freezes the final line and clears the partial
  area for the next utterance; `asr_ms` latency is shown in the indicator.
- Not verified: live Deepgram audio — requires a real `DEEPGRAM_API_KEY`
  (add to `backend/.env`) and a browser mic; smoke-test English, Hindi, and a
  third language.

## Verification performed for Phase 2 (hybrid translation)

- Backend: `uv run pytest` — **74 tests pass** (health, config, websocket
  transport, VAD, Deepgram provider, language registry, translation providers).
  New suites: `test_languages.py` (registry mapping incl. FLORES-200 codes,
  `auto` semantics, unknown-language rejection, runtime registration) and
  `test_translation_providers.py` (cloud provider against `httpx.MockTransport`
  — success/auto-source/connection-error/bad-status/malformed-body/no-key/
  non-google-config; NLLB via monkeypatched `_load_model`/`_translate_engine`;
  hybrid cloud-success/failover/both-fail; factory modes). Transport tests
  verify finals-only translation, in-order delivery, per-session languages,
  `translation_ms` latency, and non-fatal `translation_failed`.
- Backend: `uv run ruff check .` — clean.
- Frontend: `npm run typecheck`, `npm run lint`, `npm run build` all clean.
  `LatencyIndicator` now shows the most specific metric (`translation_ms` →
  `asr_ms` → `end_to_end_ms`); `translation_failed` errors no longer flip the
  session into "error" state.
- Not verified: a live Google Cloud Translation API key (add
  `CLOUD_TRANSLATION_API_KEY` to `backend/.env`; fallback path exercises
  without a key once `CLOUD_TRANSLATION_PROVIDER_NAME=google`), and a real
  NLLB-200 model run — requires the `offline` extra on Python 3.11/3.12
  (`uv sync --extra offline`).
