"""
NLLB-200 translation service (internal-only).

A tiny FastAPI service that loads facebook/nllb-200 (or any
``NllbForConditionalGeneration`` model) once and serves translations over a
private HTTP API. It is meant to be reachable ONLY from the main backend
container on the Docker network -- never published to the public internet.

API
---
  GET  /health      liveness/readiness (never blocks on the model)
  POST /translate   {"text": str, "source_lang": "hin_Deva", "target_lang": "eng_Latn"}
                    -> {"translated_text": str}

Languages use FLORES-200 tokens (e.g. ``eng_Latn``, ``hin_Deva``) resolved by
the backend from its central language registry -- this service performs no
language mapping.
"""
from __future__ import annotations

import asyncio
import os
import threading
import time

import structlog
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.logging import configure_logging

logger = structlog.get_logger(__name__)
configure_logging()

_STARTED_AT = time.time()

# Process-wide model cache. NLLB-200 takes seconds to load, so it is loaded at
# most once per process and shared across requests.
_MODEL_CACHE: dict[tuple[str, str], tuple[object, object]] = {}
_MODEL_CACHE_LOCK = threading.Lock()
# Serializes tokenizer.src_lang mutation + encode + generate: torch generation
# is not safe to run concurrently on one model instance, and this is only a
# low-rate fallback path anyway.
_INFERENCE_LOCK = threading.Lock()

app = FastAPI(title="NLLB Translation Service", version="0.1.0")


class TranslateRequest(BaseModel):
    text: str
    source_lang: str  # FLORES-200 token, e.g. "eng_Latn"
    target_lang: str  # FLORES-200 token, e.g. "hin_Deva"


class TranslateResponse(BaseModel):
    translated_text: str


def _model_name() -> str:
    return os.environ.get("NLLB_MODEL_NAME", "facebook/nllb-200-distilled-600M")


def _device() -> str:
    return os.environ.get("NLLB_DEVICE", "cpu")


def _max_length() -> int:
    return int(os.environ.get("NLLB_MAX_LENGTH", "128"))


def _num_beams() -> int:
    return int(os.environ.get("NLLB_NUM_BEAMS", "4"))


def _load_model() -> tuple[object, object]:
    """Import torch/transformers and load the model + tokenizer (blocking)."""
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    key = (_model_name(), _device())
    with _MODEL_CACHE_LOCK:
        cached = _MODEL_CACHE.get(key)
        if cached is None:
            logger.info("nllb_model_load_start", model=_model_name())
            started = time.monotonic()
            tokenizer = AutoTokenizer.from_pretrained(_model_name())
            model = AutoModelForSeq2SeqLM.from_pretrained(_model_name()).to(_device())
            model.eval()
            _MODEL_CACHE[key] = (model, tokenizer)
            logger.info(
                "nllb_model_load_done",
                model=_model_name(),
                elapsed_sec=round(time.monotonic() - started, 1),
            )
        return _MODEL_CACHE[key]


def _translate(text: str, source_lang: str, target_lang: str) -> str:
    import torch

    model, tokenizer = _load_model()
    with _INFERENCE_LOCK:
        tokenizer.src_lang = source_lang
        inputs = tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=_max_length(),
        )
        with torch.inference_mode():
            outputs = model.generate(
                **inputs,
                forced_bos_token_id=tokenizer.convert_tokens_to_ids(target_lang),
                max_length=_max_length(),
                num_beams=_num_beams(),
            )
        return tokenizer.decode(outputs[0], skip_special_tokens=True)


async def _warm_up() -> None:
    try:
        await asyncio.to_thread(_load_model)
    except Exception as exc:  # pragma: no cover - depends on external download
        logger.error("nllb_warm_up_failed", error=str(exc))


@app.on_event("startup")
async def startup() -> None:
    # Warm the model in the background so the service answers /health
    # immediately while NLLB (and its weights) load in a worker thread.
    if os.environ.get("NLLB_WARM_START", "true").lower() != "false":
        asyncio.create_task(_warm_up())


@app.post("/translate")
async def translate(request: TranslateRequest) -> TranslateResponse:
    if not request.text.strip():
        return TranslateResponse(translated_text="")
    try:
        translated = await asyncio.to_thread(
            _translate, request.text, request.source_lang, request.target_lang
        )
    except Exception as exc:
        logger.error("nllb_translate_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))
    return TranslateResponse(translated_text=translated)


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "service": "nllb",
        "model": _model_name(),
        "model_loaded": bool(_MODEL_CACHE),
        "uptime_seconds": round(time.time() - _STARTED_AT, 1),
    }
