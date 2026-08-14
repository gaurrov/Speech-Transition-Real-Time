"""
FastAPI application entrypoint.

This wires together configuration, CORS, the WebSocket audio-streaming
route, and a `/health` endpoint. Business logic (ASR, translation, VAD,
LLM refinement) lives in `app/services/*` behind provider interfaces and
is intentionally NOT implemented here -- this file only wires things up.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.utils.logging import configure_logging
from app.websocket.audio_stream import router as audio_stream_router

settings = get_settings()
configure_logging(settings.log_level)
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info("startup", env=settings.app_env)
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

app.include_router(audio_stream_router)


@app.get("/health", tags=["system"])
async def health() -> dict:
    """Lightweight liveness/readiness probe. Does not touch external providers."""
    return {
        "status": "ok",
        "env": settings.app_env,
        "asr_provider": settings.asr_provider,
        "translation_provider": settings.translation_provider,
    }



