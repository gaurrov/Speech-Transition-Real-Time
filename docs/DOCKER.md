# Deploying with Docker

Everything needed to run the translator **server side** is containerized. The
Electron desktop window intentionally stays on your machine (it needs your
microphone/system audio and an always-on-top window) — it simply connects to
the deployed WebSocket endpoint, exactly as it connects to `localhost:8000` in
development.

## 1. Prerequisites

- Docker Engine **24+** with the Compose plugin (Compose **v2.24+** is required
  for `env_file.required`; Docker Desktop ships a recent Compose by default).
- The project root has a `.env` file (copy `.env.example`). **Every variable is
  optional** — the stack boots without any of them; you only add keys for the
  providers you enable.
- An **HTTPS domain** only if you deploy to the public internet (see §10).

## 2. What gets containerized

| Container   | Image basis            | Role                                                        |
| ----------- | ---------------------- | ----------------------------------------------------------- |
| `frontend`  | nginx:1.27-alpine      | Serves the built React app + reverse-proxies `/api`, `/health`, `/ws/` to the backend |
| `backend`   | python:3.12-slim       | FastAPI: Deepgram streaming ASR, translation, LLM refinement, WebSocket pipeline |
| `nllb`      | python:3.12-slim       | NLLB-200 translation service (always starts, internal only, never published) |

- The backend image runs as a **non-root** user and has a `HEALTHCHECK` against
  `/health`.
- `nllb` always starts with the stack. The backend connects to it at
  `http://nllb:8001` (set automatically by docker-compose via `NLLB_SERVICE_URL`).
- In production only `frontend` publishes a port. The backend and nllb are
  reachable only inside the compose network.

## 3. Environment variables

Canonical names (all optional):

| Variable | Purpose |
| --- | --- |
| `ENVIRONMENT` | `development` (default) / `production`. Backward-compatible alias: `APP_ENV`. |
| `LOG_LEVEL` | `INFO` (default), `DEBUG`, ... |
| `LOG_FORMAT` | `console` (default) / `json`. `json` is forced in production. |
| `DEEPGRAM_API_KEY` | Streaming ASR. Without it the backend boots but sessions stop with `deepgram_config`. |
| `TRANSLATION_API_KEY` | Cloud translation (Google/V3, DeepL, Azure). Alias: `CLOUD_TRANSLATION_API_KEY`. |
| `LLM_API_KEY` | Optional post-hoc transcript refinement (punctuation/terminology). |
| `ENABLE_LLM_REFINEMENT` | `true`/`false`; gate for the async refinement pass. |
| `CORS_ALLOW_ORIGINS` | JSON list, e.g. `["https://app.example.com"]`. Default dev origins. Never set `"*"` with credentials. |
| `WS_ALLOWED_ORIGINS` | Optional JSON list of allowed WebSocket `Origin`s. When set, `/ws/translate` rejects others with close code **1008**. Leave unset for Electron (`file://`) and mixed-origin use. |
| `NLLB_SERVICE_URL` | Backend only. `http://nllb:8001` (set automatically by docker-compose). |
| `NLLB_MODEL_NAME` | nllb container only. Default `facebook/nllb-200-distilled-600M`. |
| `NLLB_DEVICE` | nllb container only. Default `cpu` (the image ships CPU torch only). |
| `NLLB_WARM_START` | nllb container only. Default `true` (model loads in the background at boot). |
| `BACKEND_HOST` | frontend container only. Empty = same origin through nginx; set e.g. `api.example.com` for a separate API domain. |
| `BACKEND_USE_TLS` | frontend container only. `true` → the client builds `wss://`/`https://` URLs. |

## 4. Development deployment

```bash
cp .env.example .env          # optional; the stack runs without it
docker compose up --build
```

- Frontend: http://localhost:8080
- Backend (for local tooling): http://localhost:8000/health
- WebSocket: `ws://localhost:8080/ws/translate`

If port 8000 is already used by a locally running backend, remap it:

```bash
BACKEND_PORT=18000 docker compose up -d
```

Hot-reload in containers is **not** provided; for frontend/backend iteration use
the local tooling (`npm run dev`, `uv run uvicorn --reload`) instead.

## 5. Production deployment

```bash
cp .env.example .env
# in .env: ENVIRONMENT=production is forced by the prod compose file anyway;
# set real CORS_ALLOW_ORIGINS / WS_ALLOWED_ORIGINS for your domain.

docker compose -f docker-compose.prod.yml up -d --build
```

