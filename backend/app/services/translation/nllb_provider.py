"""
NLLBTranslationProvider: offline/fallback translation using NLLB-200.

The model + torch runtime are heavy (see the ``offline`` extra in
pyproject.toml) and only install cleanly on Python 3.11/3.12, so everything
is loaded lazily on first use inside a thread executor to keep the event
loop unblocked. If torch/transformers are missing, ``translate`` raises
``TranslationError("nllb_model_unavailable")`` instead of crashing -- the
hybrid provider then surfaces a clear, non-fatal error.

Language codes are resolved through the central registry (``languages.py``),
so there are no hardcoded language-pair conditions here.
"""
from __future__ import annotations

import asyncio
import threading

import structlog

from app.config import Settings, get_settings
from app.models.schemas import TranslationSegment
from app.services.translation.base import TranslationError, TranslationProvider
from app.services.translation.languages import nllb_code

logger = structlog.get_logger(__name__)

# Process-wide model cache shared by every NLLBTranslationProvider instance.
# Loading torch + a 600M-parameter model takes seconds and must happen at most
# once per process (keyed by model name + device), otherwise every session start
# would pay the full load cost again.
_MODEL_CACHE: dict[tuple[str, str], tuple[object, object]] = {}
_MODEL_CACHE_LOCK = threading.Lock()

# Serializes the tokenizer.src_lang mutation + encode span. The tokenizer is
# shared process-wide via _MODEL_CACHE and each translation runs on its own
# asyncio.to_thread worker, so two sessions translating different source
# languages concurrently would otherwise race on tokenizer.src_lang.
_TOKENIZER_LOCK = threading.Lock()


def _reset_model_cache() -> None:
    """Clear the shared model cache (used by tests for isolation)."""
    with _MODEL_CACHE_LOCK:
        _MODEL_CACHE.clear()


class NLLBTranslationProvider(TranslationProvider):
    name = "nllb"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._model = None
        self._tokenizer = None
        self._load_lock = asyncio.Lock()

    async def warm_up(self) -> None:
        async with self._load_lock:
            if self._model is None:
                try:
                    self._model, self._tokenizer = await asyncio.to_thread(
                        self._get_or_load_model
                    )
                except ImportError as exc:
                    raise TranslationError(
                        "nllb_model_unavailable",
                        "NLLB translation requires the `offline` extra "
                        "(torch + transformers); install with `uv sync --extra offline`",
                    ) from exc
                except Exception as exc:
                    raise TranslationError(
                        "nllb_model_unavailable",
                        f"Failed to load the NLLB model: {exc}",
                    ) from exc

    def _get_or_load_model(self) -> tuple[object, object]:
        """Return the shared (model, tokenizer), loading them once process-wide."""
        key = (self._settings.nllb_model_name, self._settings.nllb_device)
        cached = _MODEL_CACHE.get(key)
        if cached is not None:
            return cached
        with _MODEL_CACHE_LOCK:
            cached = _MODEL_CACHE.get(key)
            if cached is None:
                cached = self._load_model()
                _MODEL_CACHE[key] = cached
        return cached

    async def translate(
        self,
        *,
        segment_id: str,
        text: str,
        source_language: str,
        target_language: str,
        is_final: bool,
    ) -> TranslationSegment:
        if self._model is None:
            await self.warm_up()
        if self._model is None or self._tokenizer is None:
            raise TranslationError(
                "nllb_model_unavailable", "NLLB model failed to load"
            )
        # Resolve codes first so an unsupported language fails fast and clearly.
        if source_language == "auto":
            raise TranslationError(
                "unsupported_language",
                "NLLB does not support auto-detect; configure a concrete "
                "source language or use a cloud/hybrid provider with an API key",
            )
        nllb_code(source_language)
        nllb_code(target_language)

        translated = await asyncio.to_thread(
            self._translate_engine, text, source_language, target_language
        )
        return TranslationSegment(
            segment_id=segment_id,
            source_text=text,
            translated_text=translated,
            source_language=source_language,
            target_language=target_language,
            is_final=is_final,
            provider=self.name,
        )

    # --- internal: heavy lifting, executed off the event loop --------------

    def _load_model(self) -> tuple[object, object]:
        """Import torch/transformers and load model + tokenizer (blocking)."""
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(self._settings.nllb_model_name)
        model = AutoModelForSeq2SeqLM.from_pretrained(
            self._settings.nllb_model_name
        ).to(self._settings.nllb_device)
        model.eval()
        return model, tokenizer

    def _translate_engine(self, text: str, source_language: str, target_language: str) -> str:
        import torch

        tokenizer = self._tokenizer
        model = self._model
        target_token = nllb_code(target_language)
        with _TOKENIZER_LOCK:
            tokenizer.src_lang = nllb_code(source_language)  # set before encoding
            inputs = tokenizer(
                text,
                return_tensors="pt",
                truncation=True,
                max_length=self._settings.nllb_max_length,
            )
        with torch.inference_mode():
            outputs = model.generate(
                **inputs,
                forced_bos_token_id=tokenizer.convert_tokens_to_ids(target_token),
                max_length=self._settings.nllb_max_length,
                num_beams=self._settings.nllb_num_beams,
            )
        return tokenizer.decode(outputs[0], skip_special_tokens=True)
