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

Environment variables
---------------------
NLLB_MODEL_NAME      Model identifier (default: facebook/nllb-200-distilled-600M)
NLLB_DEVICE          "cpu" or "cuda" (default: auto-detect cuda, fall back to cpu)
NLLB_MAX_LENGTH      Max tokens for encode/decode (default: 80)
NLLB_NUM_BEAMS       Beam search width (default: 1, greedy)
NLLB_NUM_THREADS     CPU threads for torch inference (default: auto)
NLLB_LENGTH_PENALTY  Generation length penalty (default: 1.0)
NLLB_REQUEST_TIMEOUT Seconds before a translation request is cancelled (default: 30)
NLLB_WARM_START      Load model at startup (default: true)
"""
from __future__ import annotations

import asyncio
import os
import threading
import time

import structlog
from app.logging import configure_logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logger = structlog.get_logger(__name__)
configure_logging()

_STARTED_AT = time.time()


# ---------------------------------------------------------------------------
# Structured errors (mirrors the backend's TranslationError)
# ---------------------------------------------------------------------------


class TranslationError(Exception):
    """Raised for known, recoverable translation failures."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)

# Process-wide model cache. NLLB-200 takes seconds to load, so it is loaded at
# most once per process and shared across requests.
_MODEL_CACHE: dict[tuple[str, str], tuple[object, object]] = {}
_MODEL_CACHE_LOCK = threading.Lock()
# Serializes tokenizer.src_lang mutation + encode + generate: torch generation
# is not safe to run concurrently on one model instance.
_INFERENCE_LOCK = threading.Lock()

# Runtime stats (reset on process restart).
_translation_count = 0
_translation_latency_sum = 0.0

app = FastAPI(title="NLLB Translation Service", version="0.2.0")


class TranslateRequest(BaseModel):
    text: str
    source_lang: str  # FLORES-200 token, e.g. "eng_Latn"
    target_lang: str  # FLORES-200 token, e.g. "hin_Deva"


class TranslateResponse(BaseModel):
    translated_text: str


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------


def _model_name() -> str:
    return os.environ.get("NLLB_MODEL_NAME", "facebook/nllb-200-distilled-600M")


def _device() -> str:
    """Return the configured device, auto-detecting CUDA when not explicitly set."""
    explicit = os.environ.get("NLLB_DEVICE")
    if explicit:
        return explicit
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except ImportError:
        pass
    return "cpu"


def _max_length() -> int:
    return int(os.environ.get("NLLB_MAX_LENGTH", "80"))


def _num_beams() -> int:
    return int(os.environ.get("NLLB_NUM_BEAMS", "1"))


def _num_threads() -> int | None:
    val = os.environ.get("NLLB_NUM_THREADS")
    return int(val) if val else None


def _length_penalty() -> float:
    return float(os.environ.get("NLLB_LENGTH_PENALTY", "1.0"))


def _request_timeout() -> float:
    return float(os.environ.get("NLLB_REQUEST_TIMEOUT", "30"))


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------


def _load_model() -> tuple[object, object]:
    """Import torch/transformers and load the model + tokenizer (blocking).

    The model is cached per (name, device) pair.  Subsequent calls return the
    cached instance without re-downloading or re-loading weights.
    """
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    key = (_model_name(), _device())
    with _MODEL_CACHE_LOCK:
        cached = _MODEL_CACHE.get(key)
        if cached is not None:
            return cached

        import torch

        num_threads = _num_threads()
        if num_threads is not None and _device() == "cpu":
            torch.set_num_threads(num_threads)

        logger.info(
            "nllb_model_load_start",
            model=_model_name(),
            device=_device(),
            num_beams=_num_beams(),
            max_length=_max_length(),
            num_threads=num_threads,
        )
        started = time.monotonic()
        tokenizer = AutoTokenizer.from_pretrained(_model_name())
        model = AutoModelForSeq2SeqLM.from_pretrained(_model_name()).to(_device())
        model.eval()
        elapsed = round(time.monotonic() - started, 1)
        _MODEL_CACHE[key] = (model, tokenizer)
        logger.info(
            "nllb_model_load_done",
            model=_model_name(),
            device=_device(),
            elapsed_sec=elapsed,
        )
        return _MODEL_CACHE[key]


# ---------------------------------------------------------------------------
# Translation (runs in a worker thread via asyncio.to_thread)
# ---------------------------------------------------------------------------


