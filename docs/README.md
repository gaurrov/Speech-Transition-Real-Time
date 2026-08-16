# docs/

Supplementary documentation for the Real-Time Translator. The authoritative
design and phased build-out docs live at the repo root:

- `ARCHITECTURE.md` — system design, data flow, provider abstractions.
- `DEVELOPMENT_PLAN.md` — phased build-out plan and current status.

Planned docs (not yet written):

- `provider-setup.md` — how to obtain and configure Deepgram, cloud
  translation, and LLM provider API keys.
- `meeting-audio.md` — capturing Zoom / Google Meet audio (system/tab audio,
  meeting-bot integration).
- `protocol.md` — the WebSocket message contract between frontend and backend.

Written so far:

- `vad.md` — client-side Silero VAD: events, thresholds, model loading,
  browser compatibility, performance, manual test checklist.
- `translation.md` — hybrid cloud → NLLB-200 translation fallback.
- `refinement.md` — async LLM transcript refinement: prompt scope, config,
  protocol, failure handling.
- `performance.md` — end-to-end latency instrumentation (T0–T9), measured
  numbers, bottlenecks, and optimizations.
