"""
HybridTranslationProvider: cloud-first with NLLB-200 fallback.

Translation strategy:
  Cloud success  -> cloud result, provider="cloud"
  Cloud failure  -> NLLB fallback -> NLLB result, provider="nllb"
  Both fail      -> raises TranslationError("translation_failed")

A transient cloud failure therefore degrades one utterance to the offline
provider instead of failing the whole meeting. Fallbacks are decided purely
on ``TranslationError`` from the cloud provider; no per-language-pair logic
lives here.
"""
from __future__ import annotations

import structlog

from app.config import Settings, get_settings
from app.models.schemas import TranslationSegment
from app.services.translation.base import TranslationError, TranslationProvider
from app.services.translation.cloud_provider import CloudTranslationProvider
from app.services.translation.nllb_provider import NLLBTranslationProvider

logger = structlog.get_logger(__name__)


class HybridTranslationProvider(TranslationProvider):
    name = "hybrid"

    def __init__(
        self,
        settings: Settings | None = None,
        cloud: TranslationProvider | None = None,
        nllb: TranslationProvider | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._cloud = cloud or CloudTranslationProvider(self._settings)
        self._nllb = nllb or NLLBTranslationProvider(self._settings)

    async def translate(
        self,
        *,
        segment_id: str,
        text: str,
        source_language: str,
        target_language: str,
        is_final: bool,
    ) -> TranslationSegment:
        # Short-circuit: if the cloud API key is not configured, skip the cloud
        # provider entirely instead of raising + catching TranslationError on
        # every single utterance.  This avoids per-utterance log spam and makes
        # the fallback path explicit.
        cloud_configured = bool(self._settings.cloud_translation_api_key)
        if cloud_configured:
            try:
                return await self._cloud.translate(
                    segment_id=segment_id,
                    text=text,
                    source_language=source_language,
                    target_language=target_language,
                    is_final=is_final,
                )
            except TranslationError as cloud_error:
                logger.warning(
                    "translation_cloud_failed",
                    code=cloud_error.code,
                    message=cloud_error.message,
                    fallback="nllb",
                    segment_id=segment_id,
                )
        else:
            logger.debug(
                "translation_cloud_skipped",
                reason="no_api_key",
                fallback="nllb",
                segment_id=segment_id,
            )

        try:
            return await self._nllb.translate(
                segment_id=segment_id,
                text=text,
                source_language=source_language,
                target_language=target_language,
                is_final=is_final,
            )
        except TranslationError as nllb_error:
            raise TranslationError(
                "translation_failed",
                f"{'Cloud and NLLB both' if cloud_configured else 'NLLB'} failed: {nllb_error.message}",
            ) from nllb_error

    async def warm_up(self) -> None:
        # Intentionally a no-op: NLLB is loaded lazily on first fallback so
        # session start is never delayed by the heavy model.
        return

    async def health_check(self) -> bool:
        return await self._cloud.health_check()

    async def close(self) -> None:
        await self._cloud.close()
        await self._nllb.close()
