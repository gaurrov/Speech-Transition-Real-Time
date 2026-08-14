# Client-side Voice Activity Detection (Silero VAD)

Voice activity detection tells the app when the user is speaking and when they
have stopped. It runs **entirely in the browser** so the latency between "user
stops talking" and "we can finalize the utterance" is a few milliseconds
instead of a network round-trip.

```
Microphone ──▶ AudioWorklet ──┬──▶ 16 kHz PCM16 ──▶ WebSocket ──▶ backend
(pcmCaptureWorklet.js)        │
                              └──▶ 512-sample Float32 windows
                                   └──▶ VAD Worker ──▶ speech/silence events
                                        (onnxruntime-web WASM + Silero v5)
```

VAD inference lives in a **Web Worker**, not the AudioWorklet, so classification
never competes with the real-time audio graph and never blocks the streaming
path. Streaming and VAD consume the same 16 kHz resampled stream concurrently.

## Events

| Event | When it fires | UI |
|---|---|---|
| `speech_started` | probability crosses the threshold from silence | ● Speaking |
| `speaking` | heartbeat while speech stays active (default every 200 ms) | ● Speaking |
| `silence_started` | speech dropped below threshold for the hangover (300 ms) | ○ Silence detected |
| `silence_detected` | silence exceeds the utterance threshold (default 600 ms) | ○ Silence detected |
| `speech_resumed` | speech returns while the utterance is still "pending" | ● Speaking |

Because `silence_detected` requires the silence to exceed the configured
threshold measured from the *last* speech frame:

- a **100 ms pause** ("Hello … World") produces **no boundary** — the state
  machine stays in `speaking` (below the 300 ms hangover) and `speech_resumed`
  is never needed;
- a **600 ms pause** produces `silence_detected` (with `duration_ms: 600`),
  which the backend records (`session.last_vad_event`) and can later use to
  force a clean utterance boundary for ASR finalization.

### Hysteresis

