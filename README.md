# Real-Time Translator

A real-time, multilingual speech translator for online meetings (Zoom, Google Meet, etc.).
Streams live speech to text, translates it, and displays translated captions with
minimal latency — with silence detection used to produce clean sentence boundaries
and punctuation.

> **Status:** client-side Silero VAD is implemented (Phase 1.5) and the backend
> now streams live transcripts through **Deepgram streaming ASR** (Phase 1):
> interim/final results, punctuation + smart formatting, multilingual /
> language-detection, client-silence-driven utterance finalization, automatic
> reconnects, and measured ASR latency. The backend boots, serves `/health`, and
> passes 37 tests (transport + a Deepgram provider suite against a fake
> Deepgram server); the frontend typechecks, lints, builds, and renders
> real-time partial/final transcripts that freeze on finalization. Translation
> and LLM refinement are the remaining build phases — see `DEVELOPMENT_PLAN.md`.

## What this is

- **ASR:** Deepgram Streaming API (default), behind an `ASRProvider` interface.
- **Translation:** hybrid — a low-latency cloud provider by default, with NLLB-200
  as an offline/fallback provider, behind a `TranslationProvider` interface.
- **VAD (silence detection):** client-side Silero VAD running in an AudioWorklet,
  so silence detection never adds server round-trip latency.
- **LLM refinement:** an async, post-hoc pass that improves punctuation,
  capitalization, obvious ASR errors, and contextual terminology — it runs
  **after** an utterance is finalized and is never on the latency-critical path.

## Project structure

```
real-time-translator/
├── frontend/          React + TypeScript + Vite + Tailwind UI
│   └── src/
│       ├── components/  LanguageSelector, AudioControls, ConnectionStatus,
│       │                LatencyIndicator, ErrorBanner, TranscriptPanel,
│       │                TranslationPanel
│       ├── hooks/       useTranslatorSession, useAudioCapture
│       ├── providers/   vad/ (VADProvider interface + SileroVADProvider stub)
│       ├── lib/         wsClient.ts (TranslatorClient WebSocket wrapper)
│       ├── types/       shared types mirroring backend schemas
│       └── styles/      Tailwind entrypoint
├── backend/           FastAPI + asyncio + WebSocket pipeline
│   ├── app/             main.py, config.py, websocket/, services/ (asr,
│   │                    translation, vad, llm), models/, utils/
│   └── tests/           pytest suite (health, config, websocket, VAD)
├── docs/              Supplementary docs
├── tests/             Cross-cutting / integration tests (root level)
├── .env.example       All environment variables, documented
├── .gitignore
├── README.md          You are here
├── ARCHITECTURE.md    System design, data flow, provider abstractions
└── DEVELOPMENT_PLAN.md  Phased build-out plan and current status
```

See `ARCHITECTURE.md` for the full system design and `backend/app/services/*`
for the provider interfaces (`ASRProvider`, `TranslationProvider`, `LLMProvider`)
that keep business logic decoupled from any single vendor.

## Prerequisites

- Python 3.11+ (backend core). Tested on 3.14.
- Node.js 20+ and npm (frontend).
- [`uv`](https://docs.astral.sh/uv/) for Python dependency management (recommended),
  or plain `pip` + `venv`.
- API keys for whichever providers you enable (Deepgram, a cloud translation
  provider, an LLM provider) — see `.env.example`. None are required to run the
  scaffold: `/health` and the frontend shell need no external providers.

> Python version note: the backend pins `requires-python = ">=3.11"`. The core
> dependencies run fine on 3.14. Only the *offline* extra (`torch`,
> `transformers`, for NLLB-200) is constrained to 3.11/3.12 because those
> packages do not yet ship stable wheels for 3.14 — install it with
> `uv sync --extra offline` only if you need the offline fallback.

## Getting started

### Backend

```bash
cd backend
uv sync                         # creates/updates .venv and installs deps
cp ../.env.example .env         # then fill in DEEPGRAM_API_KEY etc. (optional)
uv run uvicorn app.main:app --reload --port 8000
```

Verify it's up:

```bash
curl http://localhost:8000/health
# {"status":"ok","env":"development","asr_provider":"deepgram","translation_provider":"cloud"}
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open the URL Vite prints (default `http://localhost:5173`). The Vite dev server
proxies `/api` and `/ws` to `http://localhost:8000` (see `frontend/vite.config.ts`),
so the frontend and backend can be developed independently.

### Running checks

```bash
# Backend: lint + tests
cd backend && uv run ruff check .
cd backend && uv run pytest

# Frontend: lint + typecheck + build
cd frontend && npm run lint
cd frontend && npm run typecheck
cd frontend && npm run build
```

## Design principles

1. **Provider abstractions everywhere.** `ASRProvider`, `TranslationProvider`,
   `LLMProvider`, and a client-side `VADProvider` mean no business logic is
   tightly coupled to Deepgram, a specific translation API, or a specific LLM.
2. **Latency-critical path stays lean.** ASR → translation → display is the hot
   path. LLM refinement is strictly async and only ever *improves* text already
   shown to the user — it never blocks it.
3. **Silence is signal.** Client-side VAD silence events double as endpointing
   hints, giving cleaner sentence boundaries and punctuation than relying on
   ASR endpointing alone.
4. **UI needs no manual.** Two panels (original / translation), one big
   start/stop control, obvious connection and latency indicators.

## Roadmap

See `DEVELOPMENT_PLAN.md` for the phased plan, from this scaffold through
production hardening and system/meeting-audio ingestion.
