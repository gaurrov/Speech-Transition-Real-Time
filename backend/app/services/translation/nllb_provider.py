"""
NLLBTranslationProvider: offline/fallback translation using NLLB-200.

Loaded lazily and only when selected, since the model + torch runtime
are heavy (see the `offline-translation` extra in pyproject.toml). This
provider trades latency for availability -- it should be used when the
cloud provider's `health_check()` fails or when running fully offline.
"""
from __future__ import annotations

from app.config import get_settings
from app.models.schemas import TranslationSegment
from app.services.translation.base import TranslationProvider


class NLLBTranslationProvider(TranslationProvider):
    name = "nllb"

    def __init__(self) -> None:
        self._settings = get_settings()
        self._model = None
        self._tokenizer = None

    async def warm_up(self) -> None:
        # TODO: lazily load `self._settings.nllb_model_name` via transformers
        # onto `self._settings.nllb_device`, run in a thread executor to
        # avoid blocking the event loop.
        raise NotImplementedError("NLLBTranslationProvider.warm_up is not yet implemented")

    async def translate(
        self,
        *,
        segment_id: str,
        text: str,
        source_language: str,
        target_language: str,
        is_final: bool,
    ) -> TranslationSegment:
        raise NotImplementedError("NLLBTranslationProvider.translate is not yet implemented")