def _translate_sync(
    text: str,
    source_lang: str,
    target_lang: str,
    request_id: str,
    queue_enter_ts: float,
) -> tuple[str, dict[str, float]]:
    """Blocking translation call.  Invoked inside ``asyncio.to_thread``.

    Returns (translated_text, timing_dict) where timing_dict contains
    monotonic timestamps for queue_enter, lock_acquired, inference_start,
    inference_end.
    """
    import torch

    timing: dict[str, float] = {}
    timing["queue_enter"] = queue_enter_ts

    model, tokenizer = _load_model()

    # How long we waited behind _INFERENCE_LOCK (queueing delay).
    timing["lock_acquired"] = time.monotonic()
    queueing_ms = round((timing["lock_acquired"] - queue_enter_ts) * 1000, 1)

    with _INFERENCE_LOCK:
        timing["inference_start"] = time.monotonic()
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
                do_sample=False,
                length_penalty=_length_penalty(),
            )
        timing["inference_end"] = time.monotonic()
        result = tokenizer.decode(outputs[0], skip_special_tokens=True)

    logger.info(
        "nllb_inference",
        request_id=request_id,
        src=source_lang,
        tgt=target_lang,
        text_len=len(text),
        queueing_ms=queueing_ms,
        inference_ms=round(
            (timing["inference_end"] - timing["inference_start"]) * 1000, 1
        ),
        total_ms=round(
            (timing["inference_end"] - queue_enter_ts) * 1000, 1
        ),
    )
    return result, timing


# ---------------------------------------------------------------------------
# Warm-up
# ---------------------------------------------------------------------------


async def _warm_up() -> None:
    try:
        logger.info("nllb_warm_up_start")
        started = time.monotonic()
        await asyncio.to_thread(_load_model)
        elapsed = round(time.monotonic() - started, 1)
        logger.info("nllb_warm_up_done", elapsed_sec=elapsed)
    except Exception as exc:  # pragma: no cover - depends on external download
        logger.error("nllb_warm_up_failed", error=str(exc))


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@app.on_event("startup")
async def startup() -> None:
    if os.environ.get("NLLB_WARM_START", "true").lower() != "false":
        asyncio.create_task(_warm_up())


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/translate")
async def translate(request: TranslateRequest) -> TranslateResponse:
    global _translation_count, _translation_latency_sum

    if not request.text.strip():
        return TranslateResponse(translated_text="")

    text_len = len(request.text)
    timeout = _request_timeout()
    import uuid as _uuid

    request_id = _uuid.uuid4().hex[:12]

    logger.info(
        "nllb_request_received",
        request_id=request_id,
        src=request.source_lang,
        tgt=request.target_lang,
        text_len=text_len,
    )

    try:
        started = time.monotonic()
        queue_enter_ts = started
        translated, timing = await asyncio.wait_for(
            asyncio.to_thread(
                _translate_sync,
                request.text,
                request.source_lang,
                request.target_lang,
                request_id,
                queue_enter_ts,
            ),
            timeout=timeout,
        )
        latency_ms = round((time.monotonic() - started) * 1000, 1)
        _translation_count += 1
        _translation_latency_sum += latency_ms
        logger.info(
            "nllb_translate_ok",
            request_id=request_id,
            src=request.source_lang,
            tgt=request.target_lang,
            text_len=text_len,
            latency_ms=latency_ms,
        )
    except TimeoutError:
        logger.error(
            "nllb_translate_timeout",
            request_id=request_id,
            src=request.source_lang,
            tgt=request.target_lang,
            text_len=text_len,
            timeout_sec=timeout,
        )
        raise HTTPException(
            status_code=504,
            detail=f"Translation timed out after {timeout}s",
        )
    except TranslationError as exc:
        logger.error(
            "nllb_translate_failed",
            request_id=request_id,
            src=request.source_lang,
            tgt=request.target_lang,
            text_len=text_len,
            error_code=exc.code,
            error=str(exc),
        )
        raise HTTPException(status_code=422, detail=exc.detail)
    except Exception as exc:
        logger.error(
            "nllb_translate_error",
            request_id=request_id,
            src=request.source_lang,
            tgt=request.target_lang,
            text_len=text_len,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail=str(exc))

    return TranslateResponse(translated_text=translated)


@app.get("/health")
async def health() -> dict:
    model_loaded = bool(_MODEL_CACHE)
    avg_latency = (
        round(_translation_latency_sum / _translation_count, 1)
        if _translation_count
        else None
    )
    return {
        "status": "ok",
        "service": "nllb",
        "model": _model_name(),
        "device": _device(),
        "model_loaded": model_loaded,
        "num_beams": _num_beams(),
        "max_length": _max_length(),
        "translation_count": _translation_count,
        "avg_latency_ms": avg_latency,
        "uptime_seconds": round(time.time() - _STARTED_AT, 1),
    }
