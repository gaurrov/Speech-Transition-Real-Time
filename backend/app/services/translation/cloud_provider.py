"""
CloudTranslationProvider: default low-latency translation path.

Scaffold only -- wire up the concrete cloud API (Google Cloud
Translation, DeepL, or Azure Translator, selected via
`settings.cloud_translation_provider_name`) in `translate()`.
"""
from __future__ import annotations

import httpx

from app.config import get_settings
from app.models.schemas import TranslationSegment
from app.services.translation.base import TranslationProvider


class CloudTranslationProvider(TranslationProvider):
    name = "cloud"

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client = httpx.AsyncClient(timeout=5.0)

    async def translate(
        self,
        *,
        segment_id: str,
        text: str,
        source_language: str,
        target_language: str,
        is_final: bool,
    ) -> TranslationSegment:
        # TODO: call self._settings.cloud_translation_provider_name's API.
        raise NotImplementedError("CloudTranslationProvider.translate is not yet implemented")

    async def health_check(self) -> bool:
        # TODO: cheap ping/credentials check used by the hybrid router.
        return True