Silero probabilities swing frame to frame, so the state machine uses two
thresholds (the same rule as Silero's reference `VADIterator`):

- **onset** — `speechProbThreshold` (default `0.5`) to *enter* speech;
- **release** — `speechProbThreshold - 0.15` to *leave* it.

Noise measures p≈0.01–0.02, silence p<0.01, and real speech p up to 1.0, so
the default threshold is well separated from both.

## Configuration

Configurable at runtime (Settings → *Voice activity detection*), live:

| Setting | Default | Effect |
|---|---|---|
| Silence threshold (`silenceThresholdMs`) | 600 ms | Pauses longer than this end the utterance; shorter ones keep it. Range 100–1500 ms. |
| Speech sensitivity (`speechProbThreshold`) | 0.50 | Lower ⇒ catches quieter speech but risks noise triggers. Range 0.30–0.90. |

Fixed by design: `windowSize` 512 samples (30 ms @ 16 kHz), `contextSize` 64,
`hangoverMs` 300, `speakingHeartbeatMs` 200. Full defaults live in
`frontend/src/providers/vad/types.ts` (`DEFAULT_VAD_CONFIG`).

## Model loading

1. `frontend/scripts/setup-vad.mjs` (run by `npm run vad:setup`, and
   automatically by `predev`/`prebuild`) provisions:
   - `frontend/public/models/silero_vad.onnx` — Silero VAD **v5**
     (`https://github.com/snakers4/silero-vad`), ~2.3 MB, downloaded once;
   - `frontend/public/vendor/onnx/ort-wasm-simd-threaded.{mjs,wasm}` — the
     onnxruntime-web loader + WASM (~13.5 MB), copied from
     `node_modules/onnxruntime-web/dist/` (no network).
2. At runtime the VAD worker sets `ort.env.wasm.wasmPaths = "/vendor/onnx/"`,
   fetches the model (same-origin first, CDN fallbacks after), and creates an
   `InferenceSession`. If the model file is missing, the app falls back to the
   CDN copy; if that also fails, the VAD indicator shows *VAD error* and the
   UI falls back to the worklet's RMS activity check.

### Model contract (Silero VAD v5)

```
input  : float32 [1, 576]   ← 64 context samples + 512 window (16 kHz)
state  : float32 [2, 1, 128] ← recurrent state, zeros to start
sr     : int64  [1]          ← 16000
output : float32 [1, 1]      ← speech probability
stateN : float32 [2, 1, 128] ← state for the next window
```

The 64-sample context (the tail of the previous window, or zeros) is required;
feeding 512 samples alone produces unreliable probabilities. Both the Python
and JavaScript probes reproduced identical results on the reference clip
(1452/1875 windows ≥ 0.5, p max 1.0).

## Browser compatibility

- Requires `AudioWorklet` (Chrome 66+, Edge, Firefox 76+, Safari 14.1+).
- Requires WebAssembly + **SharedArrayBuffer-compatible threads**, which all
  evergreen browsers provide.
- The worker runs **single-threaded** by default
  (`ort.env.wasm.numThreads = 1`), which works without cross-origin isolation.
- For multi-threaded WASM inference, the hosting page must opt into cross-origin
  isolation (`Cross-Origin-Opener-Policy: same-origin` and
  `Cross-Origin-Embedder-Policy: require-corp`). This app does not require it;
  VAD is cheap (~1 ms per 30 ms window) so a single thread is sufficient.
- Web Workers (`type: "module"`) require a secure context — fine on
  `localhost` in development and on HTTPS in production.

## Performance

| Step | Cost |
|---|---|
| Worklet resample + Float32 window (512 samples) | negligible, real-time thread |
| Worker inference (WASM, single thread) | ~1 ms per 30 ms window, off main thread |
| WASM fetch + session creation | ~1–2 s one-time, overlapped with streaming start |
| Frames during model load | buffered (up to ~4.5 s) in the worker, replayed in order |

The VAD worker never blocks `sendAudio`: the AudioWorklet posts PCM16 chunks
and VAD windows as independent messages, and `session.run()` is serialized on a
promise chain in the worker so frames are processed in order without ever
back-pressuring the audio graph.

## Manual test checklist (requires a real microphone)

1. `cd backend && uv run uvicorn app.main:app` and
   `cd frontend && npm run dev`.
2. Open `http://localhost:5173`, allow the microphone, press **Start**.
3. In the header: *VAD loading…* appears briefly, then *Listening*.
4. Speak: the indicator flips to **● Speaking** and the session status to
   *Speaking*. Stop: after ~300 ms it shows **○ Silence detected**.
5. Say "Hello" then pause ~100 ms then "world" — the utterance must **not**
   end (status returns to *Speaking*, no `silence_detected`).
6. Speak a sentence and stay silent ~600 ms — the VAD indicator stays at
   *Silence detected* and a `vad_event` with `event: "silence_detected"` is
   logged by the backend (visible in the backend console at debug level).
7. Settings → *Voice activity detection*: raise/lower the silence threshold
   and confirm the boundary behaviour changes immediately.
8. Diagnostics panel (dev only): *VAD model*, *VAD probability* (should climb
   above 0.5 while speaking, drop below 0.1 in silence), *VAD silence threshold*.

## Files

- `frontend/src/providers/vad/types.ts` — events, config, provider interface.
- `frontend/src/providers/vad/sileroVADWorker.ts` — inference + state machine.
- `frontend/src/providers/vad/sileroVADProvider.ts` — main-thread wrapper.
- `frontend/src/audio/pcmCaptureWorklet.js` — resample/stream + VAD windows.
- `frontend/src/hooks/useAudioCapture.ts` — VAD wiring in the capture hook.
- `frontend/src/hooks/useTranslatorSession.ts` — VAD events → status + backend.
- `frontend/scripts/setup-vad.mjs` — asset provisioning.
- `backend/app/websocket/translate_stream.py` — `vad_event` handling.
- `backend/app/models/schemas.py` — `VADEventMessage` protocol model.