- Only port **80** is published. Terminate TLS in front of it (§10).
- The backend forces `ENVIRONMENT=production`, `LOG_FORMAT=json`, and a
  `service_healthy` gating for nginx.
- NLLB-200 always starts with the stack (no profile needed). First start
  downloads the weights (~2.5 GB) into the `nllb-models` volume; allow a few
  minutes before the model reports loaded.

## 6. Building images

```bash
docker compose build                 # frontend + backend + nllb
docker compose -f docker-compose.prod.yml build
```

## 7. Starting and stopping

```bash
docker compose up -d                 # start (detached)
docker compose ps                    # status + health
docker compose logs -f --tail=100    # stream logs
docker compose stop                  # pause (containers kept)
docker compose down                  # stop + remove containers/networks
docker compose down -v               # + delete the nllb model cache volume
```

## 8. Health checks

- `docker compose ps` shows `healthy`/`unhealthy` per container (frontend and
  backend define `HEALTHCHECK`s; the nllb image healthchecks `/health` too).
- REST: `curl http://localhost:8080/health` (through nginx) or
  `curl http://localhost:18000/health` (dev backend port).
- `GET /health` reports `status`, `env`, `version`, uptime, and provider state —
  e.g. `nllb: {"mode": "service", "service_configured": true, ...}` when
  `NLLB_SERVICE_URL` is set, or `"mode": "in_process"` with the offline extra.

## 9. WebSocket configuration

The client builds its WebSocket URL in `src/lib/wsClient.ts` with this
precedence:

1. `window.TRANSLATOR_CONFIG` (the runtime `config.js`) — set at container
   start via `BACKEND_HOST` / `BACKEND_USE_TLS`;
2. `VITE_BACKEND_HOST` / `VITE_BACKEND_USE_TLS` (build-time);
3. same origin as the page — `ws(s)://<host>/ws/translate`.

Leave `BACKEND_HOST` empty (default) to route `/ws/` through nginx with the
required upgrade headers — no extra config. Set a separate API domain only if
your TLS topology requires one (e.g. frontend and API on different hosts).

Electron: keep `WS_ALLOWED_ORIGINS` unset so the `file://` renderer connects
without an Origin.

## 10. HTTPS / WSS

nginx inside the container serves plain HTTP. Terminate TLS in front of it —
Caddy, Traefik, a cloud load balancer, or an OS-level reverse proxy:

```text
Internet --TLS--> Caddy/Traefik/LB :443 --> frontend :80 (compose)
```

Then, if the API stays same-origin, nothing else changes: the client is served
over `https://` and its same-origin WebSocket becomes `wss://` automatically.
For a separate API domain set `BACKEND_HOST=api.example.com` and
`BACKEND_USE_TLS=true`, and make sure `CORS_ALLOW_ORIGINS` and
`WS_ALLOWED_ORIGINS` list your real `https://app.example.com` origin.

## 11. Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| Backend healthy, but translation says `translation_misconfigured` | No `DEEPGRAM_API_KEY` is set. Set it in `.env` and restart. NLLB requires no API key — it runs locally inside the `nllb` container. |
| WebSocket closes immediately with **1008** | `WS_ALLOWED_ORIGINS` is set and the client's `Origin` is not listed. Add your origin, or clear the variable for Electron/`file://`. |
| Browser shows a CORS error on `/health` or `/api` | `CORS_ALLOW_ORIGINS` must contain the exact origin (scheme+host+port) of the page. |
| `Bind for 0.0.0.0:8000 failed: port is already allocated` | A local backend already owns 8000. Use `BACKEND_PORT=18000 docker compose up -d`. |
| nginx returns 502 for `/ws/` | The backend is not healthy. Check `docker compose ps`; frontend `depends_on` backend `service_healthy`. |
| WebSocket drops after ~60 s | That is the `/api`/`/health` read timeout — WebSockets use the `/ws/` location with 3600 s timeouts. Make sure the client connects to `.../ws/translate`, not `.../api/...`. |
| `nllb_warm_up_failed` / permission error under `/models` | Stale root-owned cache volume. Recreate it: `docker compose down -v` then `up`. |
| First translation is very slow after deploy | The model (~2.5 GB) is downloading into `nllb-models`; wait for `model_loaded: true` in `/health` of the nllb container. |
| Model download fails behind a corporate proxy | Set `HF_ENDPOINT` and proxy env vars on the nllb service, or pre-populate the `nllb-models` volume on a networked host. |
| Container OOM-killed during NLLB inference | The 600M fp32 model needs ~3 GB RAM. Add memory limits or run nllb on a host with more RAM; the CPU-only image has no CUDA. |
