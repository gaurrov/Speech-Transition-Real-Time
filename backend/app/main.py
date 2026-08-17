"""
FastAPI application entrypoint.

This wires together configuration, CORS, the WebSocket audio-streaming
route, and a `/health` endpoint. Business logic (ASR, translation, VAD,
LLM refinement) lives in `app/services/*` behind provider interfaces and
is intentionally NOT implemented here -- this file only wires things up.
"""
from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.services.translation import (
    _offline_runtime_available,
    is_translation_available,
    probe_nllb_service,
    warn_on_translation_misconfiguration,
)
from app.utils.logging import configure_logging
from app.websocket.translate_stream import router as translate_stream_router

settings = get_settings()
configure_logging(settings.log_level, settings.log_format)
logger = structlog.get_logger(__name__)

_STARTED_AT = time.time()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info("startup", env=settings.app_env)
    warn_on_translation_misconfiguration(settings)
    reachable = await probe_nllb_service()
    logger.info(
        "nllb_startup_probe",
        service_reachable=reachable,
        mode="service" if settings.nllb_service_url else "in_process",
    )
    yield


app = FastAPI(
    title="Real-Time Translator API",
    description="Streaming ASR -> translation -> refinement backend for live meeting captions.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(translate_stream_router)


@app.get("/health", tags=["system"])
async def health() -> dict:
    """Liveness/readiness probe. Touches external providers only to verify
    reachability; never exposes secrets."""
    nllb_service_reachable = await probe_nllb_service()
    translation_available = await is_translation_available(settings)

    return {
        "status": "ok",
        "env": settings.app_env,
        "version": app.version,
        "uptime_seconds": round(time.time() - _STARTED_AT, 1),
        "asr_provider": settings.asr_provider,
        "translation": {
            "available": translation_available,
            "provider": settings.translation_provider,
        },
        "websocket": {
            "endpoint": "/ws/translate",
            "origin_policy": "allowlist"
            if settings.ws_allowed_origins
            else "any",
        },
        "providers": {
            "deepgram": {
                "configured": bool(settings.deepgram_api_key),
            },
            "cloud_translation": {
                "configured": bool(settings.cloud_translation_api_key),
            },
            "nllb": {
                "mode": "service" if settings.nllb_service_url else "in_process",
                "service_configured": bool(settings.nllb_service_url),
                "service_reachable": nllb_service_reachable,
                "in_process_available": _offline_runtime_available(),
            },
        },
    }



