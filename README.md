# Real-Time Translator

A real-time, multilingual speech translator for online meetings (Zoom, Google Meet, etc.).
Streams live speech to text, translates it, and displays translated captions with
minimal latency — with silence detection used to produce clean sentence boundaries
and punctuation. It ships as a compact, always-on-top **desktop companion window**
(Electron) that sits beside your meeting and shows live translations while you talk.

> **Status:** the backend now streams live transcripts through **Deepgram
> streaming ASR** (Phase 1) and translates finalized utterances through
> **NLLB-200** (default) with optional cloud/hybrid paths (Phase 2):
> interim/final results, punctuation + smart formatting, multilingual /
> language-detection, client-silence-driven utterance finalization, automatic
> reconnects, and measured ASR **and** translation **and** LLM-refinement
> latency. The backend boots, serves `/health`, and passes 114 tests
> (transport + Deepgram provider suite against a fake server +
> language-registry/cloud/NLLB/hybrid provider suites + LLM refinement
> provider/transport suites); the frontend typechecks, lints, builds, and
> renders real-time partial/final transcripts that freeze on finalization,
> plus live translations and post-hoc refined transcripts. The whole server
> side is also deployable with Docker (see "Deploying with Docker"
> below and `docs/DOCKER.md`).

## What this is

- **ASR:** Deepgram Streaming API (default), behind an `ASRProvider` interface.
- **Translation:** NLLB-200 (default), with cloud translation available as an
  optional hybrid/fallback path, behind a `TranslationProvider` interface.
- **VAD (silence detection):** client-side Silero VAD running in an AudioWorklet,
  so silence detection never adds server round-trip latency.
- **LLM refinement:** an async, post-hoc pass that improves punctuation,
  capitalization, obvious ASR errors, and contextual terminology — it runs
  **after** an utterance is finalized and is never on the latency-critical path.

## Project structure

```
real-time-translator/
├── electron/         Electron desktop companion window
│   ├── main.js         main process: compact always-on-top window, window-state
│   │                   persistence, backend auto-start, window IPC
│   ├── preload.js      contextBridge: exposes only window.desktop controls
│   └── package.json    dev scripts (backend + vite + electron together)
├── frontend/          React + TypeScript + Vite + Tailwind UI
│   └── src/
│       ├── components/  CompactHeader, LanguageBar, TranscriptView,
│       │                TranslationView, ListeningControls, SettingsModal, ...
│       ├── hooks/       useTranslatorSession, useAudioCapture
│       ├── providers/   vad/ (VADProvider interface + SileroVADProvider stub)
│       ├── lib/         wsClient.ts (TranslatorClient WebSocket wrapper)
│       ├── types/       shared types mirroring backend schemas
│       └── styles/      Tailwind entrypoint
├── backend/           FastAPI + asyncio + WebSocket pipeline
│   ├── app/             main.py, config.py, websocket/, services/ (asr,
│   │                    translation, vad, llm), models/, utils/
│   └── tests/           pytest suite (health, config, websocket, VAD,
│                        Deepgram ASR, languages, translation providers)
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
# {"status":"ok","env":"development","asr_provider":"deepgram","translation_provider":"nllb"}
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

## Deploying with Docker

The server side is fully containerized (nginx reverse proxy + FastAPI backend +
NLLB-200 translation service); the Electron window stays on your machine
and just connects to the deployed WebSocket endpoint. See
[`docs/DOCKER.md`](docs/DOCKER.md) for the full guide.

```bash
# Development stack (frontend :8080, backend :8000, NLLB :8001 internal, WS through nginx)
docker compose up --build

# Production stack (frontend on :80 only)
docker compose -f docker-compose.prod.yml up -d --build
```

NLLB-200 always starts with the stack (no profile needed). Only `DEEPGRAM_API_KEY`
is required in `.env`. Port 8000 conflicts with a locally running backend?
`BACKEND_PORT=18000 docker compose up -d`.

## Desktop companion (Electron)

The translator runs as a small floating window that stays on top of your meeting
(Zoom, Meet, Teams). It is **not** a full-screen site.

### Start everything at once

```bash
npm run install:all   # first time: install frontend + electron deps
npm run dev           # starts FastAPI backend + Vite dev server + Electron
```

`npm run dev` is defined in the **electron** package and uses `concurrently` to
run all three together: the backend on `:8000`, Vite on `:5173`, and Electron
(which waits on both ports, then loads `http://localhost:5173`).

Individual pieces (useful while iterating):

```bash
npm run dev:backend    # uvicorn with --reload
npm run dev:frontend   # Vite only (browser tab, no window chrome)
npm run dev:electron   # Electron only (uses already-running backend + Vite)
```

To run Electron against the **built** renderer instead of the dev server:

```bash
npm run start   # builds frontend/dist, then launches Electron (loads file://)
```

### Window behavior

- Compact companion window (~420×600), `alwaysOnTop` ("floating" level), movable
  by dragging the header, resizable, minimizable.
- Size and position are remembered between launches (`window-state.json`).
- Pin/unpin button toggles always-on-top.
- Two display modes: **Expanded** (source transcript + translation + language
  selectors) and **Compact** (translation only). Switch via the header.
- Debug-only details (latency, WS events, audio diagnostics) are hidden unless
  the app was built for development and are exposed only through Settings.

### Security model

The renderer runs with `contextIsolation: true`, `nodeIntegration: false`,
`sandbox: true`, and `webSecurity: true`. The preload script exposes **only**
`window.desktop` (minimize/close/pin/always-on-top) via `contextBridge` — no
Node APIs reach the React code. See `electron/main.js` + `electron/preload.js`
and the Electron section in `ARCHITECTURE.md`.

The renderer still talks to FastAPI exactly as before over the existing
WebSocket protocol — the desktop shell adds no new AI pipeline code and changes
nothing in ASR/translation/WebSocket handling.

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
